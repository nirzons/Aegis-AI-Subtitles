import os
import platform
import subprocess
import json
import re

RE_FALLBACK_JSON = re.compile(r'\{.*\}', re.DOTALL)
from google import genai
from google.genai import types
from openai import OpenAI

from text_processing import pre_repair_json


def is_process_alive(pid):
    """בודק אם תהליך חי - תומך ב-Windows, Linux ו-macOS."""
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



def generate_batch_schema(indices_list, use_scratchpad=True):
    """Generates a dynamic JSON schema for primary translation."""
    # Use dict.fromkeys for deduplication while preserving order (important for schema clarity)
    indices = [str(i) for i in indices_list]
    indices = list(dict.fromkeys(indices))
    srt_properties = {idx: {"type": "string"} for idx in indices}
    
    # Standard properties reordered for maximum model focus (Sandwich Structure)
    # 1. Strategy & Priming
    properties = {
        "thought_process": {
            "type": "string", 
            "description": "תהליך המחשבה, האסטרטגיה וההתלבטויות לפני התרגום הסופי. אזהרה: אל תעתיק את תיאור השדה! כתוב את מחשבותיך האמיתיות."
        },
        "summary": {
            "type": "string",
            "description": "תקציר קצר של המתרחש בעלילה כרגע. אזהרה: אל תעתיק את תיאור השדה! כתוב תקציר אמיתי."
        }
    }
    
    required_fields = ["thought_process", "summary"]
    
    # 2. Scratchpad (Optional)
    if use_scratchpad:
        properties["continuous_translation_draft"] = {
            "type": "string",
            "description": "תרגום כל הטקסטים כפסקה אחת רציפה, טבעית וזורמת."
        }
        properties["mapping_plan"] = {
            "type": "string",
            "description": "תוכנית מיפוי תמציתית של חלוקת הטיוטה לאינדקסים."
        }
        required_fields.extend(["continuous_translation_draft", "mapping_plan"])

    # 3. The Core Work
    properties["translated_srt"] = {
        "type": "object",
        "properties": srt_properties,
        "required": indices,
        "additionalProperties": False,
        "description": "מילון שקידודו הוא האינדקסים המספריים והערכים הם התרגומים הסופיים לעברית."
    }
    required_fields.append("translated_srt")

    # 4. Bookkeeping (Moved to the end)
    properties["last_speaker_info"] = {
        "type": "string",
        "description": "שם הדובר (M/F) פונה אל יעד (M/F/לא ידוע/מצלמה)."
    }
    properties["continuity_note"] = {
        "type": ["string", "null"],
        "description": "הוראת רצף לבאץ' הבא (השאר ריק אם אין)."
    }
    required_fields.extend(["last_speaker_info", "continuity_note"])
    
    return {
        "type": "object",
        "properties": properties,
        "required": required_fields,
        "additionalProperties": False
    }


def generate_judge_schema(indices_list):
    """Generates a dynamic JSON schema for the AI Judge."""
    # Use dict.fromkeys for deduplication while preserving order
    indices = [str(i) for i in indices_list]
    indices = list(dict.fromkeys(indices))
    # Error map keys are dynamic indices
    error_map_properties = {idx: {"type": "string"} for idx in indices}
    
    return {
        "type": "object",
        "properties": {
            "thought_process": {
                "type": "string",
                "description": "חובה: כתוב לפחות 2 משפטים בעברית המנתחים את התרגום מול המקור. הסבר בדיוק למה החלטת לפסול או לאשר. אל תשתמש ב-'...'."
            },
            "summary": {
                "type": "string",
                "description": "תקציר קצר (משפט אחד) של העלילה. אל תשתמש ב-'...'."
            },
            "is_valid": {
                "type": "boolean",
                "description": "True אם התרגום מושלם. False אם יש לפסול (חוקים 1-6)."
            },
            "error_map": {
                "type": "object",
                "properties": error_map_properties,
                "required": indices,
                "additionalProperties": False,
                "description": "מיפוי אינדקסים לשגיאות. חובה לתת נימוק בעברית לכל פסילה. עבור תקין השאר מחרוזת ריקה \"\"."
            }
        },
        "required": ["thought_process", "summary", "is_valid", "error_map"],
        "additionalProperties": False
    }

