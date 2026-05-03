import os
import time
import datetime
import json
import re
import sys
import importlib
import subprocess
import queue

from utils.srt_manager import (
    RE_ITALIC_S, RE_ITALIC_D, RE_ALIGNMENT, 
    parse_srt_blocks, get_upcoming_cues, extract_chunk_metadata,
    strip_srt, load_srt_index_to_text, load_srt_full_history, validate_srt_file
)
import threading
from core.constants import (
    get_json_schema, get_workflow_step_templates, build_technical_rules, 
    STEP_HEADER_EN, get_user_prompt_prefix, get_special_instructions_header,
    get_technical_rules_header, get_exact_count_rule,
    get_exact_indices_rule, get_do_not_translate_rule, get_tag_rule
)
from core.text_processing import fix_rtl, pre_repair_json, check_heuristics, strip_music_glyphs_batch, force_split_overlong_line, cleanup_failed_translation
from core.llm_api import call_llm, call_llm_judge, generate_batch_schema
from utils.app_utils import log, file_log, format_cost_display, get_eta_string, pretty_json
from core.translation_stats import _inc_by_size, make_stats, print_stats
from core.session_manager import (
    get_next_checkpoint_file, resolve_checkpoint_paths, save_checkpoint,
    cleanup_checkpoint, build_checkpoint_payload, restore_profile_from_checkpoint
)
from core.audit_manager import run_audit_pipeline

RE_SDH_PUNCT = re.compile(r"[-.\s]*[\[(].*?[\])][-.\s]*")
RE_SYS_IDX = re.compile(r'###\s*(\d+)\.')

