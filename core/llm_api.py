import os
import platform
import subprocess
import json
import re

RE_FALLBACK_JSON = re.compile(r'\{.*\}', re.DOTALL)
from google import genai
from google.genai import types
from openai import OpenAI

from core.text_processing import pre_repair_json
from core.llm._utils import _strip_markdown_fences, _supports_structured_output



def is_process_alive(pid):
    """Checks if a process is alive - supports Windows, Linux, and macOS."""
    if not pid:
        return False
    
    current_os = platform.system()

    if current_os == "Windows":
        try:
            output = subprocess.check_output(
                f'tasklist /FI "PID eq {pid}" /NH', 
                shell=True, 
                text=True, 
                stderr=subprocess.DEVNULL
            )
            return str(pid) in output
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True


def ping_model(model_cfg):
    """
    Minimal connectivity check for a given model configuration.
    Returns (True, "OK") or (False, "Error message").
    """
    if not model_cfg:
        return False, "No model configuration provided."
    
    provider = model_cfg.get("provider", "openai")
    api_key = model_cfg.get("api_key", "")
    base_url = model_cfg.get("base_url", "")
    model_name = model_cfg.get("name", "")

    if provider == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com"

    try:
        if provider == "google":
            client = genai.Client(api_key=api_key)
            # Try a very simple generate_content call
            client.models.generate_content(
                model=model_name,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=1)
            )
            return True, "OK"
        elif provider == "lmstudio":
            # Hardcoded local endpoint for LM Studio to match call_llm
            local_url = base_url or "http://localhost:1234/v1"
            client = OpenAI(api_key=api_key or "lm-studio", base_url=local_url)
            client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                timeout=10
            )
            return True, "OK"
        else:
            # OpenAI / DeepSeek / Groq
            client = OpenAI(api_key=api_key or "sk-no-key-required", base_url=base_url or None)
            client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                timeout=10 # Short timeout for pre-flight
            )
            return True, "OK"
    except Exception as e:
        err_msg = str(e)
        if "400" in err_msg and "No models loaded" in err_msg:
            return False, "LM Studio is running, but no model is loaded. Please load a model in LM Studio."
        if "Connection error" in err_msg or "Failed to connect" in err_msg:
            return False, f"Could not connect to {provider} at {base_url or 'default endpoint'}. Is the server running?"
        if "401" in err_msg or "Incorrect API key" in err_msg:
            return False, f"Invalid API key for {provider}. Please check your settings."
        return False, f"{provider} Error: {err_msg}"



from core.llm.schemas import generate_batch_schema, generate_judge_schema


from core.llm.providers.google import call_google
from core.llm.providers.openai import call_openai
from core.llm.providers.deepseek import call_deepseek
from core.llm.providers.lmstudio import call_lmstudio

_PROVIDER_REGISTRY = {
    'google': call_google,
    'openai': call_openai,
    'deepseek': call_deepseek,
    'lmstudio': call_lmstudio,
}

def call_llm(model_cfg, system_prompt, user_prompt, api_key, indices_list=None, is_judge=False, response_format=None, profile=None):
    provider = model_cfg.get('provider')
    handler = _PROVIDER_REGISTRY.get(provider)
    if not handler:
        raise ValueError(f"Unknown or unsupported provider: {provider}")
    return handler(model_cfg, system_prompt, user_prompt, api_key, indices_list, is_judge, response_format, profile)






