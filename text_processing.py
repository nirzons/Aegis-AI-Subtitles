import re
import difflib


import re

def fix_rtl(text):
    if not text: return text
    
    # שלב 0: ניקוי תווי מילוט טקסטואליים שה-LLM נוטה לייצר בתוך JSON
    # אנחנו הופכים אותם לירידות שורה אמיתיות כדי שה-split הבא יזהה אותן
    text = re.sub(r'\s*\\+[nננ]\s*', '\n', str(text))
    
    lines = text.split('\n')
    fixed_lines = []
    for line in lines:
        clean_line = line.strip()
        
        # דילוג על שורות ריקות, אינדקסים או זמנים (למקרה שהפונקציה מקבלת SRT מלא)
        if not clean_line or clean_line.isdigit() or '-->' in clean_line:
            fixed_lines.append(line)
            continue
            
        is_dialogue = clean_line.startswith('-')
        if is_dialogue: clean_line = re.sub(r'^-\s*', '', clean_line)
        
        # טיפול בתגיות HTML (כמו <i>) אם קיימות
        match = re.match(r'^((?:<[^>]+>)*)(.*?)((?:<[^>]+>)*)$', clean_line)
        if match:
            leading_tags, inner_content, trailing_tags = match.group(1), match.group(2).strip(), match.group(3)
        else:
            leading_tags, inner_content, trailing_tags = "", clean_line.strip(), ""
            
        # לוגיקת היפוך פיסוק ל-RTL
        punctuation_search = re.search(r'([.,?!\\\'\":;♪]+)$', inner_content)
        if punctuation_search:
            punctuation = punctuation_search.group(1)
            main_text = inner_content[:-len(punctuation)].strip()
            # הופך את הסדר: הפיסוק עובר להתחלה (בצפייה מימין לשמאל הוא ייראה בסוף)
            inner_content = f"{punctuation}{main_text}"
            
        new_line = f"{leading_tags}{inner_content}{trailing_tags}"
        
        # אם זה דיאלוג, המקף עובר לסוף השורה (שבימין נראה כתחילתה)
        if is_dialogue: new_line = f"{new_line} -"
        
        fixed_lines.append(new_line)
        
    return '\n'.join(fixed_lines)

def strip_music_glyphs_batch(heb_dict):
    """
    1. Removes music note symbols.
    2. Wipes lines that contain only punctuation/notes/SDH artifacts.
    This prevents 'Dangling Hyphen' or 'Music Note Only' Judge rejections.
    """
    if not isinstance(heb_dict, dict):
        return
        
    for k, v in list(heb_dict.items()):
        if isinstance(v, str):
            # First, do the standard character cleaning
            cleaned = v.replace("♪", "").strip()
            
            # Now, apply the 'Empty String' logic:
            # If the resulting string is just a hyphen, a dot, or empty...
            if re.fullmatch(r"[-.\s]*", cleaned):
                heb_dict[k] = ""
            else:
                heb_dict[k] = cleaned

def pre_repair_json(raw_res):
    """נסיון לתיקון שגיאות JSON נפוצות של LLMs באופן מקומי לפני ה-Parsing."""
    if not raw_res: return ""
    cleaned = raw_res.strip()
    
    # הסרת בלוקי קוד ```json ... ```
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
        
    # תיקון פסיק מיותר בסוף מערך או אובייקט (Trailing Comma)
    cleaned = re.sub(r',\s*\}', '}', cleaned)
    cleaned = re.sub(r',\s*\]', ']', cleaned)
    
    # בריחת מילוט שגויה בעברית: נהפוך את הבק-סלאש לליטרלי כדי שה-JSON Parser לא יקרוס.
    # זה מאפשר ללולאת התיקון ב-translation_engine.py (אחרי ה-loads) לזהות, לתקן ולתעד את השגיאה!
    cleaned = re.sub(r'\\+נ', r'\\\\נ', cleaned)
    
    # ניקוי תווים בלתי נראים ו-Control Characters
    cleaned = re.sub(r'[\x00-\x1F\x7F]', '', cleaned)
    
    return cleaned


