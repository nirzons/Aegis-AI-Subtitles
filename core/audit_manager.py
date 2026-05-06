import time
import json
import re
from core.text_processing import check_heuristics, force_split_overlong_line, strip_music_glyphs_batch
from core.llm_api import call_llm_judge
from utils.app_utils import log, file_log, format_cost_display
from core.translation_stats import _inc_by_size

def run_audit_pipeline(
    indices, input_payload, received_dict, config, profile, stats, 
    log_queue, ui_queue, session_log_file, shared_state, 
    previous_overlong_indices, current_batch_size, 
    ordered_srt_indices, eng_by_index, translated_target_by_index,
    calculate_costs_func, push_eta_func,
    main_system_prompt=None
):
    """
    Orchestrates the post-processing, heuristic audit, and Judge LLM validation.
    Returns: (is_valid, last_judge_error, last_judged_indices, judge_cost_delta, updated_overlong_indices)
    """
    # 1. Post-Processing & Sanitization
    ranges_str = "".join([f"\\u{s:04x}-\\u{e:04x}" for s, e in profile.target_unicode_ranges])
    re_ghost_chars = re.compile(rf'\n[a-zA-Z]{{1,2}}(?=\s|[{ranges_str}]|<|♪)')
    re_newline_cleanup = re.compile(profile.newline_regex)
    
    changes_detected, repaired_ghost_indices = _sanitize_ghost_fragments(
        received_dict, stats, session_log_file, profile, log_queue, 
        re_newline_cleanup, re_ghost_chars
    )

    # 2. Sync & Technical Validation
    for idx in indices:
        if idx not in received_dict:
            raise ValueError(f"Sync Error: Key '{idx}' missing")
    
    strip_music_glyphs_batch(received_dict)

    # 3. Heuristic Audit
    illegal_labels = config.get("illegal_labels", [])
    is_suspicious, audit_reason, native_audit_reason, skip_judge = check_heuristics(
        input_payload, received_dict, illegal_labels=illegal_labels, profile=profile
    )
    
    # Forced Escalation for Repairs
    if changes_detected:
        is_suspicious = True
        if profile.use_native_instructions:
            indices_str = ','.join(repaired_ghost_indices)
            repair_note = profile.native_repair_note_ghost.replace("{indices}", indices_str) if repaired_ghost_indices else profile.native_repair_note_newline
            native_audit_reason = f"{repair_note}; {native_audit_reason}" if native_audit_reason else repair_note
            audit_reason = f"Repaired by Sanitizer; {audit_reason}" if audit_reason else "Repaired by Sanitizer"
        else:
            repair_note = f"IDX:{','.join(repaired_ghost_indices)}|Auto-repair applied to remove source language ghost fragments. Verify the sentence flows naturally." if repaired_ghost_indices else "GLOBAL|Auto-repair applied to line format (\\n)."
            audit_reason = f"Repaired by Sanitizer; {audit_reason}" if audit_reason else "Repaired by Sanitizer"
            native_audit_reason = f"{repair_note}; {native_audit_reason}" if native_audit_reason else repair_note

    last_judge_error = ""
    last_judged_indices = set()
    judge_cost_delta = 0.0
    updated_overlong_indices = previous_overlong_indices

    if not is_suspicious:
        return True, "", set(), 0.0, updated_overlong_indices

    # 4. Escalation: Suspicious batch
    if skip_judge:
        parsed_audit_map = _parse_audit_reason(native_audit_reason)
        
        # Stubbornness Fallback (Auto-Correction)
        fixed_any = False
        if current_batch_size <= 2:
            overlong_pattern = profile.overlong_word
            overlong_in_this_attempt = {idx for idx, msg in parsed_audit_map.items() if (overlong_pattern in msg)}
            indices_to_fix = overlong_in_this_attempt.intersection(previous_overlong_indices)
            
            if indices_to_fix:
                for idx_to_fix in indices_to_fix:
                    err_msg = parsed_audit_map[idx_to_fix].strip()
                    if profile.overlong_phrase in err_msg:
                        old_text = received_dict[idx_to_fix]
                        new_text = force_split_overlong_line(old_text)
                        if new_text != old_text:
                            received_dict[idx_to_fix] = new_text
                            fixed_any = True
                            log_msg = (profile.native_stubborn_split_log if profile.use_native_instructions else "💡 Stubborn model detected. Applying programmatic split for index {idx}.").replace("{idx}", str(idx_to_fix))
                            log(log_queue, session_log_file, log_msg)
            
            updated_overlong_indices = overlong_in_this_attempt

        if fixed_any:
            is_suspicious, audit_reason, native_audit_reason, skip_judge = check_heuristics(
                input_payload, received_dict, illegal_labels=illegal_labels, profile=profile
            )
            if not is_suspicious:
                log_msg = profile.native_stubborn_resolved_log if profile.use_native_instructions else "✅ Programmatic split resolved the issue. Proceeding..."
                log(log_queue, session_log_file, log_msg)
                return True, "", set(), 0.0, updated_overlong_indices
            elif not skip_judge:
                pass
            else:
                _inc_by_size(stats["auditor_skip_judge"], current_batch_size)
                log(log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Immediate retry (skipping Judge).")
                return False, parsed_audit_map, set(indices), 0.0, updated_overlong_indices
        else:
            _inc_by_size(stats["auditor_skip_judge"], current_batch_size)
            log(log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Immediate retry (skipping Judge).")
            if shared_state:
                shared_state.update_audit(last_decision="Auditor: Failed & Retry", batch_trend=-1)
            return False, parsed_audit_map, set(indices), 0.0, updated_overlong_indices

    # 5. Escalation to Judge
    _inc_by_size(stats["auditor_sent_to_judge"], current_batch_size)
    log(log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Calling Judge...")
    if shared_state:
        shared_state.update_audit(last_decision="Auditor: Sent to Judging", batch_trend=0)
    
    ui_queue.put(("judge_start", None))
    
    judge_cfg = config["judge_cfg"]
    judge_api_key = config["judge_api_key"]
    judge_batch_size = config["judge_batch_size"]
    
    is_valid, judge_reason, j_in, j_out, j_cached, j_reasoning = call_llm_judge(
        judge_cfg, indices, input_payload, received_dict, judge_api_key,
        judge_batch_size=judge_batch_size,
        ordered_srt_indices=ordered_srt_indices,
        eng_by_index=eng_by_index,
        target_completed_by_index=translated_target_by_index,
        log_func=lambda m: log(log_queue, session_log_file, m),
        file_log_func=lambda m: file_log(session_log_file, m),
        audit_reason_native=native_audit_reason,
        progress_func=lambda c, t: ui_queue.put(("judge_progress", (c, t))),
        ui_queue=ui_queue,
        debug_mode=config.get('debug_mode', False),
        profile=profile,
        main_system_prompt=main_system_prompt
    )
    ui_queue.put(("judge_stop", None))
    push_eta_func()
    
    _inc_by_size(stats["judge_invocations"], current_batch_size)
    
    j_cost, j_hit_str, j_hit_pct, j_brain_str = calculate_costs_func(j_in, j_out, j_cached, j_reasoning, judge_cfg)
    judge_cost_delta = j_cost
    
    fmt_val = lambda v: f"${v:.5f}"
    log(log_queue, session_log_file, f"⚖️ [Judge Model] Batch: {fmt_val(j_cost)} (In: {j_in:,}{j_hit_str} / Out: {j_out:,}{j_brain_str})")
    file_log(session_log_file, f"⚖️ Judge Stats (Batch {indices[0]}-{indices[-1]}) - Tokens: In {j_in:,} / Out {j_out:,}{j_brain_str}")

    if not is_valid:
        if judge_reason == "FAILED":
            log(log_queue, session_log_file, "   ↳ ❌ Judge ruling: FAILED (judge error). Retrying with auditor feedback.")
            last_judge_error = _parse_audit_reason(native_audit_reason)
            _inc_by_size(stats["judge_failed_errors"], current_batch_size)
        else:
            last_judge_error = judge_reason
            _inc_by_size(stats["judge_rejections"], current_batch_size)
        
        if shared_state:
            shared_state.update_audit(last_decision="Judge: Failed & Retry", batch_trend=-1)
        return False, last_judge_error, set(indices), judge_cost_delta, updated_overlong_indices
    else:
        _inc_by_size(stats["judge_approvals"], current_batch_size)
        _inc_by_size(stats["judge_approved_passes_by_size"], current_batch_size)
        if shared_state:
            shared_state.update_audit(last_decision="Judge: Approved", batch_trend=1)
        
        msg = f"✅ Judge Approved: {judge_reason}" if judge_reason and judge_reason != {} else "✅ Judge Approved"
        log(log_queue, session_log_file, msg)
        return True, "", set(), judge_cost_delta, updated_overlong_indices

def _sanitize_ghost_fragments(received_dict, stats, session_log_file, profile, log_queue, re_newline_cleanup, re_ghost_chars):
    """Internal helper for post-processing cleanup."""
    changes_detected = []
    repaired_ghost_indices = []
    for idx in received_dict:
        original_val = str(received_dict[idx])
        cleaned_val = re_newline_cleanup.sub('\n', original_val)
        
        if not profile.target_uses_latin_script:
            if re_ghost_chars.search(cleaned_val):
                cleaned_val = re_ghost_chars.sub('\n', cleaned_val)
                repaired_ghost_indices.append(idx)
    
        if cleaned_val != original_val:
            changes_detected.append(idx)
            received_dict[idx] = cleaned_val

    if changes_detected:
        if repaired_ghost_indices:
            log(log_queue, session_log_file, f"🧹 [Sanitizer] Removed English ghost fragments in indices: {', '.join(repaired_ghost_indices)}")
        log(log_queue, session_log_file, f"🧹 [Sanitizer] Fixed escaped line breaks or formatting in indices: {', '.join(changes_detected)}")
        stats["sanitizer_fixes"] += 1
            
    return changes_detected, repaired_ghost_indices

def _parse_audit_reason(reason_str):
    parsed_map = {}
    if not reason_str:
        return parsed_map
    for p in reason_str.split("; "):
        if "|" in p:
            scope, msg = p.split("|", 1)
            if scope.startswith("IDX:"):
                idx_list = scope[4:].split(",")
                for idx_val in idx_list:
                    parsed_map[idx_val] = parsed_map.get(idx_val, "") + msg + " "
            else:
                parsed_map["GLOBAL"] = parsed_map.get("GLOBAL", "") + msg + " "
        else:
            if p.strip():
                parsed_map["GENERAL"] = parsed_map.get("GENERAL", "") + p + " "
    return {k: v.strip() for k, v in parsed_map.items()}