def _judge_overlap_block(chunk_indices, ordered_srt_indices, eng_by_index, target_lookup, profile=None):
    """One cue before / after the chunk: EN+HE for judge context (not directly audited)."""
    use_native = profile and getattr(profile, 'use_native_instructions', False)
    if use_native and profile.native_judge_strings:
        nj = profile.native_judge_strings
        lines = [
            nj.get("overlap_header", "### CONTEXTUAL OVERLAP (Do not audit directly — for understanding continuity and permitted leakage only) ###"),
            nj.get("overlap_desc", "Do not reject the OVERLAP lines; use them only to understand if information \"leaked\" to an adjacent subtitle in the audited batch."),
        ]
    else:
        lines = [
            "### CONTEXTUAL OVERLAP (Do not audit directly — for understanding continuity and permitted leakage only) ###",
            "Do not reject the OVERLAP lines; use them only to understand if information \"leaked\" to an adjacent subtitle in the audited batch.",
        ]

    def fmt_neighbor(title, idx_key):
        if idx_key is None:
            none_label = profile.native_judge_strings.get("overlap_none", "(None — file boundary)") if use_native and profile.native_judge_strings else "(None — file boundary)"
            return f"{title}\n{none_label}\n"
        en = eng_by_index.get(idx_key, "")
        target_text = target_lookup.get(idx_key, "")
        
        if use_native and profile.native_judge_strings:
            nj = profile.native_judge_strings
            target_disp = target_text.strip() if isinstance(target_text, str) and target_text.strip() else nj.get("overlap_not_translated", "This line has not been translated yet")
            source_label = nj.get("source_label", "Source ({lang}):").format(lang=profile.source_lang)
            target_label = nj.get("target_label", "Target ({lang}):").format(lang=profile.target_lang)
            return f"{title} — Index {idx_key}:\n{source_label}\n{en}\n\n{target_label}\n{target_disp}\n"
        else:
            target_disp = target_text.strip() if isinstance(target_text, str) and target_text.strip() else "This line has not been translated yet - do not reject it for this reason - you are only auditing the translation of the preceding lines"
            return f"{title} — Index {idx_key}:\nSource:\n{en}\n\nTarget:\n{target_disp}\n"

    if not ordered_srt_indices or not chunk_indices:
        missing_label = profile.native_judge_strings.get("overlap_missing_context", "(External context not provided.)") if use_native and profile.native_judge_strings else "(External context not provided.)"
        lines.append(missing_label)
        return "\n".join(lines)

    try:
        i0 = ordered_srt_indices.index(chunk_indices[0])
        i1 = ordered_srt_indices.index(chunk_indices[-1])
    except ValueError:
        resolve_label = profile.native_judge_strings.get("overlap_cannot_resolve", "(Cannot resolve neighbors — missing index in the order list.)") if use_native and profile.native_judge_strings else "(Cannot resolve neighbors — missing index in the order list.)"
        lines.append(resolve_label)
        return "\n".join(lines)

    prev_idx = ordered_srt_indices[i0 - 1] if i0 > 0 else None
    next_idx = ordered_srt_indices[i1 + 1] if i1 + 1 < len(ordered_srt_indices) else None

    pre_label = profile.native_judge_strings.get("overlap_pre_batch", "One line before the chunk start (Pre-batch information)") if use_native and profile.native_judge_strings else "One line before the chunk start (Pre-batch information)"
    post_label = profile.native_judge_strings.get("overlap_post_batch", "One line after the chunk end (Post-batch information)") if use_native and profile.native_judge_strings else "One line after the chunk end (Post-batch information)"

    lines.append(fmt_neighbor(pre_label, prev_idx))
    lines.append(fmt_neighbor(post_label, next_idx))
    return "\n".join(lines)


