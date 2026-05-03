import re
import json
from core.text_processing import pre_repair_json
from core.translation.schema_recovery import recover_schema
from utils.app_utils import log

def process_llm_response(raw_res, input_payload, batch_italic_indices, 
                         batch_alignment_map, profile, stats, 
                         session_log_file, indices, current_batch_size, 
                         debug_mode=False, log_queue=None):
    """
    1. Repairs string JSON artifacts
    2. Runs schema recovery
    3. Restores italic and line alignment tags
    4. Triggers heuristic validation filters
    Returns:
       (received_dict, res_json)
    """
    cleaned_res = pre_repair_json(raw_res)
    try:
        res_json = json.loads(cleaned_res)
    except json.JSONDecodeError:
        from core.translation_stats import _inc_by_size
        _inc_by_size(stats["json_parse_errors"], current_batch_size)
        raise

    has_placeholder = False
    if profile.use_native_instructions and profile.native_placeholder_indicators:
        for indicator in profile.native_placeholder_indicators:
            if indicator in cleaned_res:
                has_placeholder = True
                break
    elif "<insert" in cleaned_res or "<brief summary" in cleaned_res:
        has_placeholder = True

    if has_placeholder:
        log(log_queue, session_log_file, "⚠️ AUDITOR WARNING: The LLM responded with identical placeholder text from the prompt template!")

    received_dict = recover_schema(res_json, stats, session_log_file, log_queue)

    it_restored = 0
    it_stripped = 0
    for idx in indices:
        if idx not in received_dict: continue
        target_text = str(received_dict[idx]).strip()
        
        # Case A: Should have italics
        if idx in batch_italic_indices:
            if target_text and not (target_text.startswith('<i>') and target_text.endswith('</i>')):
                received_dict[idx] = f"<i>{target_text}</i>"
                it_restored += 1
        
        # Case B: Should NOT have italics (Hallucination removal)
        else:
            source_text = str(input_payload.get(idx, ""))
            if "<i>" not in source_text:
                match = re.match(r"^<i>(.*)</i>$", target_text, re.DOTALL)
                if match:
                    received_dict[idx] = match.group(1).strip()
                    it_stripped += 1

    if (it_restored > 0 or it_stripped > 0) and debug_mode:
        log_msg = f"✨ [Italic Passthrough] Enforcement: Restored {it_restored} | Stripped hallucinated {it_stripped}"
        log(log_queue, session_log_file, log_msg)

    al_restored = 0
    for idx in indices:
        if idx in batch_alignment_map:
            target_text = received_dict[idx]
            if not target_text.strip():
                continue

            subtitle_aligns = batch_alignment_map[idx]
            h_lines = target_text.split('\n')
            
            # Case A: Line count matches perfectly
            if len(h_lines) >= max(subtitle_aligns.keys()) + 1:
                for line_idx, pos in subtitle_aligns.items():
                    h_lines[line_idx] = rf"{{\an{pos}}}{h_lines[line_idx]}"
                    al_restored += 1
                received_dict[idx] = '\n'.join(h_lines)
            
            # Case B: Line count mismatch
            else:
                unique_pos = sorted(list(set(subtitle_aligns.values())))
                tags = "".join([rf"{{\an{p}}}" for p in unique_pos])
                received_dict[idx] = f"{tags}{target_text}"
                al_restored += len(unique_pos)
    
    if al_restored > 0 and debug_mode:
        log(log_queue, session_log_file, f"✨ [Alignment Passthrough] Restored {{\\anX}} for {al_restored} lines.")

    return received_dict, res_json