def run_pipeline(self, config):
    try:
        resume_mode = config["resume_mode"]
        self.debug_mode = config.get("debug_mode", False)
        model_cfg = config["model_cfg"]
        api_key = config["api_key"]
        batch_size = config["batch_size"]
        session_log_file = config["session_log_file"]
        
        profile = config.get("language_profile")
        if not profile:
            from utils.settings import SETTINGS
            profile = SETTINGS.get_active_profile()
        self.profile = profile
        
        ranges_str = "".join([f"\\u{s:04x}-\\u{e:04x}" for s, e in profile.target_unicode_ranges])
        self.re_ghost_chars = re.compile(rf'\n[a-zA-Z]{{1,2}}(?=\s|[{ranges_str}]|<|♪)')
        self.re_name_labels = re.compile(rf'([A-Z][a-z]+|\([{ranges_str}]+\))')
        self.re_newline_cleanup = re.compile(profile.newline_regex)
        
        checkpoint_dir = config["checkpoint_dir"]
        sysprm_dir = config["sysprm_dir"]
        english_subs_dir = config["english_subs_dir"]
        output_dir = config["output_dir"]

        if resume_mode:
            checkpoint_data = config["checkpoint_data"]
            sys_file, srt_file = resolve_checkpoint_paths(checkpoint_data, sysprm_dir, english_subs_dir)
            output_file = checkpoint_data['output_file']
            current_index = checkpoint_data['current_index']
            processed = checkpoint_data.get('processed', 0)
            total_main_cost = checkpoint_data.get('total_main_cost', checkpoint_data.get('total_cost', 0.0))
            total_judge_cost = checkpoint_data.get('total_judge_cost', 0.0)
            context_state = checkpoint_data['context_state']
            
            restore_profile_from_checkpoint(profile, checkpoint_data)
            current_checkpoint_file = config["checkpoint_file_path"]
            
            if not os.path.exists(srt_file) or not os.path.exists(sys_file):
                log(self.log_queue, session_log_file, "❌ Error: Original files missing. Cannot resume.")
                self.ui_queue.put(("finished", None))
                return

            self.current_output_file = output_file
            log(self.log_queue, session_log_file, f"\n✅ Resuming session: {srt_file} from block {current_index}")
            log(self.log_queue, session_log_file, f"📁 Using Checkpoint File: {current_checkpoint_file}")
        else:
            sys_file = os.path.join(sysprm_dir, config["sys_name"])
            srt_file = os.path.join(english_subs_dir, config["srt_name"])
            current_checkpoint_file = get_next_checkpoint_file(checkpoint_dir)

            base_name = os.path.basename(srt_file)
            output_file = os.path.join(output_dir, base_name.replace('.srt', f'_{model_cfg["name"]}_{profile.target_lang_code}.srt'))
            self.current_output_file = output_file
            current_index = 0
            processed = 0
            total_main_cost = 0.0
            total_judge_cost = 0.0
            log(self.log_queue, session_log_file, f"\n📁 Creating new Checkpoint File: {current_checkpoint_file}")

        bypass_log_file = None
        bypass_count = 0

        log(self.log_queue, session_log_file, f"📝 Target File: {os.path.basename(srt_file)}")
        if resume_mode:
            log(self.log_queue, session_log_file, f"🔄 Resuming from index: {current_index}")

        from core.translation.context_resolver import resolve_initial_context
        (profile, series_context, initial_context_str, context_state,
         last_idx, illegal_labels, srt_content, ordered_srt_indices, prompt_prefix) = resolve_initial_context(config, self.log_queue, session_log_file)
         
        self.illegal_labels = illegal_labels
        idx_workflow = last_idx + 1
        idx_tech = idx_workflow + 1
        idx_clean = idx_tech + 1

        use_scratchpad = model_cfg.get("enable_scratchpad", True)
        
        from core.translation.prompt_builder import build_system_prompt
        system_prompt = build_system_prompt(profile, model_cfg, idx_workflow, idx_tech, idx_clean, prompt_prefix, series_context)

        log(self.log_queue, session_log_file, f"🚀 [Mode: {'High-Quality (Scratchpad)' if use_scratchpad else 'Efficiency (Direct)'}] Starting translation with {model_cfg['name']}...")

        blocks, eng_by_index, _ = parse_srt_blocks(srt_content)
        total_blocks = len(blocks)

        from core.translation.pipeline_helpers import backfill_history, determine_effective_batch_size
        translated_target_by_index = backfill_history(
            resume_mode, output_file, srt_content, ordered_srt_indices, 
            current_index, eng_by_index, self.ui_queue, self.log_queue, session_log_file
        )
        effective_batch_size, override_msg = determine_effective_batch_size(resume_mode, checkpoint_data if resume_mode else {}, batch_size)

        if resume_mode:
            stats = make_stats(resume_from=checkpoint_data.get("stats"))
        else:
            stats = make_stats()

        elapsed_at_session_start = stats["total_elapsed_seconds"]
        session_start_time = time.time()

        def push_eta():
            if processed > 0:
                t = elapsed_at_session_start + (time.time() - session_start_time)
                time_str, finish_str, eta_secs = get_eta_string(t, processed, total_blocks)
                self.ui_queue.put(("eta", (time_str, finish_str, eta_secs)))
                if self.shared_state:
                    self.shared_state.update_eta(time_str, finish_str)

        start_time = time.time()
        session_processed = 0

        self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
        if self.shared_state:
            self.shared_state.update_cost(total_main_cost, total_judge_cost, format_cost_display(total_main_cost, total_judge_cost))
        if stats.get("total_interventions", 0) > 0:
            self.ui_queue.put(("intervention_count", stats["total_interventions"]))

        log(self.log_queue, session_log_file, f"🚀 Starting Protected AI Translation with {model_cfg['provider']}")
        
        if resume_mode:
            if override_msg:
                log(self.log_queue, session_log_file, f"📦 Batch: {batch_size}{override_msg}")
            elif effective_batch_size != batch_size:
                log(self.log_queue, session_log_file, f"📦 Batch: configured {batch_size} | continuing with effective size {effective_batch_size} (checkpoint memory)")
            else:
                log(self.log_queue, session_log_file, f"📦 Batch Size: {effective_batch_size}")
        else:
            log(self.log_queue, session_log_file, f"📦 Batch Size: {effective_batch_size} | Safety Net: ACTIVE")

        self.ui_queue.put(("progress", (processed, total_blocks)))
        if self.shared_state:
            self.shared_state.update_progress(processed, total_blocks)

        if resume_mode:
            all_calls = stats.get("llm_call_times_new", []) + stats.get("llm_call_times_retry", [])
            total_duration = sum(c[0] for c in all_calls)
            total_load = sum(c[1] for c in all_calls)
            if total_duration > 0:
                historical_speed = total_load / total_duration
            
            self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
            if self.shared_state:
                self.shared_state.update_cost(total_main_cost, total_judge_cost)

        file_mode = 'a' if resume_mode else 'w'
        success_streak = 0
        
        from core.translation.batch_state import BatchState
        from core.translation.pipeline_helpers import evaluate_batch_success, evaluate_batch_failure, prepare_batch_prompt

        with open(output_file, file_mode, encoding='utf-8') as f_out:
            while current_index < total_blocks and not self.should_stop:
                upcoming_cues = get_upcoming_cues(blocks, current_index)
                self.ui_queue.put(("upcoming", upcoming_cues))

                state = BatchState(
                    current_batch_size=effective_batch_size,
                    effective_batch_size=effective_batch_size,
                    success_streak=success_streak,
                    failures_at_current_size=0,
                    min_batch_failures=0,
                    attempted_batch_sizes=[],
                    batch_success=False
                )

                last_judge_error = ""
                last_judged_indices = set()
                previous_overlong_indices = set()
                pipeline_start_time = time.time()
                
                while not state.batch_success and not self.should_stop:
                    batch_diagnostics_logged = False
                    native_audit_reason = ""
                    state.attempted_batch_sizes.append(state.current_batch_size)
                    start_idx = current_index
                    end_idx = min(current_index + state.current_batch_size, total_blocks)
                    expected_count = end_idx - start_idx
                    
                    final_prompt, indices, original_metadata, input_payload, pipeline_load, batch_italic_indices, batch_alignment_map = prepare_batch_prompt(
                        start_idx, end_idx, total_blocks, blocks, profile, 
                        context_state, model_cfg, use_scratchpad, 
                        last_judge_error, last_judged_indices, self.debug_mode, 
                        self.illegal_labels, self.log_queue, session_log_file, RE_SDH_PUNCT
                    )

                    raw_res = None
                    _batch_system_prompt = system_prompt
                    _batch_user_prompt = final_prompt
                    try:
                        log(self.log_queue, session_log_file, f"⏳ Sending Batch (Indices: {indices[0]}-{indices[-1]} | Batch Size: {expected_count})...")
                        is_retry = (len(state.attempted_batch_sizes) > 1)
                        batch_load = sum(len(str(val)) for val in input_payload.values())
                        self.ui_queue.put(("timer_start", {"size": len(input_payload), "load": batch_load, "is_retry": is_retry}))

                        if self.shared_state:
                            trend = -1 if is_retry else 0
                            if not is_retry:
                                self.shared_state.update_audit(batch_size=expected_count, batch_trend=trend, last_decision="✦ Fresh Batch")
                            else:
                                self.shared_state.update_audit(batch_size=expected_count, batch_trend=trend)
                            
                            status_txt = "Translating (Retry)" if is_retry else "Translating"
                            status_clr = "#f59e0b" if is_retry else "#0ea5e9"
                            self.shared_state.update_status(status_txt, status_clr)

                        stats["total_batches_attempted"] += 1
                        if is_retry:
                            stats["total_retries"] += 1
                        batch_call_start = time.time()

                        temp_cfg = model_cfg.copy()
                        if state.current_batch_size == 2:
                            if state.min_batch_failures == 1:
                                temp_cfg['temperature'] = 0.3
                                log(self.log_queue, session_log_file, "🌡️ [Heat-up] Minimal batch attempt 2: Setting temperature to 0.3")
                            elif state.min_batch_failures == 2:
                                temp_cfg['temperature'] = 0.7
                                log(self.log_queue, session_log_file, "🔥 [High Heat] Minimal batch attempt 3: Setting temperature to 0.7")

                        raw_res, in_tokens, out_tokens, cached_tokens, reasoning_tokens = call_llm(temp_cfg, system_prompt, final_prompt, api_key, indices_list=indices)

                        if getattr(self, 'debug_mode', False) and raw_res:
                            timestamp_str = datetime.datetime.now().strftime("%H:%M:%S")
                            file_log(session_log_file, f"\n[{timestamp_str}] --- DEBUG TRANSACTION ---")
                            file_log(session_log_file, f"SYSTEM PROMPT:\n{system_prompt.strip()}\n")
                            file_log(session_log_file, f"USER PROMPT:\n{final_prompt.strip()}\n")
                            
                            if indices:
                                schema_dump = json.dumps(generate_batch_schema(indices, use_scratchpad=use_scratchpad, profile=profile), ensure_ascii=False, indent=2)
                                file_log(session_log_file, f"STRUCTURED OUTPUT SCHEMA:\n{schema_dump}\n")

                            try:
                                pretty_res = json.dumps(json.loads(pre_repair_json(raw_res)), indent=4, ensure_ascii=False)
                            except:
                                pretty_res = raw_res.strip()

                            file_log(session_log_file, f"RAW LLM RESPONSE:\n{pretty_res}\n{'-'*38}\n")
                            batch_diagnostics_logged = True

                        _call_duration = time.time() - batch_call_start
                        if is_retry:
                            stats["llm_call_times_retry"].append((_call_duration, batch_load))
                        else:
                            stats["llm_call_times_new"].append((_call_duration, batch_load))

                        self.ui_queue.put(("timer_stop", batch_load))
                        
                        batch_cost, hit_str, hit_pct, brain_str = self._calculate_costs(in_tokens, out_tokens, cached_tokens, reasoning_tokens, model_cfg)

                        if self.shared_state:
                            self.shared_state.update_telemetry(cache_hit_percent=int(hit_pct)) 

                        total_main_cost += batch_cost
                        
                        self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                        if self.shared_state:
                            self.shared_state.update_cost(total_main_cost, total_judge_cost, format_cost_display(total_main_cost, total_judge_cost))
                        
                        def fmt_val(v): return f"{int(v):,}" if v > 100 else f"${v:.5f}"

                        log(self.log_queue, session_log_file, f"💰 [Main Model] Batch: {fmt_val(batch_cost)} (In: {in_tokens:,}{hit_str} / Out: {out_tokens:,}{brain_str}) | Total: {fmt_val(total_main_cost)}")

                        pipeline_velocity = batch_load / _call_duration if _call_duration > 0 else 0

                        from core.translation.response_processor import process_llm_response
                        received_dict, res_json = process_llm_response(
                            raw_res, input_payload, batch_italic_indices, 
                            batch_alignment_map, profile, stats, 
                            session_log_file, indices, state.current_batch_size, 
                            debug_mode=getattr(self, 'debug_mode', False), log_queue=self.log_queue
                        )

                        config["illegal_labels"] = getattr(self, 'illegal_labels', [])
                        batch_passed, last_judge_error, last_judged_indices, j_cost_delta, previous_overlong_indices = run_audit_pipeline(
                            indices=indices,
                            input_payload=input_payload,
                            received_dict=received_dict,
                            config=config,
                            profile=profile,
                            stats=stats,
                            log_queue=self.log_queue,
                            ui_queue=self.ui_queue,
                            session_log_file=session_log_file,
                            shared_state=self.shared_state,
                            previous_overlong_indices=previous_overlong_indices,
                            current_batch_size=state.current_batch_size,
                            ordered_srt_indices=ordered_srt_indices,
                            eng_by_index=eng_by_index,
                            translated_target_by_index=translated_target_by_index,
                            calculate_costs_func=self._calculate_costs,
                            push_eta_func=push_eta
                        )

                        if not batch_passed:
                            raise ValueError("Audit/Judge Rejection")

                        total_judge_cost += j_cost_delta
                        self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                        if self.shared_state:
                            self.shared_state.update_cost(total_main_cost, total_judge_cost, format_cost_display(total_main_cost, total_judge_cost))

                        self._finalize_batch_success(
                            original_metadata, received_dict, f_out, 
                            translated_target_by_index, res_json, context_state, 
                            stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
                        )

                        processed += expected_count 
                        session_processed += expected_count
                        
                        evaluate_batch_success(state, batch_size, self.log_queue, session_log_file, stats)
                        effective_batch_size = state.effective_batch_size
                        success_streak = state.success_streak
                        
                        speed_fmt = f"{pipeline_velocity:.2f}" if pipeline_velocity < 10 else f"{pipeline_velocity:.1f}"
                        log(self.log_queue, session_log_file, f"✅ Batch {indices[0]}-{indices[-1]} saved successfully. {speed_fmt}ch/s")
                        last_judge_error = ""
                        last_judged_indices = set()

                        if self.shared_state:
                            self.shared_state.update_status("Idle", "#7f8c8d")

                    except Exception as e:
                        batch_label = f"{indices[0] if indices else '?'}-{indices[-1] if indices else '?'}"
                        self.log_queue.put(f"⚠️ Batch Failure: {e}")

                        if self.shared_state:
                            e_str = str(e)
                            if "Heuristic Rejection" not in e_str and "Judge Rejection" not in e_str:
                                if isinstance(e, json.JSONDecodeError):
                                    _cause = "⚠️ Parse Error: Retry"
                                elif "Schema collapse" in e_str or "translated_srt" in e_str:
                                    _cause = "⚠️ Schema Error: Retry"
                                elif "Sync Error" in e_str:
                                    _cause = "⚠️ Sync Error: Retry"
                                else:
                                    _cause = "⚠️ API Error: Retry"
                                self.shared_state.update_audit(last_decision=_cause)

                        if not batch_diagnostics_logged:
                            file_log(session_log_file, f"--- BATCH {batch_label} FAILURE DIAGNOSTICS (PRIMARY) ---")
                            file_log(session_log_file, f"SYSTEM PROMPT:\n{pretty_json(_batch_system_prompt)}")
                            file_log(session_log_file, f"USER PROMPT:\n{pretty_json(_batch_user_prompt)}")
                            if raw_res is not None:
                                file_log(session_log_file, f"RAW LLM RESPONSE:\n{pretty_json(raw_res)}")
                            else:
                                file_log(session_log_file, f"RAW LLM RESPONSE: None (call_llm failed)")
                            file_log(session_log_file, f"ERROR: {e}")
                            batch_diagnostics_logged = True
                        else:
                            log(self.log_queue, session_log_file, f"⚠️ Batch retry failure event for {batch_label} (Retry action follows). Reason: {e}")
                            push_eta()
                        
                        evaluate_batch_failure(state, self.log_queue, session_log_file, stats)
                        if state.min_batch_failures >= 3:
                            log(self.log_queue, session_log_file, "❌ Persistent failure at minimal batch size. Triggering intervention...")
                            stats["total_interventions"] = stats.get("total_interventions", 0) + 1
                            self.ui_queue.put(("intervention_count", stats["total_interventions"]))

                            eng_src_for_intervention = []
                            for idx in indices:
                                eng_src_for_intervention.append({
                                    "index": idx,
                                    "timestamp": next(m['timestamp'] for m in original_metadata if m['index'] == idx),
                                    "text": eng_by_index[idx]
                                })
                                
                            reason_for_human = native_audit_reason if native_audit_reason else "System Error (AI succeeded but Engine crashed)"
                            if "pipeline_velocity" in str(e):
                                reason_for_human += " [Internal Bug: 'pipeline_velocity' missing]"
                            else:
                                reason_for_human += f" [System Error: {str(e)}]"

                            if getattr(self, 'bypass_intervention', False):
                                log(self.log_queue, session_log_file, f"🚫 [BYPASS] Skipping manual intervention. Auto-cleaning {len(indices)} subtitle(s)...")

                                bypass_dict = {}
                                last_received = received_dict if 'received_dict' in locals() else {}
                                for m in eng_src_for_intervention:
                                    raw_target = str(last_received.get(m['index'], ""))
                                    cleaned = cleanup_failed_translation(raw_target, m['text'], reason_for_human, profile=profile)
                                    bypass_dict[m['index']] = cleaned
                                    log(self.log_queue, session_log_file, f"   🚫 IDX {m['index']}: {repr(raw_target)[:60]} → {repr(cleaned)[:60]}")

                                if bypass_log_file is None:
                                    bypass_log_file = self._create_bypass_log(session_log_file)
                                self._write_bypass_entry(bypass_log_file, eng_src_for_intervention, bypass_dict, reason_for_human)
                                bypass_count += 1

                                received_dict = bypass_dict
                                res_json = {
                                    "translated_srt": bypass_dict,
                                    "summary": context_state.get('summary'),
                                    "last_speaker_info": context_state.get('last_speaker_info'),
                                    "continuity_note": context_state.get('continuity_note')
                                }

                                log(self.log_queue, session_log_file, f"🚫 [BYPASS] Auto-cleanup complete for batch {batch_label}. Resuming...")

                                self._finalize_batch_success(
                                    original_metadata, received_dict, f_out,
                                    translated_target_by_index, res_json, context_state,
                                    stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
                                )

                                state.min_batch_failures = 0
                                state.failures_at_current_size = 0
                                state.batch_success = True
                                success_streak = state.success_streak
                                break

                            intervention_start_t = time.time()
                            manual_fix_dict = self._perform_manual_intervention(
                                indices, 
                                eng_src_for_intervention, 
                                received_dict if 'received_dict' in locals() else {}, 
                                reason_for_human,
                                config.get("scratch_dir", "scratch"),
                                profile=profile
                            )
                            intervention_duration = time.time() - intervention_start_t
                            session_start_time += intervention_duration
                            
                            if manual_fix_dict:
                                received_dict = manual_fix_dict
                                res_json = {
                                    "translated_srt": manual_fix_dict,
                                    "summary": context_state.get('summary'),
                                    "last_speaker_info": context_state.get('last_speaker_info'),
                                    "continuity_note": context_state.get('continuity_note')
                                }
                                
                                log(self.log_queue, session_log_file, "✅ Manual Intervention successful. Resuming automated flow...")
                                file_log(session_log_file, f"--- MANUAL INTERVENTION AUDIT (Batch {indices[0]}-{indices[-1]}) ---")
                                for m in eng_src_for_intervention:
                                    idx = m['index']
                                    file_log(session_log_file, f"IDX {idx} | EN: {m['text']}")
                                    file_log(session_log_file, f"IDX {idx} | HE (HUMAN): {manual_fix_dict.get(idx, 'MISSING')}")
                                file_log(session_log_file, "--------------------------------------------------------")
                                
                                self._finalize_batch_success(
                                    original_metadata, received_dict, f_out, 
                                    translated_target_by_index, res_json, context_state, 
                                    stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
                                )

                                state.min_batch_failures = 0
                                state.failures_at_current_size = 0
                                state.batch_success = True
                                success_streak = state.success_streak
                                break 
                            else:
                                log(self.log_queue, session_log_file, "❌ Manual Intervention cancelled or failed. Stopping.")
                                self.should_stop = True
                                break

                processed = stats.get("processed_total", processed)
                stats["total_elapsed_seconds"] = elapsed_at_session_start + (time.time() - session_start_time)
                checkpoint_data = build_checkpoint_payload(
                    config, current_index, processed, total_blocks, total_main_cost, total_judge_cost, 
                    context_state, profile, stats, output_file,
                    effective_batch_size=effective_batch_size
                )
                save_checkpoint(current_checkpoint_file, checkpoint_data)
                
                total_elapsed = stats.get("total_elapsed_seconds", 0.0)
                time_str, finish_str, eta_secs = get_eta_string(total_elapsed, processed, total_blocks)

                self.ui_queue.put(("progress", (processed, total_blocks)))
                self.ui_queue.put(("eta", (time_str, finish_str, eta_secs)))
                if self.shared_state:
                    self.shared_state.update_progress(processed, total_blocks)
                    self.shared_state.update_eta(time_str, finish_str)
                    
        if not self.should_stop:
            log(self.log_queue, session_log_file, f"\n✅ Translation Complete!")
            log(self.log_queue, session_log_file, f"📂 Output saved to: {output_file}")

            stats["total_elapsed_seconds"] = elapsed_at_session_start + (time.time() - session_start_time)
            print_stats(
                stats=stats,
                total_blocks=total_blocks,
                total_main_cost=total_main_cost,
                total_judge_cost=total_judge_cost,
                srt_file=srt_file,
                sys_file=sys_file,
                output_file=output_file,
                model_cfg=model_cfg,
                judge_cfg=config.get("judge_cfg", model_cfg),
                batch_size=batch_size,
                final_eff_batch_size=effective_batch_size,
                judge_batch_size=config.get("judge_batch_size", "?"),
                log_fn=lambda msg: log(self.log_queue, session_log_file, msg),
            )

            if cleanup_checkpoint(current_checkpoint_file):
                log(self.log_queue, session_log_file, f"🧹 Cleaned up checkpoint.")

            if bypass_count > 0:
                bypass_basename = os.path.basename(bypass_log_file) if bypass_log_file else "bypass_review.txt"
                banner_line = "⚠️  " * 14
                log(self.log_queue, session_log_file, f"\n{banner_line}")
                log(self.log_queue, session_log_file, f"  ⚠️  {bypass_count} SUBTITLE BLOCK(S) WERE AUTO-BYPASSED AND MAY CONTAIN ERRORS  ⚠️")
                log(self.log_queue, session_log_file, f"  📋 Review file: {bypass_basename}")
                log(self.log_queue, session_log_file, f"{banner_line}\n")
            
    except Exception as e:
        log(self.log_queue, config.get("session_log_file"), f"❌ Fatal Error: {e}")
    finally:
        self.ui_queue.put(("finished", (processed, total_blocks) if 'processed' in locals() and 'total_blocks' in locals() else None))
        self.ui_queue.put(("refresh", None))