def call_llm(model_cfg, system_prompt, user_prompt, api_key, indices_list=None, is_judge=False, response_format=None):

    current_temp = model_cfg.get('temperature', 0.15)
    
    if model_cfg['provider'] == 'google':
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_cfg['name'],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=current_temp,
                response_mime_type="application/json" 
            ),
            contents=[user_prompt]
        )
        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return text.strip(), response.usage_metadata.prompt_token_count, response.usage_metadata.candidates_token_count, 0
    
    elif model_cfg['provider'] == 'openai':
        client = OpenAI(api_key=api_key)
        current_temp = model_cfg.get('temperature', 0.0)
        is_gpt5 = "gpt-5" in model_cfg['name'].lower()
        
        # GPT-5 / o1 reasoning models optimization: 
        # Use the 'developer' role which is the new standard for o1 models.
        # This provides the best of both worlds: high-reasoning obedience and perfect caching.
        if is_gpt5:
            req_params = {
                "model": model_cfg['name'],
                "messages": [
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                # temperature is omitted as GPT-5/o1 usually only support the default (1.0)
            }
        else:
            req_params = {
                "model": model_cfg['name'],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": current_temp
            }
            
            # OpenAI Structured Outputs (Strict Mode) check:
            # Requires gpt-4o, gpt-4o-mini, or o1 (if not using developer role)
            # OR LM Studio (which supports it in latest versions)
            supports_structured = (model_cfg['provider'] == 'openai' and 
                                 any(m in model_cfg['name'].lower() for m in ["gpt-4o", "gpt-4o-mini", "o1"])) or \
                                 (model_cfg['provider'] == 'lmstudio')
            
            if response_format is not None:
                req_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "audit_output" if is_judge else "translation_output",
                        "strict": True,
                        "schema": response_format
                    }
                }
            elif indices_list and supports_structured:
                use_scratch = model_cfg.get('enable_scratchpad', True)
                schema = generate_judge_schema(indices_list) if is_judge else generate_batch_schema(indices_list, use_scratchpad=use_scratch)
                req_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "audit_output" if is_judge else "translation_output",
                        "strict": True,
                        "schema": schema
                    }
                }

            else:
                req_params["response_format"] = {"type": "json_object"}
            
        response = client.chat.completions.create(**req_params)

        
        raw_content = response.choices[0].message.content
        # Strip markdown if model added it
        if "```json" in raw_content:
            raw_content = raw_content.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_content:
            raw_content = raw_content.split("```")[1].split("```")[0].strip()

        # Robust extraction for OpenAI/GPT-5 caching & reasoning
        cached_tokens = 0
        reasoning_tokens = 0
        usage = getattr(response, 'usage', None)
        if usage:
            # 1. Prompt Caching
            p_details = getattr(usage, 'prompt_tokens_details', None)
            if p_details:
                cached_tokens = getattr(p_details, 'cached_tokens', 0) or 0
            
            # 2. Reasoning (Brain Load)
            c_details = getattr(usage, 'completion_tokens_details', None)
            if c_details:
                reasoning_tokens = getattr(c_details, 'reasoning_tokens', 0) or 0
        
        return raw_content, response.usage.prompt_tokens, response.usage.completion_tokens, cached_tokens, reasoning_tokens

    elif model_cfg['provider'] == 'deepseek':
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=model_cfg['name'],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=current_temp,
            response_format={"type": "json_object"}
        )
        usage_dict = response.usage.model_dump() if hasattr(response.usage, 'model_dump') else vars(response.usage)
        cached_tokens = usage_dict.get('prompt_cache_hit_tokens', 0)
        
        # New robust details extraction for DeepSeek
        reasoning_tokens = 0
        if getattr(response.usage, 'prompt_tokens_details', None):
            cached_tokens = getattr(response.usage.prompt_tokens_details, 'cached_tokens', 0) or 0
        if getattr(response.usage, 'completion_tokens_details', None):
            reasoning_tokens = getattr(response.usage.completion_tokens_details, 'reasoning_tokens', 0) or 0
            
        return response.choices[0].message.content, response.usage.prompt_tokens, response.usage.completion_tokens, cached_tokens, reasoning_tokens
    
    elif model_cfg['provider'] == 'lmstudio':
        client = OpenAI(api_key=api_key, base_url="http://localhost:1234/v1", timeout=2700.0, max_retries=0)
        
        # Check for Structured Output support
        if response_format is not None or indices_list:
            # Prepare the call parameters
            req_params = {
                "model": model_cfg['name'],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": current_temp
            }
            
            # Use 'json_schema' (Strict Mode) for OpenAI high-end models AND LM Studio models.
            if (model_cfg['provider'] == 'openai' and any(m in model_cfg['name'].lower() for m in ["gpt-4o", "gpt-4o-mini", "o1"])) or model_cfg['provider'] == 'lmstudio':
                if response_format is not None:
                    schema = response_format
                else:
                    use_scratch = model_cfg.get('enable_scratchpad', True)
                    schema = generate_judge_schema(indices_list) if is_judge else generate_batch_schema(indices_list, use_scratchpad=use_scratch)
                    
                req_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "audit_output" if is_judge else "translation_output",
                        "strict": True,
                        "schema": schema
                    }
                }
            
            # Call the LLM (response_format is included if supported/requested above)
            response = client.chat.completions.create(**req_params)

            
            # Extract content with fallback for 'reasoning_content' (critical for DictaLM-Thinking)
            message = response.choices[0].message
            raw_content = getattr(message, 'content', "") or ""
            if not raw_content or not raw_content.strip():
                # Check for reasoning_content if standard content is empty
                raw_content = getattr(message, 'reasoning_content', "") or ""
            
            return raw_content, response.usage.prompt_tokens, response.usage.completion_tokens, 0, 0


        else:
            # Fallback to old manual prompt style for non-batch calls if any
            final_llm_input = (
                "### הנחיות וכללים ###\n"
                f"{system_prompt}\n\n"
                "### משימה ונתונים לתרגום ###\n"
                "אתה מתרגם עכשיו את הבאץ' הבא. זכור: הפלט חייב להיות בעברית בלבד.\n"
                f"{user_prompt}\n\n"
                "### תשובה סופית ###\n"
                "ענה עכשיו בפורמט JSON, כאשר שדה ה-text מתורגם לעברית בלבד:"
            )    
            response = client.chat.completions.create(
                model=model_cfg['name'],
                messages=[{"role": "user", "content": final_llm_input}],
                temperature=current_temp,
                max_tokens=6144,
                response_format={"type": "text"}
            )
            return response.choices[0].message.content, response.usage.prompt_tokens, response.usage.completion_tokens, 0, 0



