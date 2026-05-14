import json
import os
from core.llm_api import call_llm
from core.text_processing import pre_repair_json

def build_editor_system_prompt(sysprm_data: dict = None, editor_profile_text: str = None) -> str:
    """
    Constructs a tailored, project-specific System Prompt for the Senior Editor,
    incorporating either a raw .sysprm structure or a token-optimized pre-compiled profile.
    """
    if not sysprm_data:
        sysprm_data = {}
        
    # 1. Extract languages
    lang_section = sysprm_data.get("language", {})
    src_code = lang_section.get("source", "en")
    tgt_code = lang_section.get("target", "he")
    
    # Resolve human-readable names via core language profiles
    try:
        from core.language_profiles import get_profile
        profile = get_profile(src_code, tgt_code)
        source_name = profile.source_lang
        target_name = profile.target_lang
    except Exception:
        mapping = {"en": "English", "he": "Hebrew", "fr": "French", "es": "Spanish", "zh": "Chinese"}
        source_name = mapping.get(src_code, src_code).capitalize()
        target_name = mapping.get(tgt_code, tgt_code).capitalize()

    # 2. Collect Project Context (Favor optimized profile, fallback to raw context)
    if editor_profile_text:
        project_context_block = editor_profile_text
    else:
        series_context_list = sysprm_data.get("series_context", [])
        project_context_block = "\n".join(series_context_list) if series_context_list else "No specific project glossary provided."

    # 3. Construct Dynamic Prompt
    prompt = f"""You are a Senior {target_name} Localization Editor for high-stakes TV broadcasting, specializing in premium subtitle translation.

Your sole goal is to audit translated {target_name} subtitles against their original {source_name} source and identify CRITICAL semantic improvements. 

### YOUR SCOPE (ONLY FLAG THESE ERRORS):
1. Severe mistranslations or missed cultural idioms (e.g., translating "snow job" literally instead of its true meaning).
2. Glossary violations (Failure to follow the canonical reference glossary provided below).
3. Gender agreement mistakes based on context, character names, or dialogue flow.
4. English Leaks: If the translator accidentally left/leaked raw English text in the Hebrew translation, you MUST translate it properly into Hebrew (Mark confidence as 1.0).

### PROJECT REFERENCE GLOSSARY & CHARACTERS ###
🚨 **CRITICAL INSTRUCTION FOR YOU**: The reference dataset below contains the rules provided to the original translator. 
* **IGNORE** all technical layout rules, speech-tag rules (e.g. "PROBST:"), line-length constraints, or formatting/capitalization instructions. Those are NOT your concern.
* **EXTRACT ONLY** character names, genders, and specific term-to-term translation mappings. Treat those as your absolute source of truth for GLOSSARY_VIOLATION or GENDER_ERROR audits.

--- START REFERENCE DATA ---
{project_context_block}
--- END REFERENCE DATA ---

### LAYOUT GUIDELINE:
- Try to match the general visual layout of the original subtitle. If a line contains an existing line-break (`\n` or `<br>`), attempt to preserve a natural, grammatically sensible line-break in your replacement text to prevent excessive line width.

### EXPLICIT SILENCE RULE:
- If a translated line is culturally accurate, grammatically correct, and natural, do NOT flag it.
- DO NOT suggest changes for minor stylistic differences, synonyms, or personal taste. 
- Avoid stylistic pedantry. We only want high-impact, high-confidence fixes.
- If you find NO errors in a batch, your output 'suggestions' list MUST BE EMPTY [].

### RESPONSE FORMAT:
You must respond EXACTLY in the specified JSON Schema format.
"""
    return prompt

EDITOR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "description": "List of semantic/idiomatic corrections for the active chunk.",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "string",
                        "description": "The numeric subtitle index being corrected."
                    },
                    "current_he": {
                        "type": "string",
                        "description": "The current Hebrew text before modification."
                    },
                    "replacement_he": {
                        "type": "string",
                        "description": "The new and improved Hebrew translation."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Clear explanation of why the change is necessary."
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["CRITICAL", "GLOSSARY_VIOLATION", "GENDER_ERROR"],
                        "description": "Classification of the error."
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Confidence score from 0.0 to 1.0."
                    }
                },
                "required": ["index", "current_he", "replacement_he", "reason", "severity", "confidence"],
                "additionalProperties": False
            }
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False
}

