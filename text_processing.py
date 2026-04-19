import re
import difflib


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

def unfix_rtl(text):
    """
    Undoes 'Visual RTL' logic to restore a 'Logical RTL' string for web browsers.
    Moves punctuation from the start back to the end, and dialogue dashes to the start.
    """
    if not text: return text
    lines = str(text).split('\n')
    unfixed_lines = []
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            unfixed_lines.append(line)
            continue
            
        # Handle dialogue dash (- at the end in Visual mode)
        is_dialogue = clean_line.endswith(' -')
        if is_dialogue:
            clean_line = '-' + clean_line[:-2].strip()
            
        # Handle punctuation (at the start in Visual mode)
        # Note: fix_rtl moved it to the start. We move it back to the end.
        punc_match = re.match(r'^([.,?!\\\'\":;♪]+)', clean_line)
        if punc_match:
            punctuation = punc_match.group(1)
            main_text = clean_line[len(punctuation):].strip()
            clean_line = f"{main_text}{punctuation}"
            
        unfixed_lines.append(clean_line)
    return '\n'.join(unfixed_lines)

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
    """
    נסיון לתיקון שגיאות JSON נפוצות של LLMs באופן מקומי לפני ה-Parsing.
    מטפל ב: בלוקי קוד, פסיקים מיותרים, מפתחות שבורים (ללא נקודתיים), ו-JSON קטוע.
    """
    if not raw_res: return ""
    cleaned = raw_res.strip()
    
    # 1. הסרת בלוקי קוד ```json ... ```
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
        
    # 2. תיקון פסיק מיותר בסוף מערך או אובייקט (Trailing Comma)
    cleaned = re.sub(r',\s*\}', '}', cleaned)
    cleaned = re.sub(r',\s*\]', ']', cleaned)
    
    # 3. תיקון מפתחות שבורים (Missing Colons/Values)
    # מחפש מפתח (מחרוזת) שאחריו מגיע פסיק או סוגר, ללא נקודתיים לפניו.
    # Pattern: (Start of object or comma) + whitespace + "key" + whitespace + (?= comma or end-brace)
    # This specifically fixes: "key", -> "key": null,
    pattern_missing_colon = r'([{,])\s*"([^"\\:]+)"\s*(?=[,}\]])'
    cleaned = re.sub(pattern_missing_colon, r'\1 "\2": null', cleaned)
    
    # 4. טיפול ב-JSON קטוע (Truncated JSON)
    # אם ה-LLM עצר באמצע, ננסה לסגור את הסוגריים כדי שיהיה ניתן לפענח לפחות חלק מהמידע.
    open_braces = cleaned.count('{') - cleaned.count('}')
    open_brackets = cleaned.count('[') - cleaned.count(']')
    
    if open_braces > 0 or open_brackets > 0:
        # אם הקטיעה קרתה באמצע מפתח או ערך (נגמר בגרשיים או פסיק)
        if cleaned.endswith(','):
            cleaned = cleaned.rstrip(',')
        elif cleaned.endswith('"'):
            # אם נגמר בגרשיים, נבדוק אם זה מפתח שבור בסוף ה-JSON הקטוע
            # אם לפני הגרשיים האלה (והגרשיים הפותחות שלהן) יש רצף שנראה כמו התחלה של אובייקט או פסיק
            # ננסה להוסיף : null
            if re.search(r'([{,])\s*"[^"\\:]+"$', cleaned):
                cleaned += ': null'
        
        # סגירת סוגריים בסדר הפוך
        cleaned += ']' * max(0, open_brackets)
        cleaned += '}' * max(0, open_braces)


    # 5. בריחת מילוט שגויה בעברית: נהפוך את הבק-סלאש לליטרלי
    cleaned = re.sub(r'\\+נ', r'\\\\נ', cleaned)
    
    # 6. ניקוי תווים בלתי נראים ו-Control Characters
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
        
        # 0. שדרוג קריטי: הסרת SDH ותגיות לפני ספירת המילים
        # מסיר: [SDH], (SDH), ♪, ותגיות HTML <...>
        eng_text_clean = re.sub(r'\[.*?\]|\(.*?\)|♪|<.*?>', ' ', eng_text)
        heb_text_clean = re.sub(r'\[.*?\]|\(.*?\)|♪|<.*?>', ' ', heb_text)
        
        # Count words for batch density and single-block ratio - עכשיו סופר רק מילים אמיתיות!
        eng_wc = len([w for w in eng_text_clean.split() if any(c.isalnum() for c in w)])
        heb_wc = len([w for w in heb_text_clean.split() if any(c.isalnum() for c in w)])


        total_eng_words += eng_wc
        total_heb_words += heb_wc
        
        if eng_wc > 0:
            # Special case: If single English word > 12 chars, use char ratio instead of word ratio
            if eng_wc == 1 and len(eng_text_clean.strip()) > 12:
                block_ratio = len(heb_text) / len(eng_text_clean.strip())
            else:
                block_ratio = heb_wc / eng_wc
                
            if block_ratio > 2.0:
                reasons.append(f"Verbosification at index {idx} ({block_ratio:.1f}x)")
                heb_reasons.append(f"IDX:{idx}|זוהתה חריגה משמעותית באורך התרגום (Verbosification) ביחס למקור ({block_ratio:.1f}x).")
                has_expansion_anomaly = True
            elif block_ratio > 1.4:
                reasons.append(f"High expansion at index {idx} ({block_ratio:.1f}x)")
                heb_reasons.append(f"IDX:{idx}|התרגום ארוך יחסית למקור (High expansion) ({block_ratio:.1f}x).")
            elif block_ratio < 0.4 and eng_wc >= 4:
                reasons.append(f"Extreme omission at index {idx} ({block_ratio:.1f}x)")
                heb_reasons.append(f"IDX:{idx}|התרגום קצר משמעותית מאורך המקור (Extreme omission) ({block_ratio:.1f}x).")

        # 1. בדיקת "דילוג שקט" (Hebrew empty but Eng not)
        # אם אחרי שניקינו את ה-SDH ואת סימני הפיסוק לא נשאר כלום - זה אינדקס SDH טהור
        is_pure_sdh = len(re.sub(r'[-.\s]', '', eng_text_clean)) == 0

        if not heb_text and eng_text.strip():
            if not is_pure_sdh:
                # Flag as 'Silent Skip' ONLY IF the clean source_text contains more than 2 words
                if eng_wc > 2 or len(eng_text_clean.strip()) > 12:
                    reasons.append(f"Silent Skip at index {idx}")
                    heb_reasons.append(f"IDX:{idx}|זוהה דילוג שקט (Silent Skip) - האינדקס ריק למרות שקיים מלל בתרגום.")

        # 3. בדיקת אורך שורה במילים (9 מילים בדיוק → Judge; יותר מ-9 → retry בלי Judge)
        sub_lines = heb_text.split('\n')
        for line in sub_lines:
            # Smart word count: ignore standalone symbols like '-' or '♪'
            words = [w for w in line.split() if any(c.isalnum() for c in w)]
            wc = len(words)
            if wc == 9:
                reasons.append(f"9-word line at index {idx}")
                heb_reasons.append(f"IDX:{idx}|נמצאה שורה המכילה בדיוק 9 מילים. ודא שאין חריגה או הוספת מידע.")
            elif wc > 9:
                reasons.append(f"More than 9 words in a Hebrew line at index {idx}")
                heb_reasons.append(f"IDX:{idx}|נמצאה שורה ארוכה מדי (מעל 9 מילים).")
                has_overlong_hebrew_line = True

        # 4. בדיקת תוכן אסור: שמות דוברים, SDH, אנגלית, תווים זרים
        if heb_text:  # Only check content if there IS text
            
            # בדיקת תווים זרים (כמו סינית, רוסית וכו') - משתמש בטקסט הנקי מתגיות
            foreign_chars = re.findall(r'[^\x00-\x7F\u0590-\u05FF\u200E\u200F\u202A-\u202C\u2018-\u201D\u2026\u2013\u2014\u20AA\u20AC\u00A3\xA0\xB0♪♫]', heb_text_clean)
            if foreign_chars:
                reasons.append(f"STRICT: Foreign characters found in {idx} ({''.join(set(foreign_chars))})")
                heb_reasons.append(f"IDX:{idx}|נמצאו תווים זרים או סמלים לא מוכרים ({''.join(set(foreign_chars))}).")
            
            found_eng = re.findall(r'[a-zA-Z]+', heb_text_clean)
            if found_eng:
                # Exempt: all-caps acronyms (CNN, CBS), spelled-out letters (S-I-F-U)
                actual_errors = []
                for word in found_eng:
                    is_exempt = bool(
                        re.fullmatch(r'[A-Z]{2,}', word) or
                        re.search(r'\b[A-Z](-[A-Z])+\b', word)
                    )
                    if not is_exempt:
                        actual_errors.append(word)
                
                if actual_errors:
                    err_str = ", ".join(set(actual_errors))
                    reasons.append(f"STRICT: English letters found in {idx} ({err_str})")
                    heb_reasons.append(f"IDX:{idx}|באינדקס {idx} נמצאו מילים באנגלית ({err_str}). חובה לתרגם לעברית או למחוק!")


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
            
        # 7. בדיקת מילים ארוכות מדי (Glitches) - משתמש בטקסט הנקי מתגיות
        words = heb_text_clean.split()
        if any(len(w) > 16 for w in words):
            reasons.append(f"Suspiciously long word in {idx}")
            heb_reasons.append(f"IDX:{idx}|נמצאה מילה ארוכה באופן חריג באינדקס {idx}.")


    # 8. בדיקת כפילות תוכן בין כתוביות סמוכות (Semantic Echo)
    # מחפש מקרים בהם סוף כתובית אחת חוזר בתחילת הכתובית הבאה (הזיה נפוצה של LLM)
    indices = sorted(eng_dict.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
    for i in range(len(indices) - 1):
        idx1, idx2 = indices[i], indices[i+1]
        h1 = str(heb_dict.get(idx1, "")).strip().split('\n')
        h2 = str(heb_dict.get(idx2, "")).strip().split('\n')
        
        if h1 and h2:
            # ניקוי השורה האחרונה של 1 והראשונה של 2 להשוואה (ללא סימני פיסוק וסמלים)
            last_line = re.sub(r'[.,!?:;♪\-_]+', '', h1[-1]).strip()
            first_line = re.sub(r'[.,!?:;♪\-_]+', '', h2[0]).strip()
            
            # בדיקת כפילות של ביטוי משמעותי (3 מילים ומעלה)
            wc_last = len([w for w in last_line.split() if any(c.isalnum() for c in w)])
            if last_line == first_line and wc_last >= 3:
                # בדיקה האם הכפילות קיימת גם במקור (למשל דיאלוג "- כן. - כן.")
                e1 = str(eng_dict.get(idx1, "")).strip().lower().split('\n')
                e2 = str(eng_dict.get(idx2, "")).strip().lower().split('\n')
                
                e_repeated = False
                if e1 and e2:
                    e_last = re.sub(r'[.,!?:;♪\-_]+', '', e1[-1]).strip()
                    e_first = re.sub(r'[.,!?:;♪\-_]+', '', e2[0]).strip()
                    if e_last == e_first and len(e_last.split()) >= 2:
                        e_repeated = True
                
                if not e_repeated:
                    reasons.append(f"Semantic Echo between {idx1} and {idx2}")
                    heb_reasons.append(f"IDX:{idx1},{idx2}|זוהתה כפילות תוכן חריגה (Echo) בין כתוביות סמוכות. ודא שהמידע אינו חוזר על עצמו בטעות.")

    # 9. בדיקת יחס מילים כולל לבאץ' (Batch Density)
    if total_eng_words > 0:
        batch_ratio = total_heb_words / total_eng_words
        if batch_ratio < 0.4 or batch_ratio > 1.3:
            reasons.append(f"Batch Density anomaly ({batch_ratio:.2f}x)")
            heb_reasons.append(f"GLOBAL|נפח התרגום הכולל בבאץ' חורג מהנורמה ({batch_ratio:.2f}x).")

    skip_judge = has_bracket_sdh or has_overlong_hebrew_line or has_expansion_anomaly or any("STRICT:" in r for r in reasons)

    if reasons:
        return True, "; ".join(reasons), "; ".join(heb_reasons), skip_judge
    return False, "", "", False


def force_split_overlong_line(text):
    """
    Programmatically splits a Hebrew subtitle string into two lines 
    by inserting a \n at the linguistic midpoint. Used as a fallback 
    for 'stubborn' LLM responses during minimal batch retries.
    """
    if not text:
        return text
        
    # Standard splitting into tokens
    tokens = text.split()
    word_indices = []
    
    for i, token in enumerate(tokens):
        # A 'word' matches the auditor logic: must contain at least one alphanumeric char
        if any(c.isalnum() for c in token):
            word_indices.append(i)
            
    total_words = len(word_indices)
    
    # Safety: don't split if it's already tight (though this should only be called if wc > 8)
    if total_words <= 8:
        return text
        
    # Select the word index that represents the best middle boundary
    mid_point = total_words // 2
    split_token_idx = word_indices[mid_point - 1]
    
    # Reassemble tokens with a newline at the selected boundary
    part1 = " ".join(tokens[:split_token_idx + 1])
    part2 = " ".join(tokens[split_token_idx + 1:])
    
    return f"{part1}\n{part2}"
