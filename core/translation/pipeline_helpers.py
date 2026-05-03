import json
import importlib
from utils.app_utils import log
from utils.srt_manager import load_srt_index_to_text, load_srt_full_history, extract_chunk_metadata, strip_srt
from core.constants import (
    get_json_schema, get_user_prompt_prefix, get_special_instructions_header,
    get_technical_rules_header, get_exact_count_rule,
    get_exact_indices_rule, get_do_not_translate_rule, get_tag_rule
)

def backfill_history(resume_mode, output_file, srt_content, ordered_srt_indices, current_index, eng_by_index, ui_queue, log_queue, session_log_file):
    translated_target_by_index = {}
    if resume_mode:
        translated_target_by_index = load_srt_index_to_text(output_file)
        try:
            full_target_history = load_srt_full_history(output_file)
            if srt_content and ordered_srt_indices:
                processed_indices = []
                for idx_o in ordered_srt_indices[:current_index]:
                    if idx_o in translated_target_by_index:
                        processed_indices.append(idx_o)
                
                last_50_indices = processed_indices[-50:]
                for idx_h in last_50_indices:
                    h_data = full_target_history.get(idx_h)
                    if h_data:
                        e_text = eng_by_index.get(idx_h, "")
                        ui_queue.put(("segment", (idx_h, h_data["time"], e_text, h_data["text"])))
        except Exception as e:
            log(log_queue, session_log_file, f"⚠️ Warning: History back-fill failed: {e}")
    else:
        translated_target_by_index = {}
    return translated_target_by_index

def determine_effective_batch_size(resume_mode, checkpoint_data, batch_size):
    if resume_mode:
        ckpt_batch_original = int(checkpoint_data.get("batch_size", batch_size))
        if batch_size != ckpt_batch_original:
            effective_batch_size = batch_size
            override_msg = f" (Manual override: reset to {batch_size})"
        else:
            effective_batch_size = int(checkpoint_data.get("effective_batch_size", batch_size))
            override_msg = ""
    else:
        effective_batch_size = batch_size
        override_msg = ""
    
    effective_batch_size = max(2, effective_batch_size)
    return effective_batch_size, override_msg

