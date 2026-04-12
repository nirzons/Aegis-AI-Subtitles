import os
import platform
import subprocess
import json
import re

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


def call_llm(model_cfg, system_prompt, user_prompt, api_key):
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
                "temperature": current_temp,
                "response_format": {"type": "json_object"}
            }
            
        response = client.chat.completions.create(**req_params)
        
        raw_content = response.choices[0].message.content
        # Strip markdown if model added it
        if "```json" in raw_content:
            raw_content = raw_content.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_content:
            raw_content = raw_content.split("```")[1].split("```")[0].strip()

        # Robust extraction for OpenAI/GPT-5 caching
        cached_tokens = 0
        usage = getattr(response, 'usage', None)
        if usage:
            # Check prompt_tokens_details.cached_tokens (standard for o1/gpt-4o)
            details = getattr(usage, 'prompt_tokens_details', None)
            if details:
                cached_tokens = getattr(details, 'cached_tokens', 0) or 0
        
        return raw_content, response.usage.prompt_tokens, response.usage.completion_tokens, cached_tokens

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
        if not cached_tokens and getattr(response.usage, 'prompt_tokens_details', None):
            cached_tokens = getattr(response.usage.prompt_tokens_details, 'cached_tokens', 0) or 0
        return response.choices[0].message.content, response.usage.prompt_tokens, response.usage.completion_tokens, cached_tokens
    
    elif model_cfg['provider'] == 'lmstudio':
        client = OpenAI(api_key=api_key, base_url="http://localhost:1234/v1", timeout=3600.0)
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
        return response.choices[0].message.content, response.usage.prompt_tokens, response.usage.completion_tokens, 0


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
        return f"{title} — אינדקס {idx_key}:\nENGLISH:\n{en}\n\nHEBREW:\n{he_disp}\n"

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