def _judge_overlap_block(chunk_indices, ordered_srt_indices, eng_by_index, heb_lookup):
    """One cue before / after the chunk: EN+HE for judge context (not directly audited)."""
    lines = [
        "### CONTEXTUAL OVERLAP (לא לבצע ביקורת ישירה — רק להבנת רצף וזליגה מותרת) ###",
        "אל תפסול את שורות ה-OVERLAP; השתמש בהן רק כדי להבין אם מידע «זלג» לכתובית סמוכה בבאץ' הנבדק.",
    ]

    def fmt_neighbor(title, idx_key):
        if idx_key is None:
            return f"{title}\n(אין — גבול הקובץ)\n"
        en = eng_by_index.get(idx_key, "")
        he = heb_lookup.get(idx_key, "")
        he_disp = he.strip() if isinstance(he, str) and he.strip() else "שורה זו לא תורגמה עדיין - אין לפסול אותה בשל כך - אתה בודק רק את התרגום של השורות שקדמו לה"
        return f"{title} — אינדקס {idx_key}:\nמקור_אנגלית:\n{en}\n\nתרגום_עברית:\n{he_disp}\n"

    if not ordered_srt_indices or not chunk_indices:
        lines.append("(הקשר חיצוני לא סופק.)")
        return "\n".join(lines)

    try:
        i0 = ordered_srt_indices.index(chunk_indices[0])
        i1 = ordered_srt_indices.index(chunk_indices[-1])
    except ValueError:
        lines.append("(לא ניתן לפתור שכנים — אינדקס חסר ברשימת הסדר.)")
        return "\n".join(lines)

    prev_idx = ordered_srt_indices[i0 - 1] if i0 > 0 else None
    next_idx = ordered_srt_indices[i1 + 1] if i1 + 1 < len(ordered_srt_indices) else None

    lines.append(fmt_neighbor("שורה אחת לפני תחילת ה-chunk (מידע לפני הבאץ')", prev_idx))
    lines.append(fmt_neighbor("שורה אחת אחרי סוף ה-chunk (מידע אחרי הבאץ')", next_idx))
    return "\n".join(lines)