def evaluate_batch_success(state, batch_size, log_queue, session_log_file, stats):
    prev_effective = state.effective_batch_size
    if len(state.attempted_batch_sizes) == 1:
        state.success_streak += 1
    else:
        state.success_streak = 0
    
    if state.success_streak >= 3 and state.effective_batch_size < batch_size:
        climb_amount = max(2, min(8, batch_size // 4))
        state.effective_batch_size = min(batch_size, state.effective_batch_size + climb_amount)
        stats["batch_grow_events"] += 1
        log(log_queue, session_log_file, f"📈 Success streak {state.success_streak}: Climbing up → {state.effective_batch_size}")
        state.success_streak = 0
    elif len(state.attempted_batch_sizes) >= 2:
        state.effective_batch_size = state.attempted_batch_sizes[-2]
    else:
        state.effective_batch_size = state.current_batch_size

    if state.effective_batch_size != prev_effective:
        log(log_queue, session_log_file, f"📌 Effective batch size → {state.effective_batch_size} (penultimate size after retries; following chunks start here)")
    state.batch_success = True

def evaluate_batch_failure(state, log_queue, session_log_file, stats):
    state.success_streak = 0
    if state.current_batch_size <= 2:
        state.min_batch_failures += 1
        if state.min_batch_failures < 3:
            log(log_queue, session_log_file, f"🔁 Minimal batch (size 2) attempt {state.min_batch_failures}/3 failed; retrying same size...")
    else:
        state.failures_at_current_size += 1
        if state.failures_at_current_size < 2:
            log(log_queue, session_log_file, f"🔁 Same size ({state.current_batch_size}): first failure—retrying without reducing (guards against accidental glitches).")
        else:
            state.failures_at_current_size = 0
            reduce_by = max(3, state.current_batch_size // 6)
            state.current_batch_size = max(2, state.current_batch_size - reduce_by)
            stats["batch_shrink_events"] += 1
            log(log_queue, session_log_file, f"📉 Second failure at this size; reducing by {reduce_by} → {state.current_batch_size} and retrying...")

def prepare_batch_prompt(
    start_idx, end_idx, total_blocks, blocks, profile, 
    context_state, model_cfg, use_scratchpad, 
    last_judge_error, last_judged_indices, debug_mode, 
    illegal_labels, log_queue, session_log_file, RE_SDH_PUNCT
):
    expected_count = end_idx - start_idx
    
    prev_context_blocks = []
    if start_idx >= 2: prev_context_blocks = blocks[start_idx - 2 : start_idx]
    elif start_idx == 1: prev_context_blocks = [blocks[0]]
        
    next_context_blocks = []
    if end_idx <= total_blocks - 2: next_context_blocks = blocks[end_idx : end_idx + 2]
    elif end_idx == total_blocks - 1: next_context_blocks = [blocks[total_blocks - 1]]

    chunk = blocks[start_idx:end_idx]
    original_metadata = extract_chunk_metadata(chunk)
    
    text_chunk_parts = []
    if prev_context_blocks: 
        suffix = profile.label_do_not_translate
        text_chunk_parts.append(f"### [{profile.label_prev_context} - {suffix}] ###\n{strip_srt(prev_context_blocks)}\n")
    
    input_payload = { m['index']: m['text'] for m in original_metadata }
    pipeline_load = sum(len(str(v)) for v in input_payload.values())
    for idx, txt in input_payload.items():
        if RE_SDH_PUNCT.fullmatch(txt):
            input_payload[idx] = ""

    from core.translation.text_cleaner import clean_and_strip_tags
    final_input_payload, batch_italic_indices, batch_alignment_map = clean_and_strip_tags(input_payload, profile)

    if batch_italic_indices and debug_mode:
        log(log_queue, session_log_file, f"✨ [Italic Passthrough] Stripped outer italics for indices: {', '.join(sorted(batch_italic_indices))}")

    text_chunk_parts.append(f"### [{profile.label_translation_blocks}] ###\n{json.dumps(final_input_payload, ensure_ascii=False, indent=2)}\n")
    
    if next_context_blocks:
        suffix = profile.label_do_not_translate
        text_chunk_parts.append(f"### [{profile.label_next_context} - {suffix}] ###\n{strip_srt(next_context_blocks)}\n")
    
    text_chunk = '\n'.join(text_chunk_parts)
    indices = [d['index'] for d in original_metadata]
    
    summary_text = context_state.get('summary', profile.default_opening_summary)
    last_speaker = context_state.get('last_speaker_info') or context_state.get('last_speaker', profile.default_unknown_speaker)
    setting = context_state.get('current_setting', profile.default_setting_label)
    
    last_lines = context_state.get('last_two_lines_target', context_state.get('last_two_lines_heb', []))
    use_native = profile.use_native_instructions
    
    last_line_str = ""
    if last_lines:
        last_line_template = profile.native_last_line_label if use_native else "Last translated line (from previous batch): '{last_line}'"
        last_line_str = last_line_template.replace("{last_line}", last_lines[-1])
        
    continuity_note = context_state.get('continuity_note', '')
    continuity_str = ""
    if continuity_note and continuity_note.strip():
        continuity_template = profile.native_continuity_note_label if use_native else "⚠️ Continuity note from previous batch (Attention!): {note}"
        continuity_str = continuity_template.replace("{note}", continuity_note)

    story_header = profile.native_story_context_header if use_native else "### Story Context (Previous Batches) ###"
    setting_label = (profile.native_current_setting_label if use_native else "Current Setting: {setting}").replace("{setting}", setting)
    summary_label = (profile.native_plot_summary_label if use_native else "Plot Summary: {summary}").replace("{summary}", summary_text)
    speaker_label = (profile.native_last_speaker_label if use_native else "Last Speaker (previous batch): {speaker}").replace("{speaker}", last_speaker)

    context_section_lines = [
        story_header,
        setting_label,
        summary_label,
        speaker_label
    ]
    if last_line_str: context_section_lines.append(last_line_str)
    if continuity_str: context_section_lines.append(continuity_str)
        
    context_section = '\n'.join(context_section_lines)

    supports_structured = (model_cfg.get('provider') in ['openai', 'lmstudio'] and 
                         (model_cfg.get('provider') == 'lmstudio' or any(m in model_cfg.get('name', '').lower() for m in ["gpt-4o", "gpt-4o-mini", "o1"])))

    active_schema_template = get_json_schema(profile, is_lite=(not use_scratchpad))
    
    mandatory_schema_msg = profile.native_schema_mandatory_label if profile.use_native_instructions else "### MANDATORY: Respond EXACTLY in the specified JSON Schema format. ###"
    
    if not supports_structured:
        schema_instruction = f"\n{active_schema_template}\n"
    else:
        schema_instruction = f"\n{mandatory_schema_msg}\n"

    has_tags = any("<" in str(val) or "♪" in str(val) for val in input_payload.values())
    tag_rule = ""
    if has_tags:
        tag_rule = get_tag_rule(profile) + "\n"

    from core import text_processing
    importlib.reload(text_processing)
    pre_warnings = text_processing.pre_audit_source(input_payload, illegal_labels=illegal_labels, profile=profile)
    
    warning_section = ""
    if pre_warnings:
        warning_list = [f"Index {idx}: {msg}" for idx, msg in pre_warnings]
        header = get_special_instructions_header(profile)
        warning_section = f"\n{header}\n" + "\n".join([f"• {w}" for w in warning_list]) + "\n"
        
        flagged_indices = sorted(list(set(str(idx) for idx, msg in pre_warnings)), key=lambda x: int(x) if x.isdigit() else 0)
        if debug_mode:
            log(log_queue, session_log_file, f"🔍 Forensic Scout: Detailed analysis for indices {flagged_indices}.")
            for idx, msg in pre_warnings:
                log(log_queue, session_log_file, f"   ↳ Index {idx}: {msg}")
        else:
            log(log_queue, session_log_file, f"🔍 Forensic Scout: Targets flagged at indices {flagged_indices}.")

    from core.translation.prompt_builder import build_user_prompt
    final_prompt = build_user_prompt(
        profile, model_cfg, context_state, expected_count, indices, 
        text_chunk, input_payload, use_scratchpad, warning_section, 
        tag_rule, last_judge_error, last_judged_indices
    )
    
    return final_prompt, indices, original_metadata, input_payload, pipeline_load, batch_italic_indices, batch_alignment_map