def call_llm_judge(
    judge_model_cfg,
    indices,
    eng_dict,
    heb_dict,
    api_key,
    judge_batch_size=20,
    ordered_srt_indices=None,
    eng_by_index=None,
    heb_completed_by_index=None,
    log_func=None,
    file_log_func=None,
    audit_reason_heb=None,
):
    """Audits a suspicious translation using an AI Judge in chunks."""
    if not api_key:
        return True, "No API Key", 0, 0, 0
    
    try:
        chunk_size = int(judge_batch_size)
    except ValueError:
        chunk_size = 20

    system_prompt = """
אתה אודיטור QA דטרמיניסטי. תפקידך להשוות מילוני תרגום (מקור מול תוצאה) על בסיס חוקים בינאריים בלבד.
נתון לך גם CONTEXTUAL OVERLAP: שורת מקור/תרגום אחת לפני ואחת אחרי הבאץ' הנבדק — לצורך הקשר בלבד.
החזר אך ורק JSON חוקי במבנה הבא:
{
  "thought_process": "בחר את האינדקס הכי חשוד. השווה מקור לתרגום. אם נראית השמטה או עיוות, בדוק בהקשר ה-OVERLAP (לפני/אחרי) אם המידע 'זלג' לכתובית סמוכה. אם המשמעות הכוללת של הבאץ' יחד עם ההקשר נשמרת — סמן valid. אם יש שינוי משמעות מהותי, סתירה לוגית, או המצאה — פסול.",
  "is_valid": true,
  "error_map": { 
    "103": "אם false, ציין עבור כל אינדקס רלוונטי את השגיאה (מפתח: אינדקס, ערך: סיבה). אם true, השאר ריק או חסר."
  }
}
"""
    total_in, total_out, total_cached = 0, 0, 0
    master_error_map = {}
    is_overall_valid = True

    # Split indices into chunks
    chunks = [indices[i:i + chunk_size] for i in range(0, len(indices), chunk_size)]
    
    if file_log_func:
        file_log_func(f"⛔️ Starting Chunked Audit: {len(chunks)} chunks (Size: {chunk_size} lines per chunk)")
    if log_func:
        log_func(f"   ↳ ⚠️ Judge: Auditing in {len(chunks)} chunk(s) of {chunk_size} lines each...")
    
    heb_lookup = {**(heb_completed_by_index or {}), **heb_dict}
    eng_map = eng_by_index or {}

    for idx, chunk_indices in enumerate(chunks):
        chunk_eng = {k: eng_dict[k] for k in chunk_indices if k in eng_dict}
        chunk_heb = {k: heb_dict[k] for k in chunk_indices if k in heb_dict}
        
        source_str = json.dumps(chunk_eng, ensure_ascii=False, indent=2)
        trans_str = json.dumps(chunk_heb, ensure_ascii=False, indent=2)
        overlap_str = _judge_overlap_block(chunk_indices, ordered_srt_indices, eng_map, heb_lookup)

        user_prompt = f"""### AUDIT CHUNK {idx+1}/{len(chunks)} (Blocks: {chunk_indices[0]}-{chunk_indices[-1]}) ###

SOURCE (ENGLISH):
{source_str}

TRANSLATED (HEBREW):
{trans_str}

{overlap_str}
"""
        if audit_reason_heb:
            chunk_reasons = []
            for item in audit_reason_heb.split("; "):
                parts = item.split("|", 1)
                if len(parts) == 2:
                    scope, msg = parts[0], parts[1]
                    if scope == "GLOBAL":
                        chunk_reasons.append(("GLOBAL", msg))
                    elif scope.startswith("IDX:"):
                        idx_list = scope[4:].split(",")
                        if any(str(i) in [str(c) for c in chunk_indices] for i in idx_list):
                            # Try to extract index from scope for specific instruction
                            msg_idx = idx_list[0] if idx_list else "?"
                            chunk_reasons.append((msg_idx, msg))
                else:
                    chunk_reasons.append(("?", item))
            
            if chunk_reasons:
                formatted_reasons = []
                has_custom = False
                for msg_idx, msg in chunk_reasons:
                    if "זיהוי שם דובר" in msg or "זיהוי שם מנחה" in msg:
                        has_custom = True
                        is_host = "זיהוי שם מנחה" in msg
                        # Extract the name from the message if possible (format: 'name:')
                        name_match = re.search(r"'(.*?)'", msg)
                        found_name = name_match.group(1).strip(":") if name_match else "המילה החשודה"
                        
                        if is_host:
                            custom_msg = f"""### הופעלה התרעת מערכת חמורה: ###
המערכת הטכנית זיהתה בוודאות שם מנחה/דובר ('{found_name}:') באינדקס {msg_idx}. 
**משימתך:** חובה עליך לפסול (false) לפי חוק 3. אל תשאיר שמות דוברים או מנחה בתרגום הסופי! השם "{found_name}:" חייב להימחק."""
                        else:
                            custom_msg = f"""### הופעלה התרעת מערכת אוטומטית: ###
המערכת הטכנית זיהתה חשד לשם דובר באינדקס {msg_idx}: ('{found_name}:').
**משימתך:** בדוק בהקשר. האם "{found_name}" הוא באמת שם של דמות המדברת בתוכנית (ואז עליך לפסול לפי חוק 3)? או שמדובר בחלק אינטגרלי מהטקסט המדובר עצמו (למשל, קריין מכריז, מונח רגיל)? אם זה חלק מהטקסט ולא שם של דובר – **התעלם מההתרעה ואשר (true)**."""
                        formatted_reasons.append(custom_msg)
                    else:
                        formatted_reasons.append(msg)
                
                if has_custom:
                    reasons_text = "\n\n".join(formatted_reasons)
                    user_prompt += f"\n{reasons_text}\n\n"
                else:
                    # Previous behavior for standard reasons
                    reasons_text = "\n".join(formatted_reasons)
                    user_prompt += f"\n### אתה הופעלת בגלל הבעיה הבאה שהתגלתה: ###\n{reasons_text}\n\n"

        user_prompt += """### DETERMINISTIC AUDIT RULES (Fail/false IF ANY APPLY) ###
1. OMISSION: פסול (false) אם ערך TRANSLATED הוא ריק ("") למרות שהמקור מכיל מלל מדובר. **חריג זליגה**: מותר שהתרגום יהיה ריק אם המקור מכיל עד 2 מילים בלבד והמשמעות שלהן הוטמעה בכתובית סמוכה. **חריג קריטי**: כל טקסט שמוקף כולו בסוגריים מרובעים או עגולים (למשל [exclaims], [laughs], (sigh)) מוגדר כאפקט קולי (SDH) ולא כדיאלוג! כמו כן, תווים מוזיקליים (♪). עבור כל אלה, הערך בתרגום חייב להיות מחרוזת ריקה (""). לעולם אל תפסול שורה ריקה אם הטקסט במקור היה עטוף בסוגריים!
2. DUPLICATION: ערך TRANSLATED זהה לחלוטין לערך TRANSLATED קודם באותו באץ', בעוד שה-SOURCE המקביל שלהם שונה מהותית.
3. LEAKAGE (דליפה): פסול (false) אם נשאר בתוך הטקסט העברי שם של דובר ואחריו נקודתיים (למשל "SIFU:" או "אמילי:" או "ג'ף:"). חובה למחוק שמות דוברים המופיעים כתגית זיהוי בתחילת השורה! **אזהרה קריטית**: שמות המופיעים כחלק מהדיאלוג (למשל "היי ג'ף, מה קורה?") הם תקינים לחלוטין ואסור למחוק אותם. הפסילה היא אך ורק על תגיות זיהוי (Speaker Labels) המלוות בנקודתיים. אם השם מופיע ללא נקודתיים כחלק מהמשפט - אשר (true).
4. ENGLISH: קיימות אותיות באנגלית ב-TRANSLATED. התעלם (אל תפסול) אם מדובר בשם מותג מובהק, ראשי תיבות, איות של מילה (כמו S-I-F-U) או אותיות בודדות המשמשות לתיאור צורה/סמל (כמו האות I, צורת V או הסימון X). אם האות האנגלית נמצאת שם מסיבה לוגית ומוצדקת זו - החזר true.
5. SEMANTIC FIDELITY, IDIOMS & ALLOWED DRIFT (תוכן, ניבים וזליגה): **פסול (false) רק אם** יש שינוי משמעות **מהותי**, סתירה לוגית למקור, המצאה (Hallucination), או השמטת מונח מפתח שלא מופיע בשום אינדקס סמוך ב-OVERLAP ובגוף הבאץ' הנבדק. **תרגום ביטויים (Idioms): אל תדרוש תרגום מילולי (Word-for-Word). אשר תרגומים שמעבירים את הכוונה והרוח של המקור בצורה טבעית לעברית.** **השמטות זניחות (Micro-Omissions): אל תפסול על מילים קטנות, מילות קישור, או ביטויי סלנג ותוספות (כמו "in there", "just", "like") שלא תורגמו מילולית, כל עוד הרעיון המרכזי הועבר.** **זליגה מותרת (Shifting):** העברת ניסוח בין אינדקסים **סמוכים** לטובת עברית טבעית — **מותרת** אם **מסת הקול** נשמרת ביחד עם ה-OVERLAP. **לפני פסילה על «השמטה»:** וודא שהחומר «החסר» לא מופיע בתרגום האינדקס **הקודם או הבא** (כולל שורות OVERLAP). **שיוך שגיאות מדויק (קריטי):** אם מצאת שגיאה, **חובה לשייך אותה אך ורק לאינדקס המקורי שבו מופיע הטקסט המקביל באנגלית**. לעולם אל תדווח על שגיאה באינדקס הקודם או הבא. **ספק לטובת המתרגם:** אם חוקים **1–4** מתקיימים והמשמעות הכללית נשמרת עם ה-OVERLAP — **אשר (true)**.
6. GENDER (מגדר): פער במגדר הדובר (למשל, תרגום "Sorry" כ"מצטערת" במקום "מצטער" או להפך) **אינו** עילה לפסילה (החזר true). קבל כל הטיה מגדרית כתקינה לחלוטין. מותר לך לפסול על שגיאת מגדר (false) **רק** אם המגדר מצוין במפורש בכינויי גוף בתוך הטקסט הנבדק עצמו (לדוגמה: המקור אומר "He said" ותורגם כ-"היא אמרה").

אזהרה חמורה: אל תדמיין שגיאות! לפני שאתה קובע 'false' בגלל מילה או תגית, ודא שהיא אכן מודפסת פיזית בתוך הערך של ה-TRANSLATED. חוקים 5 ו-6 **אינם** דוחים חוקים 1–4.
"""
        try:
            if log_func:
                log_func(f"   ↳ ⏳ Judge Chunk {idx+1}/{len(chunks)} [{chunk_indices[0]}–{chunk_indices[-1]}]: sending...")
            if file_log_func:
                file_log_func(f"--- JUDGE CHUNK {idx+1} SYSTEM PROMPT START ---\n{system_prompt}\n--- JUDGE CHUNK {idx+1} SYSTEM PROMPT END ---")
                file_log_func(f"--- JUDGE CHUNK {idx+1} USER PROMPT START ---\n{user_prompt}\n--- JUDGE CHUNK {idx+1} USER PROMPT END ---")
            
            raw_res, in_tokens, out_tokens, cached_tokens = call_llm(judge_model_cfg, system_prompt, user_prompt, api_key)
            
            if file_log_func:
                file_log_func(f"--- JUDGE CHUNK {idx+1} RAW RESPONSE START ---\n{raw_res}\n--- JUDGE CHUNK {idx+1} RAW RESPONSE END ---")
            
            total_in += in_tokens
            total_out += out_tokens
            total_cached += cached_tokens
            
            cleaned = pre_repair_json(raw_res)
            res_data = json.loads(cleaned)
            
            j_discount = judge_model_cfg.get('cache_discount', 0.0)
            hit_str = ""
            if j_discount > 0 and in_tokens > 0:
                hit_pct = (cached_tokens / in_tokens * 100)
                hit_str = f" [Hit: {cached_tokens:,} ({hit_pct:.1f}%)]"

            if not res_data.get("is_valid", True):
                is_overall_valid = False
                err_map = res_data.get("error_map", {})
                if not err_map:
                    # fallback if model ignores schema
                    reason = res_data.get("reason", "Unknown Audit Failure")
                    master_error_map[f"chunk_{idx+1}_general"] = f"[Chunk {idx+1}] {reason}"
                    if log_func:
                        log_func(f"   ↳ ❌ Judge Chunk {idx+1}/{len(chunks)}: FAIL (In:{in_tokens:,}{hit_str} / Out:{out_tokens:,}) — {reason}")
                else:
                    master_error_map.update(err_map)
                    if log_func:
                        err_summary = "; ".join([f"{k}: {v}" for k, v in err_map.items()])
                        log_func(f"   ↳ ❌ Judge Chunk {idx+1}/{len(chunks)}: FAIL (In:{in_tokens:,}{hit_str} / Out:{out_tokens:,}) — {err_summary}")
                return False, master_error_map, total_in, total_out, total_cached
            else:
                if log_func:
                    log_func(f"   ↳ ✅ Judge Chunk {idx+1}/{len(chunks)}: PASS (In:{in_tokens:,}{hit_str} / Out:{out_tokens:,})")

        except Exception as e:
            is_overall_valid = False
            master_error_map[f"chunk_{idx+1}_error"] = f"Judge Error in Chunk {idx+1}: {e}"
            if log_func:
                log_func(f"   ↳ ⚠️ Judge Chunk {idx+1}/{len(chunks)}: ERROR — {e}")

    if not is_overall_valid:
        return False, master_error_map, total_in, total_out, total_cached
    return True, {}, total_in, total_out, total_cached