def call_llm_judge(judge_model_cfg, indices, eng_dict, heb_dict, api_key, ordered_srt_indices,
                   log_func=None, progress_func=None, file_log_func=None, 
                   audit_reason_heb=None, eng_by_index=None, heb_completed_by_index=None, ui_queue=None, judge_batch_size=None, debug_mode=False):
    """
    Calls a second LLM to audit the translation batch.
    Returns: (is_overall_valid, error_map, in, out, cached, reasoning)
    """
    from text_processing import pre_repair_json
    
    if judge_batch_size is not None:
        try:
            chunk_size = int(judge_batch_size)
        except ValueError:
            chunk_size = 20
    else:
        from constants import judge_batch_size as default_judge_batch
        try:
            chunk_size = int(default_judge_batch)
        except ValueError:
            chunk_size = 20

    supports_structured = (judge_model_cfg.get('provider') == 'openai' and 
                          any(m in judge_model_cfg.get('name', '').lower() for m in ["gpt-4o", "gpt-4o-mini", "o1"])) or \
                          (judge_model_cfg.get('provider') == 'lmstudio')

    system_prompt = f"""אתה אודיטור QA חסר רחמים. תפקידך למצוא שגיאות טכניות בתרגום כתוביות (עונה 42 של הישרדות).
נתון לך גם בלוק של כתוביות חופפות לצורך הקשר בלבד - אל תבצע עליו ביקורת!

### חוקי הפסילה (אם אחד מהם מתקיים, עליך לפסול את הבאץ'): ###
1. השמטת טקסט: המקור מכיל מלל (מעל 2 מילים) והתרגום ריק.
2. דליפת שמות (קריטי!): שם דובר נשאר בתרגום (למשל ROCKSROY: או רוקסרוי:).
3. חותמות שמע: תיאורי צליל (למשל: [מוזיקה] או (שיעול)) נשארים בתרגום. **חריג:** דיאלוג בסוגריים (לחישה) הוא תקין.
4. שאריות אנגלית: קיימת אנגלית בתוך התרגום ללא הצדקה.
5. תגיות: חוסר התאמה בתגיות עיצוב (כמו <i>).

### הנחיות קריטיות נגד עצלנות (חובה): ###
- חובה לענות בעברית בלבד! כל הטקסטים שאתה כותב ב-thought_process, ב-summary, ובתיאור השגיאות חייבים להיות מנוסחים בעברית התקנית. הופעת משפטים באנגלית תחשב לכישלון טכני.
- חל איסור מוחלט על שימוש ב-"..."! אתה חייב לכתוב לפחות 2 משפטים מלאים בעברית בכל שדה טקסט.
- אל תשתמש במילים בודדות לתיאור השגיאה. כתוב בדיוק מה הטעות (למשל: "השם ג'ף נשאר בתחילת השורה").
- אם הבאץ' תקין לחלוטין: סמן is_rejected: false.
- אם מצאת ולו טעות אחת זעירה: סמן is_rejected: true.

השב בפורמט ה-JSON Schema המוגדר בלבד."""

    total_in, total_out, total_cached, total_reasoning = 0, 0, 0, 0
    master_error_map = {}
    is_overall_valid = True

    chunks = [indices[i:i + chunk_size] for i in range(0, len(indices), chunk_size)]
    
    if file_log_func:
        file_log_func(f"⛔️ Starting Chunked Audit: {len(chunks)} chunks (Size: {chunk_size} lines per chunk)")
    if log_func:
        log_func(f"   ↳ ⚠️ Judge: Auditing in {len(chunks)} chunk(s) of {chunk_size} lines each...")
    
    heb_lookup = {**(heb_completed_by_index or {}), **heb_dict}
    eng_map = eng_by_index or {}

    for idx, chunk_indices in enumerate(chunks):
        if progress_func:
            progress_func(idx + 1, len(chunks))
        chunk_eng = {k: eng_dict[k] for k in chunk_indices if k in eng_dict}
        chunk_heb = {k: heb_dict[k] for k in chunk_indices if k in heb_dict}
        
        source_str = json.dumps(chunk_eng, ensure_ascii=False, indent=2)
        trans_str = json.dumps(chunk_heb, ensure_ascii=False, indent=2)
        overlap_str = _judge_overlap_block(chunk_indices, ordered_srt_indices, eng_map, heb_lookup)
        if overlap_str:
            overlap_str = f"### [READ ONLY CONTEXT] (REFERENCE ONLY - DO NOT AUDIT THESE LINES) ###\n{overlap_str}\n"

        user_prompt = f"""### AUDIT CHUNK {idx+1}/{len(chunks)} (Blocks: {chunk_indices[0]}-{chunk_indices[-1]}) ###

{overlap_str}

מקור_אנגלית:
{source_str}

תרגום_עברית:
{trans_str}
"""
        # SURGICAL INJECTION: Only show audit reasons relevant to THIS chunk
        if audit_reason_heb:
            relevant_reasons = []
            # Audit reasons are typically separated by '; ' and prefixed with 'IDX:#'
            reasons_list = audit_reason_heb.split("; ")
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
                user_prompt += f"\n### התראת מערכת אוטומטית (Audit): ###\n{reasons_text}\nשים לב: אלגוריתם הבדיקה זיהה את השגיאה הנ\"ל פיזית בתוך שדה התרגום_עברית. קרא את האינדקס המדובר בשדה התרגום שוב בעיון רב כדי לאמת זאת. אל תתעלם מהתראה זו, היא כנראה נכונה!\n"

        user_prompt += "### סוף נתונים ###\n"
        user_prompt += "\nאזהרה אחרונה: פסול את הבאץ' (is_rejected: true) אם אתה רואה את השגיאה במו עיניך בתוך שדה התרגום (תרגום_עברית). אל תפסול אם השגיאה מופיעה אך ורק במקור (מקור_אנגלית).\n"

        judge_schema = {
            "type": "object",
            "properties": {
                "thought_process": {
                    "type": "string",
                    "description": "ניתוח מעמיק בעברית (מינימום 2 משפטים). הסבר בדיוק מה בדקת. אל תשתמש ב-'...'."
                },
                "summary": {
                    "type": "string",
                    "description": "תקציר קצר של העלילה. אל תשתמש ב-'...'."
                },
                "is_rejected": {
                    "type": "boolean",
                    "description": "True אם לפסול (יש שגיאה). False אם הכל תקין."
                },
                "error_map": {
                    "type": "object",
                    "properties": {str(k): {"type": "string", "description": "תיאור השגיאה בעברית (משפט מלא). אם תקין, השאר ריק."} for k in chunk_indices},
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
                    chunk_load += len(str(heb_dict.get(idx_c, "")))
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

            if not raw_res: continue

            # Parse
            parsed = {}
            try:
                parsed = json.loads(pre_repair_json(raw_res))
            except:
                match = RE_FALLBACK_JSON.search(raw_res)
                if match:
                    try: parsed = json.loads(pre_repair_json(match.group(0)))
                    except: continue
                else: continue

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