def check_heuristics(eng_dict, heb_dict, illegal_labels=None):
    """
    בדיקת תקינות מקומית (Heuristics) ללא צורך ב-AI.
    מחזירה (is_suspicious: bool, reason: str, skip_judge: bool).

    skip_judge=True כאשר יש סוגריים מרובעים [ ] בתרגום, או יותר מ-9 מילים בשורת עברית אחת —
    במקרים אלה retry מיידי בלי Judge. דליפת SDH בסוגריים עגולים או ♪ מפעילה את השופט
    כשאין את התנאים לעיל.
    """
    if illegal_labels is None:
        illegal_labels = []
    
    reasons = []
    heb_reasons = []
    has_bracket_sdh = False
    has_overlong_hebrew_line = False
    has_expansion_anomaly = False
    
    total_eng_words = 0
    total_heb_words = 0
    
    for idx, eng_text in eng_dict.items():
        heb_text = str(heb_dict.get(idx, "")).strip()
        
        # 0. שדרוג קריטי: הסרת SDH (סוגריים מרובעים, עגולים ומוזיקה) לפני ספירת המילים
        eng_text_clean = re.sub(r'\[.*?\]|\(.*?\)|♪', '', eng_text)
        
        # Count words for batch density and single-block ratio - עכשיו סופר רק מילים אמיתיות!
        eng_wc = len(re.findall(r'\w+', eng_text_clean))
        heb_wc = len(re.findall(r'\w+', heb_text))
        total_eng_words += eng_wc
        total_heb_words += heb_wc
        
        if eng_wc > 0:
            block_ratio = heb_wc / eng_wc
            if block_ratio > 2.0:
                reasons.append(f"Verbosification at index {idx} ({block_ratio:.1f}x)")
                heb_reasons.append(f"IDX:{idx}|באינדקס {idx} זוהתה חריגה משמעותית באורך התרגום ביחס למקור. דייק את הניסוח כך שיהיה תמציתי כמו באנגלית, והסר כל מידע נוסף שהוספת או הסקת מעבר למה שכתוב במפורש.")
                has_expansion_anomaly = True
            elif block_ratio > 1.5:
                reasons.append(f"High expansion at index {idx} ({block_ratio:.1f}x)")
            elif block_ratio < 0.4 and eng_wc >= 4:
                reasons.append(f"Extreme omission at index {idx} ({block_ratio:.1f}x)")
                heb_reasons.append(f"IDX:{idx}|באינדקס {idx} התרגום קצר ביחס לאורך המקור. ודא שלא הושמט מידע מהותי. אזהרה: אל תתרגם מילולית בראשך! זכור שביטויים באנגלית (כמו 'vote out') מתורגמים לעיתים קרובות למילה אחת בלבד (כמו 'הדחה') בהתאם למילון המונחים. אם הרעיון הכללי נשמר בהצלחה בצורה תמציתית - באחריותך להתעלם מההתרעה ולאשר (true).")

        # 1. בדיקת "דילוג שקט" (Hebrew empty but Eng not)
        # אם אחרי שניקינו את ה-SDH ואת סימני הפיסוק לא נשאר כלום - זה אינדקס SDH טהור
        is_pure_sdh = len(re.sub(r'[-.\s]', '', eng_text_clean)) == 0

        if not heb_text and eng_text.strip():
            if not is_pure_sdh:
                # Flag as 'Silent Skip' ONLY IF the clean source_text contains more than 2 words
                if eng_wc > 2 or len(eng_text_clean.strip()) > 12:
                    reasons.append(f"Silent Skip at index {idx}")
                    heb_reasons.append(f"IDX:{idx}|דילגת על אינדקס {idx} (הוא ריק למרות שיש מלל משמעותי במקור).")

        # 3. בדיקת אורך שורה במילים (9 מילים בדיוק → Judge; יותר מ-9 → retry בלי Judge)
        sub_lines = heb_text.split('\n')
        for line in sub_lines:
            wc = len(line.split())
            if wc == 9:
                reasons.append(f"9-word line at index {idx}")
                heb_reasons.append(f"IDX:{idx}|באינדקס {idx} נמצאה שורה ארוכה (9 מילים). ודא שאין חריגה או הוספת מידע.")
            elif wc > 9:
                reasons.append(f"More than 9 words in a Hebrew line at index {idx}")
                heb_reasons.append(f"IDX:{idx}|מעל ל-9 מילים בעברית באותה השורה באינדקס {idx}")
                has_overlong_hebrew_line = True

        # 4. בדיקת תוכן אסור: שמות דוברים, SDH, אנגלית
        if heb_text:  # Only check content if there IS text
            if re.search(r'[a-zA-Z]', heb_text):
                # Exempt: all-caps acronyms (CNN, CBS), spelled-out letters (S-I-F-U)
                is_exempt = bool(
                    re.fullmatch(r'[A-Z]{2,}', heb_text.strip()) or
                    re.search(r'\b[A-Z]{2,}\b', heb_text) or
                    re.search(r'\b[A-Z](-[A-Z])+\b', heb_text)
                )
                if not is_exempt:
                    reasons.append(f"English letters found in {idx}")
                    heb_reasons.append(f"IDX:{idx}|באינדקס {idx} נמצאו אותיות באנגלית למרות שהתרגום אמור להיות בעברית בלבד.")

            # Refined Speaker Name Check (Checks every line, including dialogue dashes)
            # Looks for: [Optional -] [Name 1-15 chars] :
            speaker_match = re.search(r'(?m)^(?:\s*-\s*)?([^:\n]{1,15}):', heb_text)
            if speaker_match:
                found_name = speaker_match.group(1).strip()
                # Absolute prohibited labels (Dynamic from sysprm)
                if found_name.lower() in [val.lower() for val in illegal_labels]:
                    reasons.append(f"STRICT: Illegal label detected in {idx} ('{found_name}')")
                    heb_reasons.append(f"IDX:{idx}|זיהוי שם מנחה או תווית אסורה ('{found_name}:') באינדקס {idx}. חל איסור מוחלט לכלול שמות דוברים או מנחה בתרגום. מחק זאת מיד!")
                # General name labels
                elif found_name.lower() not in ["הערה", "שים לב", "נ.ב"]:
                    reasons.append(f"Speaker name found in {idx} ('{found_name}')")
                    heb_reasons.append(f"IDX:{idx}|זיהוי שם דובר ('{found_name}:') באינדקס {idx}. חובה למחוק שמות דוברים!")

            if '[' in heb_text or ']' in heb_text:
                reasons.append(f"Square bracket SDH found in {idx}")
                has_bracket_sdh = True
                heb_reasons.append(f"IDX:{idx}|נמצאו סוגריים מרובעים (SDH) באינדקס {idx}. אין לכלול הבעות פנים או צלילי רקע בתרגום.")

            # Flag parentheses/music ONLY if text exists (guards against your empty SDH lines)
            if any(c in heb_text for c in "()♪"):
                reasons.append(f"Parenthesis or music SDH found in {idx}") 
                heb_reasons.append(f"IDX:{idx}|נמצאו סוגריים או סמלי מוזיקה (SDH) באינדקס {idx}.")           

        # 5. בדיקת Robot Talk (AI Filler)
        robot_phrases = ["הנה התרגום", "כאן מופיע", "תרגום:", "הכתובית הבאה"]
        if any(p in heb_text for p in robot_phrases):
            reasons.append(f"Robot talk phrases in {idx}")
            heb_reasons.append(f"IDX:{idx}|נמצאו ביטויי 'Robot Talk' (דיבור רובוטי) באינדקס {idx}.")

        # 6. בדיקת תקינות תגיות (Tag Integrity)
        if heb_text.count('<') != heb_text.count('>') or heb_text.count('<i>') != heb_text.count('</i>'):
            reasons.append(f"Tag mismatch in {idx}")
            heb_reasons.append(f"IDX:{idx}|נמצא חוסר התאמה של תגיות HTML התחלתיות וסוגרות באינדקס {idx}.")
            
        # 7. בדיקת מילים ארוכות מדי (Glitches)
        words = heb_text.split()
        if any(len(w) > 16 for w in words):
            reasons.append(f"Suspiciously long word in {idx}")
            heb_reasons.append(f"IDX:{idx}|נמצאה מילה ארוכה באופן חריג באינדקס {idx}.")

    # 8. בדיקת כפילויות חשודות (Repetition Loops)
    indices = list(eng_dict.keys())
    for i in range(len(indices) - 1):
        idx1, idx2 = indices[i], indices[i+1]
        eng1, eng2 = eng_dict[idx1], eng_dict[idx2]
        heb1, heb2 = str(heb_dict.get(idx1, "")), str(heb_dict.get(idx2, ""))
        if not heb1 or not heb2: continue
        eng_sim = difflib.SequenceMatcher(None, eng1, eng2).ratio()
        heb_sim = difflib.SequenceMatcher(None, heb1, heb2).ratio()
        if heb_sim > 0.85 and eng_sim < 0.4:
            reasons.append(f"Suspicious repetition between {idx1}-{idx2}")
            heb_reasons.append(f"IDX:{idx1},{idx2}|נמצאה חזרתיות חשודה בין אינדקסים {idx1}-{idx2}.")

    # 9. בדיקת יחס מילים כולל לבאץ' (Batch Density)
    # Lower bound: < 0.4 means too much was dropped (likely skipped lines)
    # Upper bound: > 1.6 triggers judge (SDH-heavy batches skew ratio up)
    if total_eng_words > 0 and total_heb_words > 0:
        batch_ratio = total_heb_words / total_eng_words
        if batch_ratio < 0.4 or batch_ratio > 1.6:
            reasons.append(f"Batch Density anomaly ({batch_ratio:.2f})")
            heb_reasons.append(f"GLOBAL|זוהתה חריגה בצפיפות הטקסט הכללית של הבאץ' (יחס תרגום/מקור של {batch_ratio:.2f}).")

    skip_judge = has_bracket_sdh or has_overlong_hebrew_line or has_expansion_anomaly

    if reasons:
        return True, "; ".join(reasons), "; ".join(heb_reasons), skip_judge
    return False, "", "", False