def call_llm_judge(judge_model_cfg, indices, eng_dict, target_dict, api_key, ordered_srt_indices,
                   log_func=None, progress_func=None, file_log_func=None, 
                   audit_reason_native=None, eng_by_index=None, target_completed_by_index=None, ui_queue=None, judge_batch_size=None, debug_mode=False, profile=None, main_system_prompt=None):
    """
    Calls a second LLM to audit the translation batch.
    Returns: (is_overall_valid, error_map, in, out, cached, reasoning)
    """
    from core.text_processing import pre_repair_json
    from core.constants import build_judge_system_prompt
    use_native = profile and getattr(profile, 'use_native_instructions', False)
    
    if judge_batch_size is not None:
        try:
            chunk_size = int(judge_batch_size)
        except ValueError:
            chunk_size = 20
    else:
        from core.constants import judge_batch_size as default_judge_batch
        try:
            chunk_size = int(default_judge_batch)
        except ValueError:
            chunk_size = 20

    supports_structured = (judge_model_cfg.get('provider') == 'openai' and 
                          any(m in judge_model_cfg.get('name', '').lower() for m in ["gpt-4", "o1"])) or \
                          (judge_model_cfg.get('provider') == 'lmstudio')

    if profile:
        system_prompt = build_judge_system_prompt(profile)
    else:
        # Fallback to English/Hebrew if no profile is provided
        from core.language_profiles import get_profile
        fallback_profile = get_profile("en", "he")
        system_prompt = build_judge_system_prompt(fallback_profile)

    if main_system_prompt:
        if use_native and profile and profile.native_judge_strings:
            reference_header = profile.native_judge_strings.get("reference_material_header", "\n\n### חומרי עזר (לעיונך בלבד) ###\nלהלן המילון, רשימת הדמויות וההנחיות שניתנו למתרגם. השתמש במידע זה אך ורק כדי לוודא אם המתרגם השתמש במונחים, שמות או מגדרים נכונים. אל תפסול על סמך חוקים המופיעים כאן, אלא רק על סמך 'חוקי הפסילה' שהוגדרו לך למעלה.\n")
        else:
            reference_header = "\n\n### REFERENCE MATERIAL ONLY ###\nThe following is the glossary, character list, and context provided to the translator. Use this ONLY to verify if the translator correctly used specific terms, genders, or names. Do NOT reject based on instructions here, your ONLY rejection criteria are the Rejection Rules defined above.\n"
        
        system_prompt += reference_header + main_system_prompt

    system_prompt += "\n\nRespond EXACTLY in the specified JSON Schema format."

    total_in, total_out, total_cached, total_reasoning = 0, 0, 0, 0
    master_error_map = {}
    is_overall_valid = True

    chunks = [indices[i:i + chunk_size] for i in range(0, len(indices), chunk_size)]
    
    if file_log_func:
        file_log_func(f"⛔️ Starting Chunked Audit: {len(chunks)} chunks (Size: {chunk_size} lines per chunk)")
    if log_func:
        log_func(f"   ↳ ⚠️ Judge: Auditing in {len(chunks)} chunk(s) of {chunk_size} lines each...")
    
    target_lookup = {**(target_completed_by_index or {}), **target_dict}
    eng_map = eng_by_index or {}

    for idx, chunk_indices in enumerate(chunks):
        if progress_func:
            progress_func(idx + 1, len(chunks))
        chunk_eng = {k: eng_dict[k] for k in chunk_indices if k in eng_dict}
        chunk_target = {k: target_dict[k] for k in chunk_indices if k in target_dict}
        
        source_str = json.dumps(chunk_eng, ensure_ascii=False, indent=2)
        trans_str = json.dumps(chunk_target, ensure_ascii=False, indent=2)
        overlap_str = _judge_overlap_block(chunk_indices, ordered_srt_indices, eng_map, target_lookup, profile=profile)
        if overlap_str:
            if use_native and profile.native_judge_strings:
                header = profile.native_judge_strings.get("overlap_header", "### [READ ONLY CONTEXT] (REFERENCE ONLY - DO NOT AUDIT THESE LINES) ###")
                overlap_str = f"{header}\n{overlap_str}\n"
            else:
                overlap_str = f"### [READ ONLY CONTEXT] (REFERENCE ONLY - DO NOT AUDIT THESE LINES) ###\n{overlap_str}\n"

        source_lang_name = profile.source_lang if profile else "English"
        target_lang_name = profile.target_lang if profile else "Target"
        
        if use_native and profile.native_judge_strings:
            nj = profile.native_judge_strings
            chunk_header = nj.get("chunk_header", "### AUDIT CHUNK {current}/{total} (Blocks: {start}-{end}) ###").format(current=idx+1, total=len(chunks), start=chunk_indices[0], end=chunk_indices[-1])
            source_header = nj.get("source_label", "Source ({lang}):").format(lang=source_lang_name)
            target_header = nj.get("target_label", "Translation ({lang}):").format(lang=target_lang_name)
        else:
            chunk_header = f"### AUDIT CHUNK {idx+1}/{len(chunks)} (Blocks: {chunk_indices[0]}-{chunk_indices[-1]}) ###"
            source_header = f"Source ({source_lang_name}):"
            target_header = f"Translation ({target_lang_name}):"

        user_prompt = f"""{chunk_header}

{overlap_str}

{source_header}
{source_str}

{target_header}
{trans_str}
"""
        # SURGICAL INJECTION: Only show audit reasons relevant to THIS chunk
        if audit_reason_native:
            relevant_reasons = []
            # Audit reasons are typically separated by '; ' and prefixed with 'IDX:#'
            reasons_list = audit_reason_native.split("; ")
            for r in reasons_list:
                # Check for global errors OR specific index matches for THIS chunk
                if "IDX:" in r:
                    # Match pattern like IDX:25 or IDX:25,26
                    try:
                        idx_part = r.split("|")[0].replace("IDX:", "").strip()
                        # `chunk_indices` contains strings (e.g. "6"). Ensure affected indices are strings.
                        affected_indices = [str(i.strip()) for i in idx_part.split(",")]
                        if any((i in chunk_indices) for i in affected_indices):
                            relevant_reasons.append(r)
                    except:
                        # Fallback: if we can't parse safely, include it to be safe
                        relevant_reasons.append(r)
                else:
                    # Global/General errors are shown to every chunk
                    relevant_reasons.append(r)

            if relevant_reasons:
                reasons_text = "\n".join(relevant_reasons)
                if use_native and profile.native_judge_strings:
                    nj = profile.native_judge_strings
                    sys_warn = nj.get("automated_warning_header", "### AUTOMATED SYSTEM AUDIT WARNING: ###")
                    sys_desc = nj.get("automated_warning_desc", "NOTE: An automated algorithm flagged a potential error above.")
                else:
                    sys_warn = "### AUTOMATED SYSTEM AUDIT WARNING: ###"
                    sys_desc = "NOTE: An automated algorithm flagged a potential error above. Review the specified index carefully. Exercise independent judgment - the algorithm might be wrong (e.g. natural length differences between languages). Only reject if you see a genuine, material error with your own eyes."
                user_prompt += f"\n{sys_warn}\n{reasons_text}\n{sys_desc}\n"

        end_of_data = profile.native_judge_strings.get("end_of_data", "### END OF DATA ###") if use_native and profile.native_judge_strings else "### END OF DATA ###"
        user_prompt += f"{end_of_data}\n"
        
        if use_native and profile.native_judge_strings:
            final_warn = profile.native_judge_strings.get("final_warning", "FINAL WARNING: Reject...").format(lang=target_lang_name, source=source_lang_name)
        else:
            final_warn = f"\nFINAL WARNING: Reject the batch (`is_rejected: true`) ONLY if you see the error with your own eyes in the Translation ({target_lang_name}) field. DO NOT reject if the error only exists in the Source ({source_lang_name}).\n"
        user_prompt += f"\n{final_warn}\n"

        judge_schema = {
            "type": "object",
            "properties": {
                "thought_process": {
                    "type": "string",
                    "description": profile.native_judge_strings.get("field_desc_thought", "In-depth analysis...") if use_native and profile.native_judge_strings else "In-depth analysis (minimum one full sentence). Explain exactly what you checked. Do not use '...'."
                },
                "summary": {
                    "type": "string",
                    "description": profile.native_judge_strings.get("field_desc_summary", "Short plot summary...") if use_native and profile.native_judge_strings else "Short plot summary. Do not use '...'."
                },
                "is_rejected": {
                    "type": "boolean",
                    "description": profile.native_judge_strings.get("field_desc_is_rejected", "True if rejected...") if use_native and profile.native_judge_strings else "True if rejected (error found). False if completely flawless."
                },
                "error_map": {
                    "type": "object",
                    "properties": {str(k): {"type": "string", "description": profile.native_judge_strings.get("field_desc_error_map", "Error description...") if use_native and profile.native_judge_strings else "Error description (full sentence). Leave empty if flawless."} for k in chunk_indices},
                    "required": [str(k) for k in chunk_indices],
                    "additionalProperties": False
                }
            },
            "required": ["thought_process", "summary", "is_rejected", "error_map"],
            "additionalProperties": False
        }

        try:
            if log_func:
                log_func(f"   ↳ ⏳ Judge Chunk {idx+1}/{len(chunks)} [{chunk_indices[0]}–{chunk_indices[-1]}]: sending...")
            
            if file_log_func:
                file_log_func(f"--- JUDGE CHUNK {idx+1} SYSTEM PROMPT START ---\n{system_prompt}\n--- JUDGE CHUNK {idx+1} SYSTEM PROMPT END ---")
                file_log_func(f"--- JUDGE CHUNK {idx+1} USER PROMPT START ---\n{user_prompt}\n--- JUDGE CHUNK {idx+1} USER PROMPT END ---")
                if supports_structured:
                    file_log_func(f"--- JUDGE CHUNK {idx+1} STRUCTURED OUTPUT SCHEMA ---\n{json.dumps(judge_schema, indent=2, ensure_ascii=False)}\n")

            if ui_queue:
                chunk_load = 0
                for idx_c in chunk_indices:
                    chunk_load += len(str(eng_dict.get(idx_c, "")))
                    chunk_load += len(str(target_dict.get(idx_c, "")))
                ui_queue.put(("judge_timer_start", {"size": len(chunk_indices), "load": chunk_load}))

            raw_res, in_t, out_t, cached_t, reasoning_t = call_llm(
                judge_model_cfg, system_prompt, user_prompt, api_key,
                response_format=judge_schema if supports_structured else None
            )

            if ui_queue:
                ui_queue.put(("judge_timer_stop", chunk_load))

            total_in += in_t
            total_out += out_t
            total_cached += cached_t
            total_reasoning += reasoning_t

            if file_log_func:
                try:
                    pretty_res = json.dumps(json.loads(pre_repair_json(raw_res)), indent=4, ensure_ascii=False)
                except:
                    pretty_res = raw_res
                file_log_func(f"--- JUDGE CHUNK {idx+1} RAW RESPONSE START ---\n{pretty_res}\n--- JUDGE CHUNK {idx+1} RAW RESPONSE END ---")

            if not raw_res: 
                if log_func: log_func(f"   ↳ ❌ Judge Chunk {idx+1}: REJECTED (Empty LLM Response)")
                is_overall_valid = False
                break

            # Parse
            parsed = {}
            try:
                parsed = json.loads(pre_repair_json(raw_res))
            except:
                match = RE_FALLBACK_JSON.search(raw_res)
                if match:
                    try: 
                        parsed = json.loads(pre_repair_json(match.group(0)))
                    except: 
                        if log_func: log_func(f"   ↳ ❌ Judge Chunk {idx+1}: REJECTED (JSON Parse Failed)")
                        is_overall_valid = False
                        break
                else: 
                    if log_func: log_func(f"   ↳ ❌ Judge Chunk {idx+1}: REJECTED (No JSON Object Found)")
                    is_overall_valid = False
                    break

            # Check rejection
            is_rejected = parsed.get('is_rejected', False)
            if is_rejected:
                is_overall_valid = False
            
            # Merge errors
            err_map = parsed.get('error_map', {})
            master_error_map.update(err_map)

            if log_func:
                tok_str = f"(In: {in_t:,} | Out: {out_t:,})" if (in_t or out_t) else ""
                if is_rejected:
                    if debug_mode:
                        desc = "; ".join([f"{k}: {v}" for k, v in err_map.items() if v])
                        log_func(f"   ↳ ❌ Judge Chunk {idx+1}: REJECTED {tok_str} — {desc}")
                    else:
                        log_func(f"   ↳ ❌ Judge Chunk {idx+1}: REJECTED {tok_str}")
                else:
                    log_func(f"   ↳ ✅ Judge Chunk {idx+1}: PASSED {tok_str}")
            
            if is_rejected:
                if log_func: log_func("   ↳ 🛑 Short-circuiting remaining chunks to save time.")
                break

        except Exception as e:
            if log_func: log_func(f"   ↳ ❌ Judge Chunk {idx+1} Exception: {e}")
            is_overall_valid = False
            break

    return is_overall_valid, master_error_map, total_in, total_out, total_cached, total_reasoning
    return is_overall_valid, master_error_map, total_in, total_out, total_cached, total_reasoning
