import os
import time
import datetime
import json
import re
import threading
from constants import GLOBAL_SYSTEM_INSTRUCTIONS, GLOBAL_TECHNICAL_RULES, JSON_SCHEMA_TEMPLATE
from text_processing import fix_rtl, pre_repair_json, check_heuristics, strip_music_glyphs_batch
from llm_api import call_llm, call_llm_judge
from app_utils import log, file_log, format_cost_display, get_eta_string, strip_srt, load_srt_index_to_text

from translation_stats import _inc_by_size, make_stats, print_stats


class TranslationEngine:
    def __init__(self, log_queue, ui_queue):
        self.log_queue = log_queue
        self.ui_queue = ui_queue
        self.should_stop = False
        self.current_output_file = None

    def request_stop(self):
        self.should_stop = True

    def run_translation(self, config):
        try:
            resume_mode = config["resume_mode"]
            model_cfg = config["model_cfg"]
            api_key = config["api_key"]
            batch_size = config["batch_size"]  # UI / configured default; may differ from effective_batch_size while running
            session_log_file = config["session_log_file"]
            
            # Paths
            checkpoint_dir = config["checkpoint_dir"]
            sysprm_dir = config["sysprm_dir"]
            english_subs_dir = config["english_subs_dir"]
            output_dir = config["output_dir"]

            if resume_mode:
                checkpoint_data = config["checkpoint_data"]
                
                # Ensure we have full absolute paths even if checkpoint only has basenames
                sys_file_raw = checkpoint_data['sys_file']
                srt_file_raw = checkpoint_data['srt_file']
                sys_file = sys_file_raw if os.path.isabs(sys_file_raw) else os.path.join(sysprm_dir, sys_file_raw)
                srt_file = srt_file_raw if os.path.isabs(srt_file_raw) else os.path.join(english_subs_dir, srt_file_raw)

                output_file = checkpoint_data['output_file']
                current_index = checkpoint_data['current_index']
                processed = checkpoint_data.get('processed', 0)
                total_main_cost = checkpoint_data.get('total_main_cost', checkpoint_data.get('total_cost', 0.0))
                total_judge_cost = checkpoint_data.get('total_judge_cost', 0.0)
                context_state = checkpoint_data['context_state']
                current_checkpoint_file = config["checkpoint_file_path"] # The actual path to the .json file
                
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

                max_num = 0
                while True:
                    max_num += 1
                    current_checkpoint_file = os.path.join(checkpoint_dir, f"translator_checkpoint_{max_num}.json")
                    if not os.path.exists(current_checkpoint_file):
                        try:
                            with open(current_checkpoint_file, 'w', encoding='utf-8') as f:
                                json.dump({"pid": os.getpid(), "processed": 0, "status": "initializing"}, f)
                            break
                        except Exception:
                            continue

                base_name = os.path.basename(srt_file)
                output_file = os.path.join(output_dir, base_name.replace('.srt', f'_{model_cfg["name"]}_heb.srt'))
                self.current_output_file = output_file
                current_index = 0
                processed = 0
                total_main_cost = 0.0
                total_judge_cost = 0.0
                log(self.log_queue, session_log_file, f"\n📁 Creating new Checkpoint File: {current_checkpoint_file}")

            with open(sys_file, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            clean_lines = [line for line in lines if not line.strip().startswith("//")]
            raw_sysprm = "".join(clean_lines).strip()
            parts = [p.strip() for p in raw_sysprm.split("===")]    
            
            if len(parts) >= 2:
                initial_context_str = parts[0]
                series_context = parts[1]
                if not resume_mode: log(self.log_queue, session_log_file, "✅ Loaded project-specific context from sysprm.")
            else:
                initial_context_str = "{}"
                series_context = parts[0]
                
            system_prompt = f"""
{GLOBAL_SYSTEM_INSTRUCTIONS}

{series_context}

{GLOBAL_TECHNICAL_RULES}
"""
                
            if not resume_mode:
                try:
                    context_state = json.loads(initial_context_str) if initial_context_str != "{}" else {}
                    if not context_state:
                         context_state = {
                            "last_two_lines_heb": [], "last_speaker_info": "לא ידוע", 
                            "speakers_gender": {}, "current_setting": "לא ידוע", "summary": "הפרק רק התחיל."
                         }
                except json.JSONDecodeError:
                    log(self.log_queue, session_log_file, "⚠️ Warning: Could not parse initial JSON. Falling back to default.")
                    context_state = {
                        "last_two_lines_heb": [], "last_speaker_info": "לא ידוע", 
                        "speakers_gender": {}, "current_setting": "לא ידוע", "summary": "הפרק רק התחיל."
                    }

            with open(srt_file, 'r', encoding='utf-8-sig') as f:
                srt_content = f.read()

            srt_content = srt_content.replace('\r\n', '\n')
            blocks = srt_content.strip().split('\n\n')
            total_blocks = len(blocks)

            eng_by_index = {}
            ordered_srt_indices = []
            for b in blocks:
                lines_b = b.split('\n')
                if len(lines_b) >= 2:
                    idx_b = lines_b[0].strip()
                    text_b = "\n".join([l.strip() for l in lines_b[2:]]).strip()
                    eng_by_index[idx_b] = text_b
                    ordered_srt_indices.append(idx_b)

            if resume_mode:
                translated_heb_by_index = load_srt_index_to_text(output_file)
            else:
                translated_heb_by_index = {}

            if resume_mode:
                ckpt_batch_original = int(checkpoint_data.get("batch_size", batch_size))
                if batch_size != ckpt_batch_original:
                    # Manual override detected in UI
                    effective_batch_size = batch_size
                    override_msg = f" (Manual override: reset to {batch_size})"
                else:
                    effective_batch_size = int(checkpoint_data.get("effective_batch_size", batch_size))
                    override_msg = ""
            else:
                effective_batch_size = batch_size
                override_msg = ""
            
            effective_batch_size = max(2, effective_batch_size)

            # ── Stats initialization ──────────────────────────────────────
            if resume_mode:
                stats = make_stats(resume_from=checkpoint_data.get("stats"))
            else:
                stats = make_stats()

            # Capture elapsed time accumulated in previous sessions
            elapsed_at_session_start = stats["total_elapsed_seconds"]
            session_start_time = time.time()
            # ─────────────────────────────────────────────────────────────

            start_time = time.time()
            session_processed = 0
            success_streak = 0

            log(self.log_queue, session_log_file, f"\n🚀 Starting Protected AI Translation with {model_cfg['name']}")
            
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

            file_mode = 'a' if resume_mode else 'w'
            with open(output_file, file_mode, encoding='utf-8') as f_out:
                
                while current_index < total_blocks and not self.should_stop:
                    current_batch_size = effective_batch_size
                    batch_success = False
                    min_batch_failures = 0  # at size 2, allow up to 3 attempts before total failure
                    attempted_strides = []  # strides tried this chunk; on success after retries, effective = one-before-last
                    failures_at_current_stride = 0  # need 2 failures at same stride before shrinking (avoids one-off glitches)

                    last_judge_error = ""      # הטקסט של השגיאה
                    last_judged_indices = set() # האינדקסים שהיו בתוך ה-Chunk שנפסל
                    while not batch_success and not self.should_stop:
                        batch_diagnostics_logged = False
                        this_attempt_auditor_flagged = False  # reset each attempt
                        attempted_strides.append(current_batch_size)
                        start_idx = current_index
                        end_idx = min(current_index + current_batch_size, total_blocks)
                        expected_count = end_idx - start_idx
                        
                        prev_context_blocks = []
                        if start_idx >= 2: prev_context_blocks = blocks[start_idx - 2 : start_idx]
                        elif start_idx == 1: prev_context_blocks = [blocks[0]]
                            
                        next_context_blocks = []
                        if end_idx <= total_blocks - 2: next_context_blocks = blocks[end_idx : end_idx + 2]
                        elif end_idx == total_blocks - 1: next_context_blocks = [blocks[total_blocks - 1]]

                        chunk = blocks[start_idx:end_idx]
                        
                        original_metadata = []
                        for b in chunk:
                            lines_b = b.split('\n')
                            if len(lines_b) >= 2:
                                idx_b = lines_b[0].strip()
                                time_b = lines_b[1].strip()
                                text_b = "\n".join([l.strip() for l in lines_b[2:]]).strip()
                                original_metadata.append({
                                    "index": idx_b,
                                    "timestamp": time_b,
                                    "text": text_b
                                })
                        
                        text_chunk_parts = []
                        if prev_context_blocks: 
                            text_chunk_parts.append(f"### [הקשר קודם - לא לתרגום] ###\n{strip_srt(prev_context_blocks)}\n")
                        
                        input_payload = { m['index']: m['text'] for m in original_metadata }
                        for idx, txt in input_payload.items():
                            # If line is only SDH tags + punctuation, force empty string
                            if re.fullmatch(r"[-.\s]*[\[(].*?[\])][-.\s]*", txt):
                                input_payload[idx] = "" 

                        text_chunk_parts.append(f"### [בלוקים לתרגום - JSON] ###\n{json.dumps(input_payload, ensure_ascii=False, indent=2)}\n")
                        
                        if next_context_blocks: 
                            text_chunk_parts.append(f"### [הקשר הבא - לא לתרגום] ###\n{strip_srt(next_context_blocks)}\n")
                        
                        text_chunk = '\n'.join(text_chunk_parts)
                        indices = [d['index'] for d in original_metadata]
                        
                        summary_text = context_state.get('summary', 'הפרק רק התחיל.')
                        last_speaker = context_state.get('last_speaker_info') or context_state.get('last_speaker', 'לא ידוע')
                        setting = context_state.get('current_setting', 'לא ידוע')
                        
                        last_lines = context_state.get('last_two_lines_heb', [])
                        last_line_str = f"שורה מתורגמת אחרונה (מהבאץ' הקודם): '{last_lines[-1]}'" if last_lines else ""
                        
                        continuity_note = context_state.get('continuity_note', '')
                        continuity_str = f"⚠️ הערת רציפות מהבאץ' הקודם (שים לב!): {continuity_note}" if continuity_note and continuity_note.strip() else ""

                        context_section_lines = [
                            "### הסיפור עד כה (הקשר קודם) ###",
                            f"מיקום נוכחי: {setting}",
                            f"תקציר האירועים: {summary_text}",
                            f"הדובר האחרון בבאץ' הקודם: {last_speaker}"
                        ]
                        if last_line_str: context_section_lines.append(last_line_str)
                        if continuity_str: context_section_lines.append(continuity_str)
                            
                        context_section = '\n'.join(context_section_lines)

                        user_prompt = f"""
אתה מתרגם עכשיו את הבאץ' הבא. זכור: הפלט חייב להיות בעברית בלבד.

{context_section}

{text_chunk}

### חוקים טכניים חובה ###
1. ספירה מדויקת: **חובה עליך להחזיר בדיוק {expected_count} מפתחות באובייקט 'translated_srt'.**
2. אינדקסים מדויקים: השתמש בדיוק באינדקסים הבאים כמפתחות: {', '.join(indices)}.
3. **אל תתרגם ואל תכלול בפלט** אף מילה המופיעה בבלוקי ה"הקשר" (הן בשדה ה-draft והן בתרגום הסופי).

{JSON_SCHEMA_TEMPLATE}
"""
                        feedback_injection = ""
                        # אם יש שגיאה מהשופט, ויש לפחות אינדקס אחד משותף בין הבאץ' הנוכחי לבאץ' שנפסל
                        if last_judge_error and set(indices).intersection(last_judged_indices):
                            feedback_injection = "\n### חובה לתקן את השגיאות הבאות לפי אינדקס (אל תחזור על טעויות אלו): ###\n"
                            if isinstance(last_judge_error, dict):
                                for err_idx, err_msg in last_judge_error.items():
                                    if err_idx in ["GLOBAL", "GENERAL", "general"] or str(err_idx).startswith("chunk_") or err_idx in indices or str(err_idx) in [str(i) for i in indices]:
                                        prefix = f"אינדקס {err_idx}: " if err_idx not in ["GLOBAL", "GENERAL", "general"] and not str(err_idx).startswith("chunk_") else ""
                                        feedback_injection += f"{prefix}{err_msg}\n"
                            else:
                                feedback_injection += f"{last_judge_error}\n"
                            feedback_injection += "----------------------------------------\n"
                        final_prompt = user_prompt + feedback_injection

                        raw_res = None
                        _batch_system_prompt = system_prompt
                        _batch_user_prompt = final_prompt
                        try:
                            log(self.log_queue, session_log_file, f"⏳ Sending Batch (Indices: {indices[0]}-{indices[-1]} | cues: {expected_count}, stride: {current_batch_size})...")
                            is_retry = (len(attempted_strides) > 1)
                            self.ui_queue.put(("timer_start", (expected_count, is_retry)))

                            # ── Track attempt ──────────────────────────────
                            stats["total_batches_attempted"] += 1
                            if is_retry:
                                stats["total_retries"] += 1
                            batch_call_start = time.time()
                            # ──────────────────────────────────────────────

                            raw_res, in_tokens, out_tokens, cached_tokens, reasoning_tokens = call_llm(model_cfg, system_prompt, final_prompt, api_key)

                            # ── Record LLM call duration ───────────────────
                            _call_duration = time.time() - batch_call_start
                            if is_retry:
                                stats["llm_call_times_retry"].append((_call_duration, current_batch_size))
                            else:
                                stats["llm_call_times_new"].append((_call_duration, current_batch_size))
                            # ──────────────────────────────────────────────

                            self.ui_queue.put(("timer_stop", None))
                            
                            # MAIN MODEL Cost Calculation
                            discount = model_cfg.get('cache_discount', 0.0)
                            
                            if discount > 0 and in_tokens > 0:
                                miss_tokens = in_tokens - cached_tokens
                                # Calculate discounted price based on the percentage provided in settings
                                cache_hit_price = model_cfg['input_price'] * (1 - (discount / 100.0))
                                batch_cost = (miss_tokens / 1e6 * model_cfg['input_price']) + (cached_tokens / 1e6 * cache_hit_price) + (out_tokens / 1e6 * model_cfg['output_price'])
                                hit_pct = (cached_tokens/in_tokens*100)
                                hit_str = f" [Hit: {cached_tokens:,} ({hit_pct:.1f}%)]"
                            else:
                                batch_cost = (in_tokens / 1e6 * model_cfg['input_price']) + (out_tokens / 1e6 * model_cfg['output_price'])
                                hit_str = ""
                            
                            brain_load = (reasoning_tokens / out_tokens * 100) if out_tokens > 0 else 0
                            brain_str = f" | 🧠 Brain: {reasoning_tokens:,} ({brain_load:.1f}%)" if reasoning_tokens > 0 else ""

                            total_main_cost += batch_cost
                            
                            # Immediate GUI update
                            self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                            
                            # Immediate Terminal logging
                            def fmt_val(v): return f"{int(v):,}" if v > 100 else f"${v:.5f}"
                            log(self.log_queue, session_log_file, f"💰 [Main Model] Batch: {fmt_val(batch_cost)} (In: {in_tokens:,}{hit_str} / Out: {out_tokens:,}{brain_str}) | Total Main: {fmt_val(total_main_cost)}")

                            cleaned_res = pre_repair_json(raw_res)
                            try:
                                res_json = json.loads(cleaned_res)
                            except json.JSONDecodeError:
                                _inc_by_size(stats["json_parse_errors"], current_batch_size)
                                raise

                            # Schema Recovery Layer: Handle GPT-5 key hallucinations
                            recovered = False
                            if 'translated_srt' not in res_json:
                                possible_keys = ["translation", "translations", "translated", "result", "output", "data"]
                                for pk in possible_keys:
                                    if pk in res_json and isinstance(res_json[pk], dict):
                                        res_json['translated_srt'] = res_json[pk]
                                        recovered = True
                                        log(self.log_queue, session_log_file, f"   ↳ 💡 Recovered schema from hallucinated key: '{pk}'")
                                        break
                                
                                if not recovered:
                                    # Search for any dictionary that contains numeric keys
                                    for key, value in res_json.items():
                                        if isinstance(value, dict) and any(str(k).isdigit() for k in value.keys()):
                                            res_json['translated_srt'] = value
                                            recovered = True
                                            log(self.log_queue, session_log_file, f"   ↳ 💡 Recovered schema from inferred dictionary: '{key}'")
                                            break
                                
                                if not recovered:
                                    # Last ditch: Check if the ROOT object itself has numeric keys
                                    if any(str(k).isdigit() for k in res_json.keys()):
                                        # To avoid losing the original structure if needed, wrap it
                                        res_json = {'translated_srt': res_json}
                                        recovered = True
                                        log(self.log_queue, session_log_file, "   ↳ 💡 Recovered schema from root-level flat dictionary")

                                if recovered:
                                    stats["schema_recoveries"] += 1  # track successful recovery

                            if 'translated_srt' not in res_json or not isinstance(res_json['translated_srt'], dict):
                                raise ValueError(f"Schema collapse: 'translated_srt' missing. Found: {list(res_json.keys())}")

                            received_dict = res_json['translated_srt']

                            changes_detected = []
                            for idx in received_dict:
                                original_val = str(received_dict[idx])
                                # 1. מבצעים את התיקון ושומרים למשתנה זמני
                                cleaned_val = re.sub(r'\s*\\+[nננ]\s*', '\n', original_val)
                            
                                # 2. בודקים אם היה שינוי
                                if cleaned_val != original_val:
                                    changes_detected.append(idx)
                                    # 3. מעדכנים את המילון בערך הנקי
                                    received_dict[idx] = cleaned_val

                            # הדפסת לוג רק אם היו תיקונים
                            if changes_detected:
                                log(self.log_queue, session_log_file, f"🧹 [Sanitizer] Fixed escaped line breaks in indices: {', '.join(changes_detected)}")
                                stats["sanitizer_fixes"] += 1

                            for idx in indices:
                                if idx not in received_dict:
                                    raise ValueError(f"Sync Error: Key '{idx}' missing")

                            strip_music_glyphs_batch(received_dict)

                            illegal_labels = context_state.get("illegal_labels", [])
                            is_suspicious, audit_reason, heb_audit_reason, skip_judge = check_heuristics(input_payload, received_dict, illegal_labels=illegal_labels)
                            
                            if is_suspicious:
                                this_attempt_auditor_flagged = True  # mark for clean-pass tracking

                                if not batch_diagnostics_logged:
                                    file_log(session_log_file, f"--- BATCH {indices[0] if indices else '?'}-{indices[-1] if indices else '?'} DIAGNOSTICS (PRIMARY) ---")
                                    file_log(session_log_file, f"SYSTEM PROMPT:\n{_batch_system_prompt}")
                                    file_log(session_log_file, f"USER PROMPT:\n{_batch_user_prompt}")
                                    file_log(session_log_file, f"RAW LLM RESPONSE:\n{raw_res}\n--------------------------------------")
                                    batch_diagnostics_logged = True

                                if skip_judge:
                                    # אם יש לנו הערה בעברית מהאודיטור, נשתמש בה. 
                                    # אם היא ריקה (כי שלחנו לשופט), נשתמש רק בתוצאה של השופט בהמשך.
                                    parsed_audit_map = {}
                                    for p in heb_audit_reason.split("; "):
                                        if "|" in p:
                                            scope, msg = p.split("|", 1)
                                            if scope.startswith("IDX:"):
                                                idx_list = scope[4:].split(",")
                                                for idx_val in idx_list:
                                                    parsed_audit_map[idx_val] = parsed_audit_map.get(idx_val, "") + msg + " "
                                            else:
                                                parsed_audit_map["GLOBAL"] = parsed_audit_map.get("GLOBAL", "") + msg + " "
                                        else:
                                            if p.strip():
                                                parsed_audit_map["GENERAL"] = parsed_audit_map.get("GENERAL", "") + p + " "
                                    
                                    # Cleanup extra spaces
                                    parsed_audit_map = {k: v.strip() for k, v in parsed_audit_map.items()}
                                    last_judge_error = parsed_audit_map
                                    last_judged_indices = set(indices)
                                    _inc_by_size(stats["auditor_skip_judge"], current_batch_size)
                                    log(self.log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Immediate retry (skipping Judge).")
                                    raise ValueError(f"Heuristic Rejection (skip judge): {audit_reason}")

                                _inc_by_size(stats["auditor_sent_to_judge"], current_batch_size)
                                log(self.log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Calling Judge...")
                                self.ui_queue.put(("judge_start", None))
                                
                                judge_cfg = config["judge_cfg"]
                                judge_api_key = config["judge_api_key"]
                                judge_batch_size = config["judge_batch_size"]
                                
                                is_valid, judge_reason, j_in, j_out, j_cached, j_reasoning = call_llm_judge(
                                    judge_cfg, indices, input_payload, received_dict, judge_api_key,
                                    judge_batch_size=judge_batch_size,
                                    ordered_srt_indices=ordered_srt_indices,
                                    eng_by_index=eng_by_index,
                                    heb_completed_by_index=translated_heb_by_index,
                                    log_func=lambda m: log(self.log_queue, session_log_file, m),
                                    file_log_func=lambda m: file_log(session_log_file, m),
                                    audit_reason_heb=heb_audit_reason,
                                    progress_func=lambda c, t: self.ui_queue.put(("judge_progress", (c, t)))
                                )
                                self.ui_queue.put(("judge_stop", None))

                                # ── Track judge activity ───────────────────
                                _inc_by_size(stats["judge_invocations"], current_batch_size)
                                # ──────────────────────────────────────────
                                
                                # JUDGE Cost Calculation
                                j_discount = judge_cfg.get('cache_discount', 0.0)
                                if j_discount > 0 and j_in > 0:
                                    j_miss = j_in - j_cached
                                    j_hit_price = judge_cfg['input_price'] * (1 - (j_discount / 100.0))
                                    j_cost = (j_miss / 1e6 * judge_cfg['input_price']) + (j_cached / 1e6 * j_hit_price) + (j_out / 1e6 * judge_cfg['output_price'])
                                    j_hit_pct = (j_cached / j_in * 100)
                                    j_hit_str = f" [Hit: {j_cached:,} ({j_hit_pct:.1f}%)]"
                                else:
                                    j_cost = (j_in / 1e6 * judge_cfg['input_price']) + (j_out / 1e6 * judge_cfg['output_price'])
                                    j_hit_str = ""
                                
                                j_brain_load = (j_reasoning / j_out * 100) if j_out > 0 else 0
                                j_brain_str = f" | 🧠 Brain: {j_reasoning:,} ({j_brain_load:.1f}%)" if j_reasoning > 0 else ""

                                total_judge_cost += j_cost
                                
                                # Immediate GUI update
                                self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                                
                                # Immediate Terminal logging
                                log(self.log_queue, session_log_file, f"⚖️ [Judge Model] Batch: {fmt_val(j_cost)} (In: {j_in:,}{j_hit_str} / Out: {j_out:,}{j_brain_str}) | Total Judge: {fmt_val(total_judge_cost)}")
                                file_log(session_log_file, f"⚖️ Judge Stats (Batch {indices[0]}-{indices[-1]}) - Tokens: In {j_in:,} / Out {j_out:,}{j_brain_str} | Total Judge Cost: ${total_judge_cost:.5f}")

                                if not is_valid:
                                    if judge_reason == "FAILED":
                                        # Judge itself errored — declare ruling as FAILED and use auditor output as retry feedback
                                        log(self.log_queue, session_log_file, "   ↳ ❌ Judge ruling: FAILED (judge error). Retrying with auditor feedback.")
                                        parsed_audit_map = {}
                                        for p in heb_audit_reason.split("; "):
                                            if "|" in p:
                                                scope, msg = p.split("|", 1)
                                                if scope.startswith("IDX:"):
                                                    idx_list = scope[4:].split(",")
                                                    for idx_val in idx_list:
                                                        parsed_audit_map[idx_val] = parsed_audit_map.get(idx_val, "") + msg + " "
                                                else:
                                                    parsed_audit_map["GLOBAL"] = parsed_audit_map.get("GLOBAL", "") + msg + " "
                                            else:
                                                if p.strip():
                                                    parsed_audit_map["GENERAL"] = parsed_audit_map.get("GENERAL", "") + p + " "
                                        parsed_audit_map = {k: v.strip() for k, v in parsed_audit_map.items()}
                                        last_judge_error = parsed_audit_map
                                        _inc_by_size(stats["judge_failed_errors"], current_batch_size)
                                    else:
                                        # Normal judge rejection — use judge's error map as feedback
                                        last_judge_error = judge_reason
                                        _inc_by_size(stats["judge_rejections"], current_batch_size)
                                    last_judged_indices = set(indices)
                                    raise ValueError("Judge Rejection")
                                else:
                                    last_judge_error = ""
                                    last_judged_indices = set()
                                    _inc_by_size(stats["judge_approvals"], current_batch_size)
                                    _inc_by_size(stats["judge_approved_passes_by_size"], current_batch_size)
                                    msg = f"✅ Judge Approved: {judge_reason}" if judge_reason and judge_reason != {} else "✅ Judge Approved"
                                    log(self.log_queue, session_log_file, msg)

                            translated_lines = []
                            for m in original_metadata:
                                idx = m['index']
                                heb_text = received_dict[idx]
                                translated_lines.append(f"{idx}\n{m['timestamp']}\n{fix_rtl(heb_text)}")
                            
                            f_out.write('\n\n'.join(translated_lines) + '\n\n')
                            f_out.flush()

                            for m in original_metadata:
                                translated_heb_by_index[m['index']] = fix_rtl(received_dict[m['index']])
                            
                            context_state = res_json.get('context_state', context_state)
                            if indices:
                                last_idx = indices[-1]
                                context_state['last_two_lines_heb'] = [received_dict[last_idx]]

                            processed += expected_count 
                            session_processed += expected_count
                            batch_success = True

                            # ── Batch success tracking ─────────────────────
                            stats["total_batches_succeeded"] += 1
                            if len(attempted_strides) == 1 and not this_attempt_auditor_flagged:
                                _inc_by_size(stats["clean_passes_by_size"], current_batch_size)
                            # ──────────────────────────────────────────────

                            self.ui_queue.put(("batch_success", None))
                            
                            log(self.log_queue, session_log_file, f"✅ Batch {indices[0]}-{indices[-1]} saved successfully.")
                            last_judge_error = ""
                            last_judged_indices = set()

                        except Exception as e:
                            success_streak = 0
                            batch_label = f"{indices[0] if indices else '?'}-{indices[-1] if indices else '?'}"
                            
                            # Log error TO TERMINAL ONLY (to prevent cascading in file log)
                            self.log_queue.put(f"⚠️ Batch Failure: {e}")
                            
                            if not batch_diagnostics_logged:
                                file_log(session_log_file, f"--- BATCH {batch_label} FAILURE DIAGNOSTICS (PRIMARY) ---")
                                file_log(session_log_file, f"SYSTEM PROMPT:\n{_batch_system_prompt}")
                                file_log(session_log_file, f"USER PROMPT:\n{_batch_user_prompt}")
                                if raw_res is not None:
                                    file_log(session_log_file, f"RAW LLM RESPONSE:\n{raw_res}")
                                else:
                                    file_log(session_log_file, f"RAW LLM RESPONSE: None (call_llm failed)")
                                file_log(session_log_file, f"ERROR: {e}")
                                batch_diagnostics_logged = True
                            else:
                                file_log(session_log_file, f"⚠️ Batch retry failure event for {batch_label} (Retry action follows).")
                            
                            if current_batch_size <= 2:
                                min_batch_failures += 1
                                if min_batch_failures >= 3:
                                    log(self.log_queue, session_log_file, "❌ Failed minimal batch size (2) after 3 attempts. Stopping.")
                                    self.should_stop = True
                                    break
                                log(self.log_queue, session_log_file, f"🔁 Minimal batch (size 2) attempt {min_batch_failures}/3 failed; retrying same size...")
                            else:
                                failures_at_current_stride += 1
                                if failures_at_current_stride < 2:
                                    log(self.log_queue, session_log_file, f"🔁 Same stride ({current_batch_size}): first failure—retrying without reducing (guards against accidental glitches).")
                                else:
                                    failures_at_current_stride = 0
                                    reduce_by = max(3, current_batch_size // 6)
                                    current_batch_size = max(2, current_batch_size - reduce_by)
                                    stats["batch_shrink_events"] += 1
                                    log(self.log_queue, session_log_file, f"📉 Second failure at this stride; reducing by {reduce_by} → {current_batch_size} and retrying...")

                    if batch_success:
                        prev_effective = effective_batch_size
                        # If we succeeded on the FIRST attempt, increment streak
                        if len(attempted_strides) == 1:
                            success_streak += 1
                        else:
                            success_streak = 0 # Reset if it took retries                        
                        
                        # Check for Climb-Up Trigger
                        if success_streak >= 3 and effective_batch_size < batch_size:
                            # Calculate half-distance climb (min 5 units to ensure progress)
                            #climb_amount = max(5, (batch_size - effective_batch_size) // 2)
                            climb_amount = 8
                            effective_batch_size = min(batch_size, effective_batch_size + climb_amount)
                            stats["batch_grow_events"] += 1
                            log(self.log_queue, session_log_file, f"📈 Success streak {success_streak}: Climbing up → {effective_batch_size}")
                            success_streak = 0 # Reset streak to stabilize at new size
                        elif len(attempted_strides) >= 2:
                            # e.g. strides 60→50→42 succeeded at 42 → next chunk uses 50 (penultimate attempt)
                            effective_batch_size = attempted_strides[-2]
                        else:
                            effective_batch_size = current_batch_size
                        if effective_batch_size != prev_effective:
                            log(self.log_queue, session_log_file, f"📌 Effective batch size → {effective_batch_size} (penultimate stride after retries; following chunks start here)")
                        current_index += expected_count

                        # ── Update accumulated elapsed time & write checkpoint ─
                        stats["total_elapsed_seconds"] = elapsed_at_session_start + (time.time() - session_start_time)
                        checkpoint_data = {
                            "pid": os.getpid(),
                            "model_choice": config["model_choice"],
                            "judge_model_choice": config["judge_model_choice"],
                            "batch_size": batch_size,
                            "effective_batch_size": effective_batch_size,
                            "judge_batch_size": config["judge_batch_size"],
                            "sys_file": config["sys_name"],
                            "srt_file": config["srt_name"],
                            "output_file": output_file,
                            "current_index": current_index,
                            "processed": processed,
                            "total_blocks": total_blocks,
                            "total_main_cost": total_main_cost,
                            "total_judge_cost": total_judge_cost,
                            "context_state": context_state,
                            "stats": stats,
                        }
                        with open(current_checkpoint_file, 'w', encoding='utf-8') as ckpt_f:
                            json.dump(checkpoint_data, ckpt_f, ensure_ascii=False, indent=4)
                    
                    elapsed = time.time() - start_time
                    time_str, finish_str = get_eta_string(elapsed, session_processed, processed, total_blocks)

                    self.ui_queue.put(("progress", (processed, total_blocks)))
                    self.ui_queue.put(("eta", (time_str, finish_str)))
                        
            if not self.should_stop:
                log(self.log_queue, session_log_file, f"\n✅ Translation Complete!")
                log(self.log_queue, session_log_file, f"📂 Output saved to: {output_file}")

                # ── Finalize elapsed and print stats ──────────────────────
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
                # ─────────────────────────────────────────────────────────

                if current_checkpoint_file and os.path.exists(current_checkpoint_file):
                    os.remove(current_checkpoint_file)
                    log(self.log_queue, session_log_file, f"🧹 Cleaned up checkpoint.")
                
        except Exception as e:
            log(self.log_queue, config.get("session_log_file"), f"❌ Fatal Error: {e}")
        finally:
            self.ui_queue.put(("finished", None))
            self.ui_queue.put(("refresh", None))