def get_or_create_editor_profile(
    sysprm_path: str,
    model_cfg: dict,
    api_key: str,
    log_func=None,
    debug_mode: bool = False
) -> str:
    """
    Retrieves a condensed, token-optimized Editor Profile.
    If already cached in 'editor_profiles/', loads it instantly from disk.
    Otherwise, runs a ONE-TIME LLM extraction and saves it.
    """
    # 1. Ensure the caching directory exists
    cache_dir = "editor_profiles"
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
        if log_func:
            log_func(f"📁 Created cache directory: {cache_dir}")
            
    # 2. Derive cache filename (maps 1-to-1 with sysprm name)
    base_name = os.path.basename(sysprm_path)
    cache_filename = os.path.splitext(base_name)[0] + ".sneprf"
    cache_path = os.path.join(cache_dir, cache_filename)
    
    # 3. Check Cache Hit (The ultimate money saver)
    if os.path.exists(cache_path):
        if log_func:
            log_func(f"♻️ [Hybrid Mastermind] Cache Hit! Loading optimized profile from disk.")
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()
            
    # 4. Cache Miss -> Run Extraction LLM Call
    if log_func:
        log_func(f"📥 [Hybrid Mastermind] Cache Miss. Compiling token-optimized profile with ONE-TIME LLM call...")
        
    if not os.path.exists(sysprm_path):
        raise FileNotFoundError(f"Sysprm configuration file not found at: {sysprm_path}")
        
    with open(sysprm_path, "r", encoding="utf-8") as f:
        sysprm_data = json.load(f)
        
    series_context = "\n".join(sysprm_data.get("series_context", []))
    if not series_context.strip():
        return "No specific project context provided in sysprm."
        
    # 5. Define the Technical Reference Condenser System Prompt
    ext_system = """You are a Technical Reference Condenser. Your sole goal is to strip massive instruction blocks into token-lean, perfectly clean reference sheets.

### YOUR INSTRUCTIONS:
1. **EXTRACT ONLY**:
   - Names of Cast / Characters and their associated Genders (e.g., M / F).
   - Term-to-Term Translation Glossary maps (e.g., "Term A" -> "מונח א").
2. **DISCARD COMPLETELY**:
   - Technical instructions, rules, character limits, stylistic advice, tone requirements, and conversational fillers.
3. **OUTPUT FORMAT**:
   - You MUST respond with a valid JSON object containing 'cast' and 'glossary' mappings.
   - Be brief. Minimize tokens used."""

    ext_user = f"Condense the following raw translation instructions into a clean JSON Cast & Glossary sheet:\n\n{series_context}"
    
    is_debug = debug_mode() if callable(debug_mode) else debug_mode
    if is_debug:
        log_msg_system = f"\n--- 🧪 [DEBUG] CONDENSER SYSTEM PROMPT ---\n{ext_system}\n--- 🧪 END ---\n"
        log_msg_user = f"\n--- 🧪 [DEBUG] CONDENSER USER PROMPT ---\n{ext_user}\n--- 🧪 END ---\n"
        
        if file_log_func:
            file_log_func(log_msg_system)
            file_log_func(log_msg_user)
        else:
            print(log_msg_system)
            print(log_msg_user)
        
    # Fire call to extract
    raw_res, in_t, out_t, cached_t, reasoning_t = call_llm(
        model_cfg=model_cfg,
        system_prompt=ext_system,
        user_prompt=ext_user,
        api_key=api_key
    )
    
    if not raw_res:
        raise ValueError("The Reference Condenser LLM call failed to return a result.")
        
    # 6. Save to persistent Cache for future episode reuse
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(raw_res.strip())
        
    if log_func:
        log_func(f"✅ Saved condensed profile to cache ({len(raw_res)} chars): {cache_path}")
        
    return raw_res.strip()

def build_editor_user_prompt(batch_payload: dict) -> str:
    """
    Constructs the user prompt instructing the LLM to audit the active chunk,
    while respecting the preceding/succeeding context blocks.
    """
    context_before = batch_payload.get("context_before", {})
    active_chunk = batch_payload.get("active_chunk", {})
    context_after = batch_payload.get("context_after", {})
    
    prompt_lines = []
    
    if context_before:
        prompt_lines.append("### [READ-ONLY PRECEDING CONTEXT (Do NOT Audit or Edit)] ###")
        prompt_lines.append(json.dumps(context_before, ensure_ascii=False, indent=2))
        prompt_lines.append("")
        
    prompt_lines.append("### [ACTIVE CHUNK TO AUDIT AND REFINE] ###")
    prompt_lines.append("Analyze the following lines carefully. These are the ONLY lines you are auditing and flagging for corrections:")
    prompt_lines.append(json.dumps(active_chunk, ensure_ascii=False, indent=2))
    prompt_lines.append("")
    
    if context_after:
        prompt_lines.append("### [READ-ONLY SUCCEEDING CONTEXT (Do NOT Audit or Edit)] ###")
        prompt_lines.append(json.dumps(context_after, ensure_ascii=False, indent=2))
        prompt_lines.append("")
        
    prompt_lines.append("### MANDATORY INSTRUCTION ###")
    prompt_lines.append("Evaluate only the 'ACTIVE CHUNK' indices. Use the surrounding context solely to understand flow, pronouns, and conversational continuity.")
    prompt_lines.append("Apply the Explicit Silence Rule: Only report errors that actually hurt translation fidelity.")
    
    return "\n".join(prompt_lines)

def audit_batch_with_editor(
    model_cfg: dict,
    api_key: str,
    batch_payload: dict,
    sysprm_data: dict = None,
    editor_profile_text: str = None,
    supports_structured: bool = True,
    log_func = None,
    file_log_func = None,
    debug_mode: bool = False
) -> dict:
    """
    Sends a single batch payload to the Heavyweight LLM Senior Editor
    and retrieves its structured suggestions list.
    
    Returns:
        A dictionary containing the 'suggestions' key with findings, e.g.:
        { "suggestions": [...] }
    """
    system_prompt = build_editor_system_prompt(sysprm_data, editor_profile_text)
    user_prompt = build_editor_user_prompt(batch_payload)
    
    # Append visual schema instruction to guarantee 100% structural key compliance
    # (Essential for non-OpenAI providers like DeepSeek, LM Studio, or Claude)
    schema_repr = {
        "suggestions": [
            {
                "index": "52",
                "current_he": "...",
                "replacement_he": "...",
                "reason": "...",
                "severity": "CRITICAL",
                "confidence": 0.95
            }
        ]
    }
    user_prompt += f"\n\nRespond EXACTLY in the following JSON format:\n```json\n{json.dumps(schema_repr, indent=4)}\n```"
    
    # --- LOGGING & TRANSPARENCY (DEBUG MODE) ---
    if log_func:
        batch_idx = batch_payload.get("active_chunk", {})
        indices_str = f"{list(batch_idx.keys())[0]}-{list(batch_idx.keys())[-1]}" if batch_idx else "empty"
        log_func(f"⏳ [Senior Editor] Auditing batch (cues {indices_str})...")
        
    is_debug = debug_mode() if callable(debug_mode) else debug_mode
    if is_debug:
        log_msg_system = f"\n--- 🧪 [DEBUG] SENIOR EDITOR SYSTEM PROMPT START ---\n{system_prompt}\n--- 🧪 END SYSTEM PROMPT ---\n"
        log_msg_user = f"\n--- 🧪 [DEBUG] SENIOR EDITOR USER PROMPT START ---\n{user_prompt}\n--- 🧪 END USER PROMPT ---\n"
        
        if file_log_func:
            file_log_func(log_msg_system)
            file_log_func(log_msg_user)
        else:
            print(log_msg_system)
            print(log_msg_user)

    # Fire call
    raw_res, in_t, out_t, cached_t, reasoning_t = call_llm(
        model_cfg=model_cfg,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        response_format=EDITOR_RESPONSE_SCHEMA if supports_structured else None
    )
    
    if is_debug:
        log_msg_raw = f"\n--- 🧪 [DEBUG] SENIOR EDITOR RAW RESPONSE ---\n{raw_res}\n--- 🧪 END RAW RESPONSE ---\n"
        if file_log_func:
            file_log_func(log_msg_raw)
        else:
            print(log_msg_raw)
    
    if not raw_res:
        return {"suggestions": [], "tokens": {"in": in_t, "out": out_t}}
        
    # Parse & Clean
    try:
        cleaned = pre_repair_json(raw_res)
        parsed = json.loads(cleaned)
    except Exception as e:
        # Fallback regex extraction if parsing failed
        import re
        match = re.search(r'\{.*\}', raw_res, re.DOTALL)
        if match:
            try:
                parsed = json.loads(pre_repair_json(match.group(0)))
            except:
                raise ValueError(f"Failed to parse JSON Senior Editor response: {e}. Raw content: {raw_res}")
        else:
            raise ValueError(f"No valid JSON found in Senior Editor response: {e}. Raw content: {raw_res}")
            
    # Attach token telemetry for cost assessments later
    parsed["_telemetry"] = {
        "input_tokens": in_t,
        "output_tokens": out_t,
        "cached_tokens": cached_t,
        "reasoning_tokens": reasoning_t
    }
    
    return parsed
