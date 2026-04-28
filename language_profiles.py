from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional

RTL_LANGUAGES = {"he", "ar", "fa", "ur", "yi", "ckb", "syc", "dv"}

@dataclass
class LanguageProfile:
    source_lang_code: str
    target_lang_code: str
    source_lang: str = "Unknown"
    target_lang: str = "Unknown"
    target_is_rtl: bool = False
    target_script: str = "latin"
    target_unicode_ranges: list[Tuple[int, int]] = field(default_factory=lambda: [(0x0000, 0x024F)])
    max_words_per_line: int = 8
    
    word_ratio_vs_english: float = 1.0
    use_char_ratio: bool = False
    direct_pair_ratios: Dict[str, Tuple[float, float, float, float]] = field(default_factory=dict)
    
    native_meta_instructions: Optional[str] = None
    use_native_instructions: bool = False
    gender_tracking: bool = True
    
    native_unknown_speaker: str = "Unknown"
    native_setting_label: str = "Unknown"
    native_opening_summary: str = "The episode just started."
    native_label_prev_context: str = "Previous Context"
    native_label_translation_blocks: str = "Translation Blocks - JSON"
    native_label_next_context: str = "Next Context"

    @property
    def default_unknown_speaker(self) -> str:
        return self.native_unknown_speaker if self.use_native_instructions else "Unknown"

    @property
    def default_setting_label(self) -> str:
        return self.native_setting_label if self.use_native_instructions else "Unknown"

    @property
    def default_opening_summary(self) -> str:
        return self.native_opening_summary if self.use_native_instructions else "The episode just started."

    @property
    def label_prev_context(self) -> str:
        return self.native_label_prev_context if self.use_native_instructions else "Previous Context"

    @property
    def label_translation_blocks(self) -> str:
        return self.native_label_translation_blocks if self.use_native_instructions else "Translation Blocks - JSON"

    @property
    def label_next_context(self) -> str:
        return self.native_label_next_context if self.use_native_instructions else "Next Context"
        
    @property
    def label_do_not_translate(self) -> str:
        return self.native_do_not_translate_label if self.use_native_instructions else "DO NOT TRANSLATE"
        
    @property
    def overlong_word(self) -> str:
        return self.native_overlong_word if self.use_native_instructions else "words"
        
    @property
    def overlong_phrase(self) -> str:
        return self.native_overlong_phrase if self.use_native_instructions else "too long"
        
    @property
    def newline_regex(self) -> str:
        return self.native_newline_regex if self.use_native_instructions else r'\s*\\+[n]\s*'
    
    native_audit_messages: Dict[str, str] = field(default_factory=dict)
    native_json_schema: Optional[str] = None
    native_json_schema_lite: Optional[str] = None
    native_workflow_steps: Optional[Dict[str, str]] = None
    native_technical_rules: Optional[str] = None
    native_judge_prompt: Optional[str] = None
    
    native_user_prompt_prefix: Optional[str] = None
    native_special_instructions_header: Optional[str] = None
    native_technical_rules_header: Optional[str] = None
    native_exact_count_rule: Optional[str] = None
    native_exact_indices_rule: Optional[str] = None
    native_do_not_translate_rule: Optional[str] = None
    native_tag_rule: Optional[str] = None
    native_do_not_translate_label: str = "DO NOT TRANSLATE"
    native_missing_translation_label: str = "Missing Translation"
    native_schema_descriptions: Dict[str, str] = field(default_factory=dict)
    native_judge_strings: Dict[str, str] = field(default_factory=dict)
    native_index_label: str = "Index"
    native_feedback_header: str = "### YOU MUST FIX THE FOLLOWING ERRORS BY INDEX (DO NOT REPEAT THESE MISTAKES): ###"
    native_last_line_label: str = "Last translated line (from previous batch): '{last_line}'"
    native_continuity_note_label: str = "⚠️ Continuity note from previous batch (Attention!): {note}"
    native_story_context_header: str = "### Story Context (Previous Batches) ###"
    native_current_setting_label: str = "Current Setting: {setting}"
    native_plot_summary_label: str = "Plot Summary: {summary}"
    native_last_speaker_label: str = "Last Speaker (previous batch): {speaker}"
    native_schema_mandatory_label: str = "### MANDATORY: Respond EXACTLY in the specified JSON Schema format. ###"
    native_placeholder_indicators: list[str] = field(default_factory=list)
    native_robot_phrases: list[str] = field(default_factory=list)
    native_exempt_labels: list[str] = field(default_factory=list)
    native_repair_note_ghost: str = "Auto-repair applied to remove source language ghost fragments. Verify the sentence flows naturally."
    native_repair_note_newline: str = "Auto-repair applied to line format (\\n)."
    native_stubborn_split_log: str = "💡 Stubborn model detected. Applying programmatic split for index {idx}."
    native_stubborn_resolved_log: str = "✅ Programmatic split resolved the issue. Proceeding..."
    native_intervention_header: str = "####### MANUAL INTERVENTION REQUIRED #######"
    native_intervention_instructions: list[str] = field(default_factory=lambda: [
        "1. Edit the translation to the best of your ability.",
        "2. Save the file (Ctrl+S).",
        "3. Close the editor to continue."
    ])
    native_intervention_source_label: str = "SOURCE ENGLISH LINES"
    native_intervention_target_label: str = "TRANSLATED LINES REQUIRING FIX"
    native_intervention_edit_warning: str = "Do not change the index numbers, only the translation text."
    native_intervention_max_words_warning: str = "Try to ensure no more than {max_words} words per line."
    native_intervention_error_label: str = "The errors identified in these lines are:"
    native_overlong_word: str = "words"
    native_overlong_phrase: str = "too long"
    native_newline_regex: str = r'\s*\\+[n]\s*'

    def get_ratios(self, source_code: str) -> Tuple[float, float, float, float]:
        """
        Returns the (MinBlock, MaxBlock, MinBatch, MaxBatch) word ratios for a pair.
        Prioritizes direct_pair_ratios, then scales global defaults by the expansion factor.
        """
        if source_code in self.direct_pair_ratios:
            return self.direct_pair_ratios[source_code]
        
        # Fallback logic: Scale standard ratios by the language's expansion factor.
        # Base English -> Hebrew style ratios: (0.4, 3.0, 0.45, 1.3)
        base = self.word_ratio_vs_english
        return (0.4 * base, 3.0 * base, 0.45 * base, 1.3 * base)

    @property
    def target_uses_latin_script(self) -> bool:
        return self.target_script == "latin"

    def build_allowed_charset(self):
        import re
        # Build regex to match characters OUTSIDE the allowed script range,
        # ignoring basic ascii punctuation/numbers and universal whitespace.
        # Characters we WANT to allow:
        # \x00-\x7F (Basic ASCII - covers numbers, english letters, basic punct)
        # \u2000-\u206F (General punctuation, directionality marks)
        # The target block itself.
        
        if self.target_script == "latin":
            # For Latin targets, we basically allow the entire Latin blocks.
            # So anything NOT in these blocks is foreign.
            pattern = rf'[^\x00-\x7F\u0080-\u024F\u2000-\u206F]'
        else:
            # For non-Latin targets (Hebrew, Arabic, CJK, etc.)
            # Allow basic ASCII EXCEPT A-Za-z. 
            # Basic ASCII without letters: \x00-\x40, \x5B-\x60, \x7B-\x7F
            # Allow target ranges.
            # Allow general punctuation.
            
            range_strs = []
            for start, end in self.target_unicode_ranges:
                range_strs.append(f"\\u{start:04X}-\\u{end:04X}")
            
            ranges_combined = "".join(range_strs)
            
            # The negated class matches anything NOT in these ranges.
            # So if it finds A-Za-z, it WILL match it as foreign, which is what we want!
            pattern = rf'[^\x00-\x40\x5B-\x60\x7B-\x7F{ranges_combined}\u2000-\u206F]'
            
        return re.compile(pattern)

BUILT_IN_PROFILES = {
    "en": {"name": "English", "ratio": 1.0, "script": "latin", "unicode": [(0x0000, 0x024F)]},
    "he": {
        "name": "Hebrew",
        "rtl": True,
        "script": "hebrew",
        "unicode": [(0x0590, 0x05FF)],
        "max_words": 8,
        "ratio": 0.75,
        "direct_pairs": {"en": (0.35, 3.0, 0.40, 1.30), "fr": (0.28, 2.5, 0.32, 1.10)},
        "unknown_speaker": "לא ידוע",
        "setting_label": "לא ידוע",
        "opening_summary": "הפרק רק התחיל.",
        "label_prev_context": "הקשר קודם",
        "label_translation_blocks": "בלוקים לתרגום - JSON",
        "label_next_context": "הקשר הבא",
        "native_json_schema": """{
  "thought_process": "<הכנס כאן את תהליך המחשבה שלך>",
  "summary": "<תקציר קצר של המתרחש בעלילה כרגע>",
  "continuous_translation_draft": "<הכנס כאן את כל התרגום כפסקת טקסט רציפה אחת>",
  "mapping_plan": "<הכנס כאן את תוכנית המיפוי מול חלוקת האינדקסים. לדוגמה: 'משפט 1 ל-14'>",
  "translated_srt": {
    "1": "<התרגום הסופי לעברית של אינדקס 1 הרלוונטי לבאץ'>",
    "2": "<התרגום הסופי לעברית של אינדקס 2 הרלוונטי לבאץ'>"
  },
  "last_speaker_info": "<שם הדובר (M/F) פונה אל יעד (M/F/לא ידוע/מצלמה)>",
  "continuity_note": "<הוראת רצף לבאץ' הבא, השאר ריק אם אין>"
}""",
        "native_json_schema_lite": """{
  "thought_process": "...",
  "summary": "<תקציר קצר של המתרחש בעלילה כרגע>",
  "translated_srt": {
    "1": "<התרגום הסופי לעברית של אינדקס 1 הרלוונטי לבאץ'>",
    "2": "<התרגום הסופי לעברית של אינדקס 2 הרלוונטי לבאץ'>"
  },
  "last_speaker_info": "<שם הדובר (M/F) פונה אל יעד (M/F/לא ידוע/מצלמה)>",
  "continuity_note": "<הוראת רצף לבאץ' הבא, השאר ריק אם אין>"
}""",
        "native_audit_messages": {
            "pre_speaker_name": "חשד לשם דובר ('{found_name}:'). מחק את השם, אך וודא שהדיאלוג המדובר עדיין מתורגם!",
            "pre_sdh_brackets": "חשד לתיאור צליל/SDH ({content}). אם מדובר בתיאור סאונד, מחק אותו אך תרגם כל דיאלוג אחר המופיע בשורה.",
            "pre_tag_mismatch": "זוהה חוסר התאמה בתגיות במקור האנגלי. זה עלול לגרום לשגיאות תרגום או פסילה ע\"י השופט. מומלץ לתקן את קובץ המקור.",
            "pre_music_symbol": "נמצא סמל מוזיקה ♪. מחק אותו מהתרגום.",
            "heur_verbosification": "IDX:{idx}|זוהתה חריגה משמעותית באורך התרגום (Verbosification) ביחס למקור ({block_ratio:.1f}x).",
            "heur_high_expansion": "IDX:{idx}|התרגום ארוך יחסית למקור (High expansion) ({block_ratio:.1f}x).",
            "heur_extreme_omission": "IDX:{idx}|חשד להשמטת טקסט - התרגום קצר משמעותית מהמקור ({block_ratio:.1f}x). ודא שלא הושמט מידע עלילתי. זכור: עברית מטבעה דחוסה יותר מאנגלית (מילות יחס כמו in/to/that הופכות לקידומות ב/ל/ש) לכן יחס נמוך הוא לרוב תקין לחלוטין.",
            "heur_silent_skip": "IDX:{idx}|זוהה דילוג שקט (Silent Skip) - האינדקס ריק למרות שקיים מלל בתרגום.",
            "heur_exact_word_match": "IDX:{idx}|נמצאה שורה המכילה בדיוק {wc} מילים. ודא שאין חריגה או הוספת מידע.",
            "heur_line_too_long": "IDX:{idx}|נמצאה שורה ארוכה מדי (מעל {max_words_plus_1} מילים).",
            "heur_foreign_chars": "IDX:{idx}|נמצאו תווים זרים או סמלים לא מוכרים ({chars}).",
            "heur_source_lang_words": "IDX:{idx}|באינדקס {idx} נמצאו מילים משפת המקור ({err_str}). חובה לתרגם או למחוק!",
            "heur_illegal_label": "IDX:{idx}|זיהוי שם מנחה או תווית אסורה ('{found_name}:') באינדקס {idx}. חל איסור מוחלט לכלול שמות דוברים או מנחה בתרגום. מחק זאת מיד!",
            "heur_speaker_name": "IDX:{idx}|זיהוי שם דובר ('{found_name}:') באינדקס {idx}. חובה למחוק שמות דוברים!",
            "heur_square_bracket_sdh": "IDX:{idx}|נמצאו סוגריים מרובעים (SDH) באינדקס {idx}. אין לכלול הבעות פנים או צלילי רקע בתרגום.",
            "heur_parentheses_sdh": "IDX:{idx}|נמצאו סוגריים או סמלי מוזיקה (SDH) באינדקס {idx}.",
            "heur_robot_talk": "IDX:{idx}|נמצאו ביטויי 'Robot Talk' (דיבור רובוטי) באינדקס {idx}.",
            "heur_tag_mismatch": "IDX:{idx}|נמצא חוסר התאמה של תגיות HTML התחלתיות וסוגרות באינדקס {idx}.",
            "heur_glitch_long_word": "IDX:{idx}|נמצאה מילה ארוכה באופן חריג באינדקס {idx}.",
            "heur_semantic_echo": "IDX:{idx1},{idx2}|זוהתה כפילות תוכן חריגה (Echo) בין כתוביות סמוכות. ודא שהמידע אינו חוזר על עצמו בטעות.",
            "heur_batch_density": "GLOBAL|נפח התרגום הכולל בבאץ' חורג מהנורמה ({batch_ratio:.2f}x)."
        },
        "native_do_not_translate_rule": "3. **אל תתרגם ואל תכלול בפלט** אף מילה המופיעה בבלוקי ה\"הקשר\" (בכל שדה שהוא).",
        "native_missing_translation_label": "תרגום חסר",
        "native_tag_rule": "4. תגיות עיצוב (Formatting Tags): שמור על תגיות כמו <i> או <font color=\"...\"> בדיוק במיקומן המקורי. אל תתרגם מילים טכניות (כמו 'color') ואל תמחק אותן. **חשוב: מותר (ואף חובה) להוסיף ירידת שורה `\\n` בתוך תגיות (למשל `<i>טקסט...\\n...טקסט</i>`) כדי לשמור על חוק {max_words} המילים לשורה.** וודא שערכי צבע מוקפים במירכאות.",
        "native_workflow_steps": {
            "header": "### [IDX_WORKFLOW]. תהליך עבודה מובנה (חובה - אין לדלג) ###\nכדי להבטיח תרגום מדויק וטבעי, עליך לעבוד בשלבים הבאים בדיוק לפי הסדר:\n\nבשדה thought_process כתוב את \"תהליך המחשבה, האסטרטגיה וההתלבטויות לפני התרגום הסופי.\" (חשוב: אל תעתיק את משפט זה כפי שהוא! כתוב את מחשבותיך האמיתיות).\nבשדה summary כתוב את \"תקציר קצר של המתרחש בעלילה כרגע.\" (חשוב: אל תעתיק את משפט זה כפי שהוא! כתוב תקציר אמיתי).\nבשדה translated_srt הזן את התרגומים הסופיים.\nבשדה last_speaker_info כתוב את \"שם הדובר האחרון (M/F) פונה אל יעד (M/F/לא ידוע/מצלמה).\" (אל תעתיק את ההוראה).\nבשדה continuity_note כתוב את \"הוראת רצף לבאץ' הבא (השאר ריק אם אין).\" (אל תעתיק את ההוראה).",
            "read_context": "שלב {n}: קרא את טקסט \"הקשר קודם\" ואת \"הקשר הבא\" כדי להבין את הסיטואציה. שים לב: הטקסטים הללו מוגשים כעת כטקסט נקי ללא אינדקסים או זמנים (Striped Context). **אל תתרגם אותם**.",
            "priming": "שלב {n}: כתוב תקציר קצר של המתרחש בעלילה כרגע בתוך שדה ה-summary. זה יעזור לך 'להיכנס לעניינים' לפני שאתה מתחיל לתרגם.",
            "draft": "שלב {n}: קרא את מילון ה-JSON המופיע תחת הכותרת [Translation Blocks - JSON]. זהו המידע היחיד שעליך לתרגם. תרגם את כל הטקסטים המופיעים במילון כפסקה אחת רציפה, טבעית וזורמת לעברית. כתוב תרגום זה בתוך שדה \"continuous_translation_draft\" ב-JSON. בשלב זה, אל תתייחס לאינדקסים. חל איסור מוחלט לכלול בטיוטה מידע המופיע בבלוקי ההקשר.",
            "mapping": "שלב {n}: מיפוי טכני תמציתי של חלוקת הטיוטה בחזרה לאינדקסים, תוך היצמדות מלאה למבנה המקור באנגלית. דוגמה: 'משפט 1 ל-14. משפט 2 ל-15. \\n ב-16. דוברים פוצלו ב-17'. אל תסביר, רק מפה. כתוב זאת בשדה \"mapping_plan\".",
            "split_rules": "שלב {n}: שבירת שורות (\\n) - חובה קריטית: \n1. כתובית לא יכולה להכיל יותר מ-{max_words} מילים בשורה אחת. אם התרגום ארוך, עליך לפצל אותו לשתי שורות קצרות ושוות ככל הניתן בעזרת התו \\n. מותר (ואף חובה) להוסיף את ה-\\n בתוך תגיות עיצוב (למשל: <i>טקסט... \\n ...טקסט</i>).\n2. חוק שני דוברים: אם כתובית מכילה דיאלוג בין שני אנשים (מסומן בשני מקפים -), חובה לפצל את הכתובית לשתי שורות בעזרת \\n כך שכל דובר יקבל שורה משלו.",
            "final_srt": "שלב {n}: הזן את הטקסט המחולק והסופי לתוך האובייקט \"translated_srt\". **חובה להחזיר מפת JSON (Dictionary) שבה המפתחות הם בדיוק אותם האינדקסים שקיבלת בקלט, והערכים הם התרגומים לעברית**. חובה לוודא ששמות דוברים (כמו 'PROBST:' או 'JEFF:' או 'ג'ף:') נמחקו לחלוטין ולא תורגמו.",
            "metadata": "שלב {n}: עדכון מטא-דאטה (Metadata) לבאץ' הבא. מלא את השדות 'last_speaker_info' ו-'continuity_note' על סמך הטקסט שתירגמת הרגע. **אזהרה: אל תעתיק את משפטי ההדרכה שבתוך הגרשיים (למשל 'שם הדובר...') לתוך הפלט! עליך להחליף אותם במידע האמיתי מהפרק.**",
            "audit": "שלב {n}: ביקורת איכות והצלבת נתונים (Self-Audit)\nלפני סגירת ה-JSON, עליך לבצע סריקה קפדנית של האובייקט translated_srt מול רשימת המקור.\nעליך לענות לעצמך על השאלות הבאות:\n- האם כל האינדקסים קיימים? וודא שכל מספר אינדקס שהופיע בקלט מופיע גם בפלט.\n- האם יש שכפולים? בדוק האם טקסט מסוים מופיע פעמיים תחת אינדקסים שונים.\n- האם יש השמטות? וודא שכל המידע מהמקור מצא את מקומו בתרגום הסופי.\n- תקינות טכנית: וודא שלא השתמשת בלוכסן שגוי (כמו \\נ) ושהשתמשת רק ב-\\n לפיצול שורות."
        },
        "native_technical_rules": "### [IDX_TECH]. חוקים טכניים ועיצוב חזותי (קריטי) ###\n- רציפות מגדרית (Gender Tracking): עקוב בקפידה אחר מגדר הדוברים לאורך כל הבאץ'. אם מספר שורות רצופות שייכות לאותו דובר (או מדברות על אותה דמות מילון הדמויות), חובה לשמור על תארים ופעלים באותו מגדר בדיוק. חל איסור להחליף מגדר באמצע הפסקה.\n- גבולות התרגום: תרגם אך ורק את הערכים המופיעים במילון ה-JSON תחת [בלוקים לתרגום - JSON]. בשום פנים ואופן אין לכלול בתרגום טקסט שנמצא בבלוקי ההקשר.\n- חוק ה-1:1 (דיוק במפת המפתחות): חובה להחזיר בתוך 'translated_srt' את כל המפתחות (האינדקסים) שהופיעו בקלט. אל תחסיר אף מפתח ואל תוסיף מפתחות חדשים.\n- חוק ה-ו' (קריטי): בעברית, ו' החיבור חייבת להיות תחילית הצמודה למילה הבאה ללא רווח (למשל \"וכולנו\", ולא \"ו כולנו\" או \"ו\\nכולנו\"). אם שורת המקור מסתיימת ב-\"and\" והמשפט ממשיך, חובה לחבר את ה-ו' לתחילת המילה הראשונה בשורה הבאה. חריג יחיד: אם המשפט נקטע/נקטע באמצע (למשל מסתיים ב-\"and--\" או \"and...\"), מותר ואף רצוי לתרגם כ-\"ו-\" או \"ו...\" בסוף השורה כדי לשמר את השהיית הדיבור (Cliffhanger).\n- ללא אנגלית: אל תשאיר מילים באנגלית בתרגום הסופי (מלבד שמות מותגים או ראשי תיבות ללא תרגום מקובל, כמו CNN או CBS). חריג קריטי: כאשר מופיעה אות אנגלית בודדת לתיאור צורה או אובייקט (למשל The \"I\" piece, V-shaped), עליך לתעתק את שם האות לעברית. לדוגמה: תרגם \"האות I\" ל-\"האות איי\", ו-\"צורת V\" ל-\"צורת וי\". לעולם אל תשאיר את האותיות באנגלית בפלט.\n\n### [IDX_CLEAN]. חוקי ניקוי ועיצוב (חובה להחיל על פלט ה-JSON הסופי) ###\n1. מחיקת תגיות דוברים (Speaker Labels): מחק לגמרי תגיות זיהוי של דוברים המופיעות בתחילת כתובית ומסתיימות בנקודתיים (למשל \"PROBST:\", \"JEFF:\", \"ג'ף:\"). חובה לוודא ששם הדובר לא נשאר בתרגום הסופי. אזהרה: אם שם נכתב כחלק טבעי מהמשפט (למשל \"-Julie drops\"), אסור למחוק אותו.\n2. ניקוי רכיבי קול (SDH): מחק תיאורי קול בסוגריים [] או () (למשל: [cheering], (coughs)). **חשוב:** אם הטקסט בתוך הסוגריים הוא דיאלוג מדובר (למשל לחישה), עליך לתרגם אותו ולשמור על הסוגריים. אם השורה מכילה רק תיאור קול, החזר מחרוזת ריקה \"\".\n3. שבירת שורות (\\n): חובה עליך לפצל משפטים ארוכים! אם הטקסט המתורגם שייכנס לאינדקס מסוים עולה על {max_words} מילים, עליך להשתמש בתו `\\n` במקום הגיוני תחבירית (אחרי פסיק, נקודה, או מילת חיבור) כדי לחלק אותו לשתי שורות. ניתן ורצוי לפצל בתוך תגיות עיצוב (למשל בתוך <i>).\n4. אימות כמותי (Audit): חל איסור מוחלט על \"המצאת\" טקסט כדי למלא אינדקסים או שכפול טקסט מאינדקס קודם.\n\n- איסור אנגלית מוחלט (Strict No-English): חרף כל הוראה אחרת, חל איסור מוחלט על השארת תווים באנגלית בשדה translated_srt. תרגם או תעתק הכל לעברית! (למשל: השתמש ב-'הישרדות' במקום 'Survivor'). **שים לב במיוחד למילים קטנות שלעיתים נשמטות כמו 'of', 'and' או 'the' — הן חייבות להיות מתורגמות או להימחק.** כל תו אנגלי יפסול את התרגום.\n",
        "native_judge_prompt": "אתה מבקר QA חסר רחמים עבור תרגומי כתוביות לשפה עברית.\nשפת המקור: אנגלית. שפת היעד: עברית.\n\n### חוקי פסילה (פסול אם לפחות אחד מתקיים): ###\n1. השמטת טקסט: למקור יש טקסט משמעותי (>2 מילים) אך התרגום ריק.\n2. זליגת תווית דובר: תג הדובר נשאר בתרגום (למשל, \"JEFF:\" או התעתיק שלו).\n3. זליגת SDH: תיאורי צליל (למשל, [music], (coughs)) נשארים בתרגום.\n   חריג: דיאלוג בסוגריים (למשל, לחישות) תקין ומותר.\n4. זליגת שפת מקור: טקסט בשפה אנגלית מופיע בתרגום ללא הצדקה.\n   חריג: ראשי תיבות בין-לאומיים מוכרים (CNN, NASA) ושמות מותגים מותרים.\n5. חוסר התאמת תגיות: תגיות HTML/עיצוב (כמו <i>) אינן תואמות למקור.\n\n### חוקים קריטיים נגד הזיות (Anti-Hallucination): ###\n- התעלם מתגיות עיצוב ומקודי צבע (hex codes) בעת בדיקת זליגות שפה אנגלית.\n- לא כל המילים המסתיימות בנקודתיים הן שמות דוברים. \"תאריך:\", \"פרק:\" הם תוכן חוקי.\n- ודא שהשגיאות קיימות בטקסט ה-עברית, ולא במקור ה-אנגלית.\n- אל תהזה שגיאות! בדוק כל אינדקס בנפרד.\n- אם הבאץ' ללא רבב לחלוטין, הגדר `is_rejected: false` והשאר את תיאורי השגיאות ריקים.\n- אם נמצאה אפילו שגיאה זעירה אחת, הגדר `is_rejected: true` ופרט אותה.\n- **עליך להשיב אך ורק בשפה עברית.** אל תשתמש באנגלית בתהליך המחשבה שלך.",
        "native_schema_descriptions": {
            "thought_process": "תהליך המחשבה, האסטרטגיה וההתלבטויות לפני התרגום הסופי. אזהרה: אל תעתיק את תיאור השדה! כתוב את מחשבותיך האמיתיות.",
            "summary": "תקציר קצר של המתרחש בעלילה כרגע. אזהרה: אל תעתיק את תיאור השדה! כתוב תקציר אמיתי.",
            "continuous_translation_draft": "תרגום כל הטקסטים כפסקה אחת רציפה, טבעית וזורמת.",
            "mapping_plan": "תוכנית מיפוי תמציתית של חלוקת הטיוטה לאינדקסים.",
            "translated_srt": "מילון שקידודו הוא האינדקסים המספריים והערכים הם התרגומים הסופיים לעברית.",
            "last_speaker_info": "שם הדובר (M/F) פונה אל יעד (M/F/לא ידוע/מצלמה).",
            "continuity_note": "הוראת רצף לבאץ' הבא (השאר ריק אם אין).",
            "judge_thought_process": "חובה: כתוב לפחות משפט אחד בעברית המנתחים את התרגום מול המקור. הסבר בדיוק למה החלטת לפסול או לאשר. אל תשתמש ב-'...'.",
            "judge_summary": "תקציר קצר (משפט אחד) של העלילה. אל תשתמש ב-'...'.",
            "judge_is_valid": "True אם התרגום מושלם. False אם יש לפסול (חוקים 1-6).",
            "judge_error_map": "מיפוי אינדקסים לשגיאות. חובה לתת נימוק בעברית לכל פסילה. עבור תקין השאר מחרוזת ריקה \"\"."
        },
        "native_judge_strings": {
            "overlap_header": "### [הקשר לקריאה בלבד] (לעיון בלבד - אל תבקר שורות אלו) ###",
            "overlap_desc": "אל תפסול את שורות ה-OVERLAP; השתמש בהן רק כדי להבין אם מידע «זלג» לכתובית סמוכה בבאץ' הנבדק.",
            "overlap_none": "(אין — גבול הקובץ)",
            "overlap_missing_context": "(הקשר חיצוני לא סופק.)",
            "overlap_cannot_resolve": "(לא ניתן לפתור שכנים — אינדקס חסר ברשימת הסדר.)",
            "overlap_pre_batch": "שורה אחת לפני תחילת ה-chunk (מידע לפני הבאץ')",
            "overlap_post_batch": "שורה אחת אחרי סוף ה-chunk (מידע אחרי הבאץ')",
            "overlap_not_translated": "שורה זו לא תורגמה עדיין - אין לפסול אותה בשל כך - אתה בודק רק את התרגום של השורות שקדמו לה",
            "source_label": "מקור ({lang}):",
            "target_label": "תרגום ({lang}):",
            "chunk_header": "### באץ' ביקורת {current}/{total} (בלוקים: {start}-{end}) ###",
            "automated_warning_header": "### אזהרת ביקורת מערכת אוטומטית: ###",
            "automated_warning_desc": "הערה: אלגוריתם אוטומטי סימן שגיאה אפשרית לעיל. בדוק היטב את האינדקס שצוין. הפעל שיקול דעת עצמאי - ייתכן שהאלגוריתם טועה (למשל עקב הבדלי אורך טבעיים בין שפות). פסול רק אם אתה רואה שגיאה מהותית ואמיתית במו עיניך.",
            "end_of_data": "### סוף נתונים ###",
            "final_warning": "אזהרה סופית: דחה את הבאץ' (`is_rejected: true`) רק אם אתה רואה שגיאה במו עיניך בשדה התרגום ({lang}). אל תפסול אם השגיאה קיימת רק במקור ({source}).",
            "field_desc_thought": "ניתוח מעמיק (לפחות משפט אחד מלא). הסבר בדיוק מה בדקת. אל תשתמש ב-'...'.",
            "field_desc_summary": "תקציר קצר של העלילה. אל תשתמש ב-'...'.",
            "field_desc_is_rejected": "True אם נפסל (נמצאה שגיאה). False אם ללא רבב.",
            "field_desc_error_map": "תיאור השגיאה (משפט מלא). השאר ריק אם ללא רבב."
        },
        "native_index_label": "אינדקס",
        "native_feedback_header": "### חובה לתקן את השגיאות הבאות לפי אינדקס (אל תחזור על טעויות אלו): ###",
        "native_last_line_label": "שורה אחרונה שתורגמה (מהבאץ' הקודם): '{last_line}'",
        "native_continuity_note_label": "⚠️ הערת רצף מהבאץ' הקודם (שים לב!): {note}",
        "native_story_context_header": "### הקשר עלילתי (באצ'ים קודמים) ###",
        "native_current_setting_label": "תפאורה נוכחית: {setting}",
        "native_plot_summary_label": "תקציר עלילה: {summary}",
        "native_last_speaker_label": "דובר אחרון (באץ' קודם): {speaker}",
        "native_schema_mandatory_label": "### חובה: השב בפורמט ה-JSON Schema המוגדר בלבד. ###",
        "native_placeholder_indicators": ["<הכנס כאן", "<חובה למלא", "<התרגום הסופי", "<שם הדובר", "<הוראת רצף"],
        "native_robot_phrases": ["הנה התרגום", "כאן מופיע", "תרגום:", "הכתובית הבאה"],
        "native_exempt_labels": ["הערה", "שים לב", "נ.ב"],
        "native_repair_note_ghost": "IDX:{indices}|בוצע תיקון אוטומטי להסרת שאריות אנגלית (Ghost fragments). וודא היטב שהמשפט תקין וזורם.",
        "native_repair_note_newline": "בוצע תיקון אוטומטי לפורמט השורות (n\\).",
        "native_stubborn_split_log": "💡 דגם עקשן זוהה. מבצע חלוקה תוכניתית עבור אינדקס {idx}.",
        "native_stubborn_resolved_log": "✅ החלוקה התוכניתית פתרה את הבעיה. ממשיך...",
        "native_intervention_header": "####### התערבות אנושית נדרשת ################",
        "native_intervention_instructions": [
            "הוראות:",
            "1. ערוך את התרגום בעברית למיטב יכולתך.",
            "2. שמור את הקובץ (Ctrl+S).",
            "3. סגור את Notepad על מנת להמשיך"
        ],
        "native_intervention_source_label": "שורות המקור באנגלית",
        "native_intervention_target_label": "שורות מתורגמות שנדרש בהן תיקון",
        "native_intervention_edit_warning": "אל תשנה את השורות עם המספרים, רק את התרגום",
        "native_intervention_max_words_warning": "נסה לסדר שלא יהיו יותר מ-{max_words} מילים בשורה",
        "native_intervention_error_label": "השגיאות שאותן הסקריפט זיהה בשורות תרגום אלו הן:",
        "native_do_not_translate_label": "לא לתרגום",
        "native_overlong_word": "מילים",
        "native_overlong_phrase": "ארוכה מדי",
        "native_newline_regex": r'\s*\\+[nננ]\s*'
    },
    "ar": {
        "name": "Arabic",
        "rtl": True,
        "script": "arabic",
        "unicode": [(0x0600, 0x06FF)],
        "max_words": 8,
        "ratio": 0.80,
        "direct_pairs": {"en": (0.40, 3.0, 0.45, 1.30)},
        "unknown_speaker": "غير معروف",
        "setting_label": "غير معروف",
        "opening_summary": "الحلقة بدأت للتو.",
        "label_prev_context": "السياق السابق"
    },
    "fr": {
        "name": "French",
        "rtl": False,
        "script": "latin",
        "unicode": [(0x0000, 0x024F)],
        "max_words": 10,
        "ratio": 1.15,
        "direct_pairs": {"en": (0.50, 3.5, 0.60, 1.50)},
        "opening_summary": "L'épisode vient de commencer.",
        "label_prev_context": "Contexte Précédent",
        "native_workflow_steps": {
            "header": "### [IDX_WORKFLOW]. Processus de Travail Structuré (Obligatoire - Ne pas ignorer) ###\nPour garantir une traduction précise et naturelle, vous devez suivre ces étapes dans l'ordre exact :\n\nDans le champ thought_process, écrivez votre \"processus de réflexion, stratégie et dilemmes avant la traduction finale.\" (Important : Ne copiez pas cette phrase ! Écrivez vos vraies pensées).\nDans le champ summary, écrivez un \"court résumé de ce qui se passe dans l'intrigue en ce moment.\" (Important : Ne copiez pas cette phrase ! Écrivez un vrai résumé).\nDans le champ translated_srt, saisissez les traductions finales.\nDans le champ last_speaker_info, écrivez le \"nom du dernier locuteur (M/F) s'adressant à la cible (M/F/Inconnu/Caméra).\" (Ne copiez pas l'instruction).\nDans le champ continuity_note, écrivez la \"note de continuité pour le prochain lot (laisser vide si aucune).\" (Ne copiez pas l'instruction).",
            "read_context": "Étape {n} : Lisez les textes \"Contexte Précédent\" et \"Contexte Suivant\" pour comprendre la situation. Note : Ces textes sont fournis en texte brut sans index ni horodatage (Striped Context). **Ne les traduisez pas**.",
            "priming": "Étape {n} : Écrivez un court résumé de ce qui se passe dans l'intrigue en ce moment dans le champ summary. Cela vous aidera à vous mettre en contexte avant de commencer à traduire.",
            "draft": "Étape {n} : Lisez le dictionnaire JSON sous l'en-tête [Translation Blocks - JSON]. C'est la SEULE information que vous devez traduire. Traduisez tous les textes apparaissant dans le dictionnaire comme un seul paragraphe continu, naturel et fluide en Français. Écrivez cette traduction dans le champ JSON \"continuous_translation_draft\". À ce stade, ignorez les index. Il vous est strictement interdit d'inclure des informations provenant des blocs de contexte dans le brouillon.",
            "mapping": "Étape {n} : Cartographie technique concise du brouillon vers les index, en respectant strictement la structure de la source anglaise. Exemple : 'Phrase 1 vers 14. Phrase 2 vers 15. \\n en 16. Locuteurs divisés en 17'. Ne pas expliquer, juste cartographier. Écrivez cela dans le champ \"mapping_plan\".",
            "split_rules": "Étape {n} : Sauts de ligne (\\n) - Exigence Critique :\n1. Un sous-titre ne peut pas contenir plus de {max_words} mots sur une seule ligne. Si la traduction est longue, vous devez la diviser en deux lignes courtes et équilibrées à l'aide du caractère \\n. Vous êtes autorisé (et tenu) d'ajouter le \\n à l'intérieur des balises de formatage (ex : <i>texte... \\n ...texte</i>).\n2. Règle des deux locuteurs : Si un sous-titre contient un dialogue entre deux personnes (indiqué par deux traits d'union -), vous devez diviser le sous-titre en deux lignes à l'aide de \\n afin que chaque locuteur ait sa propre ligne.",
            "final_srt": "Étape {n} : Saisissez le texte divisé et final dans l'objet \"translated_srt\". **Vous devez renvoyer une carte JSON (Dictionnaire) où les clés sont exactement les mêmes index numériques que vous avez reçus en entrée, et les valeurs sont les traductions finales en Français**. Assurez-vous que les noms des locuteurs (comme 'PROBST:' ou 'JEFF:' etc.) sont complètement supprimés et non traduits.",
            "metadata": "Étape {n} : Mettre à jour les métadonnées pour le prochain lot. Remplissez les champs 'last_speaker_info' et 'continuity_note' en fonction du texte que vous venez de traduire. **Attention : Ne copiez pas les phrases d'instruction entre guillemets (ex : 'nom du locuteur...') dans le résultat ! Vous devez les remplacer par les informations réelles de l'épisode.**",
            "audit": "Étape {n} : Contrôle Qualité et Références Croisées (Auto-Audit)\nAvant de fermer le JSON, scannez attentivement l'objet translated_srt par rapport à la liste source.\nVous devez répondre aux questions suivantes par vous-même :\n- Tous les index existent-ils ? Assurez-vous que chaque numéro d'index apparu dans l'entrée apparaît également dans la sortie.\n- Y a-t-il des doublons ? Vérifiez si un certain texte apparaît deux fois sous des index différents.\n- Y a-t-il des omissions ? Assurez-vous que toutes les informations de la source ont trouvé leur place dans la traduction finale.\n- Validité technique : Assurez-vous de ne pas avoir utilisé de barres obliques incorrectes et d'avoir uniquement utilisé \\n pour diviser les lignes."
        },
        "native_technical_rules": "### [IDX_TECH]. Règles Techniques et Formatage Visuel (CRITIQUE) ###\n- Suivi du Genre : Suivez attentivement le genre des locuteurs tout au long du lot. Si plusieurs lignes consécutives appartiennent au même locuteur (ou parlent du même personnage du dictionnaire), vous devez maintenir exactement le même genre pour les adjectifs et les verbes. Ne changez pas de genre au milieu d'un paragraphe.\n- Limites de Traduction : Traduisez UNIQUEMENT les valeurs apparaissant dans le dictionnaire JSON sous [Translation Blocks - JSON]. En aucun cas vous ne devez inclure de texte trouvé dans les blocs de contexte dans la traduction.\n- Règle 1:1 (Précision de la carte des clés) : Vous devez renvoyer dans 'translated_srt' TOUTES les clés (index) qui sont apparues dans l'entrée. N'omettez aucune clé et n'ajoutez pas de nouvelles clés.\n- Pas de Langue Source : Ne laissez pas de mots en Anglais dans la traduction finale (sauf pour les noms de marques ou les acronymes sans traduction acceptée, comme CNN ou CBS). Exception Critique : Lorsqu'une seule lettre anglaise apparaît pour décrire une forme ou un objet (ex : La pièce en \"I\", en forme de V), vous devez translittérer le nom de la lettre en Français. Ne laissez jamais les lettres anglaises dans la sortie.\n\n### [IDX_CLEAN]. Règles de Nettoyage et de Formatage (DOIT s'appliquer à la sortie JSON finale) ###\n1. Supprimer les Étiquettes de Locuteur : Supprimez complètement les étiquettes d'identification des locuteurs qui apparaissent au début d'un sous-titre et se terminent par deux points (ex : \"PROBST:\", \"JEFF:\"). Vous devez vous assurer que le nom du locuteur ne reste pas dans la traduction finale.\n2. Nettoyer les Éléments Sonores (SDH) : Supprimez les descriptions sonores entre crochets [] ou parenthèses () (ex : [acclamations], (tousse)). **Important :** Si le texte à l'intérieur des parenthèses est un dialogue parlé (ex : chuchotement), vous devez le traduire et garder les parenthèses.\n3. Sauts de ligne (\\n) : Vous devez diviser les phrases longues ! Si le texte traduit pour un index spécifique dépasse {max_words} mots, vous devez utiliser le caractère `\\n` à un endroit syntaxiquement logique pour diviser le texte en deux lignes.",
        "native_judge_prompt": "Vous êtes un auditeur QA impitoyable pour les traductions de sous-titres en Français.\nLangue source : Anglais. Langue cible : Français.\n\n### RÈGLES DE REJET (rejeter si l'une d'entre elles est VRAIE) :\n1. Omission de texte : La source contient un texte significatif (>2 mots) mais la traduction est vide.\n2. Fuite d'étiquette de locuteur : Une étiquette de locuteur reste dans la traduction (ex : \"JEFF:\" ou sa translittération).\n3. Fuite SDH : Les descripteurs sonores (ex : [musique], (tousse)) restent dans la traduction.\n   EXCEPTION : Le dialogue entre parenthèses (ex : chuchotements) est valide.\n4. Fuite de langue source : Du texte en Anglais apparaît dans la traduction sans justification.\n5. Incohérence des balises : Les balises HTML/de formatage (comme <i>) ne correspondent pas à la source.\n\n### RÈGLES CRITIQUES ANTI-HALLUCINATION :\n- Ignorez les balises de formatage lors de la vérification des fuites d'Anglais.\n- Tous les mots se terminant par deux points ne sont pas des noms de locuteurs.\n- Vérifiez que les erreurs existent dans le texte Français, PAS dans la source Anglaise.\n- Ne PAS halluciner d'erreurs. Vérifiez CHAQUE index individuellement.\n- Si le lot est parfaitement correct, définissez `is_rejected: false`.\n- Si une seule petite erreur est trouvée, définissez `is_rejected: true` et détaillez-la.\n- **Vous devez répondre entièrement en Français.** N'utilisez pas l'Anglais dans votre processus de réflexion.",
        "native_user_prompt_prefix": "Vous traduisez maintenant le lot suivant. Rappel : La sortie doit être en Français uniquement.",
        "native_special_instructions_header": "### Instructions Spéciales pour ce Lot (Votre Responsabilité !) ###",
        "native_technical_rules_header": "### Règles Techniques Obligatoires ###",
        "native_exact_count_rule": "1. Compte Exact : **Vous devez renvoyer exactement {expected_count} clés dans l'objet 'translated_srt'.**",
        "native_exact_indices_rule": "2. Index Exacts : Utilisez EXACTEMENT les index suivants comme clés : {indices}.",
        "native_do_not_translate_rule": "3. **NE TRADUISEZ PAS et N'INCLUEZ PAS** de mot apparaissant dans les blocs de \"Contexte\" (dans n'importe quel champ).",
        "native_missing_translation_label": "Traduction manquante",
        "native_tag_rule": "4. Balises de Formatage : Conservez les balises comme <i> ou <font color=\"...\"> exactement dans leur position d'origine. Ne traduisez pas les mots techniques (comme 'color') et ne les supprimez pas. **Important : Vous êtes autorisé (et tenu) d'ajouter un saut de ligne `\\n` à l'intérieur des balises (ex : `<i>texte...\\n...texte</i>`) pour maintenir la règle des {max_words} mots par ligne.** Assurez-vous que les valeurs de couleur sont entourées de guillemets.",
        "native_schema_descriptions": {
            "thought_process": "Le processus de réflexion, la stratégie et les délibérations avant la traduction finale. Attention : Ne copiez pas la description du champ ! Écrivez vos vraies pensées.",
            "summary": "Un bref résumé de ce qui se passe actuellement dans l'intrigue. Attention : Ne copiez pas la description du champ ! Écrivez un vrai résumé.",
            "continuous_translation_draft": "Traduisez tous les textes comme un seul paragraphe continu, naturel et fluide.",
            "mapping_plan": "Un plan de cartographie concis divisant le brouillon en index.",
            "translated_srt": "Un dictionnaire où les clés sont des index numériques et les valeurs sont les traductions finales en Français.",
            "last_speaker_info": "Le nom du locuteur (M/F) s'adressant à une cible (M/F/Inconnu/Caméra).",
            "continuity_note": "Instruction de continuité pour le prochain lot (laisser vide si aucune).",
            "judge_thought_process": "Mandatoire : Écrivez au moins une phrase en Français analysant la traduction par rapport à la source. Expliquez exactement pourquoi vous avez décidé de rejeter ou d'approuver. N'utilisez pas de '...'.",
            "judge_summary": "Un bref résumé (une phrase) de l'intrigue. N'utilisez pas de '...'.",
            "judge_is_valid": "True si la traduction est parfaite. False si elle doit être rejetée (Règles 1-6).",
            "judge_error_map": "Cartographie des index aux erreurs. Mandatoire de fournir un raisonnement en Français pour chaque rejet. Pour une traduction valide, laissez une chaîne vide \"\"."
        },
        "native_judge_strings": {
            "overlap_header": "### [CONTEXTE EN LECTURE SEULE] (RÉFÉRENCE UNIQUEMENT - NE PAS AUDITER CES LIGNES) ###",
            "overlap_desc": "Ne rejetez pas les lignes OVERLAP ; utilisez-les uniquement pour comprendre si des informations ont « fui » vers un sous-titre adjacent dans le lot audité.",
            "overlap_none": "(Aucun — limite du fichier)",
            "overlap_missing_context": "(Contexte externe non fourni.)",
            "overlap_cannot_resolve": "(Impossible de résoudre les voisins — index manquant dans la liste de commande.)",
            "overlap_pre_batch": "Une ligne avant le début du chunk (Informations pré-lot)",
            "overlap_post_batch": "Une ligne après la fin du chunk (Informations post-lot)",
            "overlap_not_translated": "Cette ligne n'a pas encore été traduite - ne la rejetez pas pour cette raison - vous auditez uniquement la traduction des lignes précédentes",
            "source_label": "Source ({lang}) :",
            "target_label": "Traduction ({lang}) :",
            "chunk_header": "### CHUNK D'AUDIT {current}/{total} (Blocs : {start}-{end}) ###",
            "automated_warning_header": "### AVERTISSEMENT D'AUDIT SYSTÈME AUTOMATISÉ : ###",
            "automated_warning_desc": "NOTE : Un algorithme automatisé a signalé une erreur potentielle ci-dessus. Examinez attentivement l'index spécifié. Exercez votre jugement indépendant - l'algorithme pourrait se tromper (ex : différences de longueur naturelles entre les langues). Ne rejetez que si vous voyez une erreur réelle et matérielle de vos propres yeux.",
            "end_of_data": "### FIN DES DONNÉES ###",
            "final_warning": "AVERTISSEMENT FINAL : Rejetez le lot (`is_rejected: true`) UNIQUEMENT si vous voyez l'erreur de vos propres yeux dans le champ Traduction ({lang}). NE REJETEZ PAS si l'erreur n'existe que dans la Source ({source}).",
            "field_desc_thought": "Analyse approfondie (minimum une phrase complète). Expliquez exactement ce que vous avez vérifié. N'utilisez pas '...'.",
            "field_desc_summary": "Bref résumé de l'intrigue. N'utilisez pas '...'.",
            "field_desc_is_rejected": "True si rejeté (erreur trouvée). False si totalement impeccable.",
            "field_desc_error_map": "Description de l'erreur (phrase complète). Laissez vide si impeccable."
        },
        "native_index_label": "Index",
        "native_feedback_header": "### VOUS DEVEZ CORRIGER LES ERREURS SUIVANTES PAR INDEX (NE RÉPÉTEZ PAS CES ERREURS) : ###",
        "native_last_line_label": "Dernière ligne traduite (du lot précédent) : '{last_line}'",
        "native_continuity_note_label": "⚠️ Note de continuité du lot précédent (Attention !) : {note}",
        "native_story_context_header": "### Contexte de l'histoire (lots précédents) ###",
        "native_current_setting_label": "Cadre actuel : {setting}",
        "native_plot_summary_label": "Résumé de l'intrigue : {summary}",
        "native_last_speaker_label": "Dernier locuteur (lot précédent) : {speaker}",
        "native_schema_mandatory_label": "### OBLIGATOIRE : Répondez EXACTEMENT au format JSON Schema spécifié. ###",
        "native_placeholder_indicators": ["<insérez ici", "<doit être rempli", "<la traduction finale", "<nom du locuteur", "<instruction de continuité"],
        "native_robot_phrases": ["Voici la traduction", "Ici apparaît", "Traduction :", "Le sous-titre suivant"],
        "native_exempt_labels": ["Note", "Attention", "PS"],
        "native_repair_note_ghost": "IDX:{indices}|Réparation automatique appliquée pour supprimer les fragments fantômes de la langue source. Vérifiez que la phrase coule naturellement.",
        "native_repair_note_newline": "Réparation automatique appliquée au format de ligne (\\n).",
        "native_stubborn_split_log": "💡 Modèle obstiné détecté. Application d'une division programmée pour l'index {idx}.",
        "native_stubborn_resolved_log": "✅ La division programmée a résolu le problème. Poursuite...",
        "native_intervention_header": "####### INTERVENTION MANUELLE REQUISE #######",
        "native_intervention_instructions": [
            "Instructions :",
            "1. Modifiez la traduction au mieux de vos capacités.",
            "2. Enregistrez le fichier (Ctrl+S).",
            "3. Fermez l'éditeur pour continuer."
        ],
        "native_intervention_source_label": "LIGNES SOURCES ANGLAISES",
        "native_intervention_target_label": "LIGNES TRADUITES NÉCESSITANT UNE CORRECTION",
        "native_intervention_edit_warning": "Ne modifiez pas les numéros d'index, seulement le texte de la traduction.",
        "native_intervention_max_words_warning": "Essayez de ne pas dépasser {max_words} mots par ligne.",
        "native_intervention_error_label": "Les erreurs identifiées dans ces lignes sont :",
        "label_prev_context": "Contexte Précédent",
        "label_translation_blocks": "Blocs de Traduction - JSON",
        "label_next_context": "Contexte Suivant",
        "native_do_not_translate_label": "PAS À TRADUIRE",
        "native_overlong_word": "mots",
        "native_overlong_phrase": "trop longue",
        "native_missing_translation_label": "Traduction manquante"
    },
    "es": {
        "name": "Spanish",
        "rtl": False,
        "script": "latin",
        "unicode": [(0x0000, 0x024F)],
        "max_words": 10,
        "ratio": 1.20,
        "direct_pairs": {"en": (0.50, 3.5, 0.60, 1.50)},
        "unknown_speaker": "Desconocido",
        "setting_label": "Desconocido",
        "opening_summary": "El episodio acaba de empezar.",
        "label_prev_context": "Contexto Anterior"
    },
    "de": {
        "name": "German",
        "rtl": False,
        "script": "latin",
        "unicode": [(0x0000, 0x024F)],
        "max_words": 8,
        "ratio": 0.95,
        "direct_pairs": {"en": (0.40, 3.5, 0.50, 1.40)},
        "unknown_speaker": "Unbekannt",
        "setting_label": "Unbekannt",
        "opening_summary": "Die Episode hat gerade erst begonnen.",
        "label_prev_context": "Vorheriger Kontext"
    },
    "zh": {
        "name": "Chinese",
        "rtl": False,
        "script": "cjk",
        "unicode": [(0x4E00, 0x9FFF), (0x3000, 0x303F), (0xFF00, 0xFFEF)],
        "max_words": 14,
        "ratio": 1.0,
        "use_char": True,
        "unknown_speaker": "未知",
        "setting_label": "未知",
        "opening_summary": "该集刚刚开始。",
        "label_prev_context": "先前的背景"
    },
    "pt": {
        "name": "Portuguese",
        "rtl": False,
        "script": "latin",
        "unicode": [(0x0000, 0x024F)],
        "max_words": 10,
        "ratio": 1.20,
        "direct_pairs": {"en": (0.50, 3.5, 0.60, 1.50)},
        "unknown_speaker": "Desconhecido",
        "setting_label": "Desconhecido",
        "opening_summary": "O episódio começou agora.",
        "label_prev_context": "Contexto Anterior"
    },
    "ru": {
        "name": "Russian",
        "rtl": False,
        "script": "cyrillic",
        "unicode": [(0x0400, 0x04FF)],
        "max_words": 8,
        "ratio": 1.0,
        "direct_pairs": {"en": (0.40, 3.0, 0.45, 1.30)},
        "unknown_speaker": "Неизвестно",
        "setting_label": "Неизвестно",
        "opening_summary": "Эпизод только что начался.",
        "label_prev_context": "Предыдущий контекст"
    },
    "it": {
        "name": "Italian",
        "rtl": False,
        "script": "latin",
        "unicode": [(0x0000, 0x024F)],
        "max_words": 10,
        "ratio": 1.15,
        "direct_pairs": {"en": (0.50, 3.5, 0.60, 1.50)},
        "unknown_speaker": "Sconosciuto",
        "setting_label": "Sconosciuto",
        "opening_summary": "L'episodio è appena iniziato.",
        "label_prev_context": "Contesto Precedente"
    },
    "pl": {
        "name": "Polish",
        "rtl": False,
        "script": "latin",
        "unicode": [(0x0000, 0x024F)],
        "max_words": 9,
        "ratio": 0.95,
        "direct_pairs": {"en": (0.35, 3.0, 0.40, 1.30)},
        "unknown_speaker": "Nieznany",
        "setting_label": "Nieznany",
        "opening_summary": "Odcinek właśnie się zaczął.",
        "label_prev_context": "Poprzedni kontekst"
    },
    "uk": {
        "name": "Ukrainian",
        "rtl": False,
        "script": "cyrillic",
        "unicode": [(0x0400, 0x04FF)],
        "max_words": 8,
        "ratio": 1.0,
        "direct_pairs": {"en": (0.40, 3.0, 0.45, 1.30)},
        "unknown_speaker": "Невідомо",
        "setting_label": "Невідомо",
        "opening_summary": "Епізод щойно розпочався.",
        "label_prev_context": "Попередній контекסט"
    }
}

def get_profile(source_code: str, target_code: str) -> LanguageProfile:
    source_info = BUILT_IN_PROFILES.get(source_code, {"name": source_code, "ratio": 1.0})
    target_info = BUILT_IN_PROFILES.get(target_code, {})
    
    is_rtl = target_info.get("rtl", target_code in RTL_LANGUAGES)
    
    return LanguageProfile(
        source_lang_code=source_code,
        target_lang_code=target_code,
        source_lang=source_info.get("name", source_code),
        target_lang=target_info.get("name", target_code),
        target_is_rtl=is_rtl,
        target_script=target_info.get("script", "latin"),
        target_unicode_ranges=target_info.get("unicode", [(0x0000, 0x024F)]),
        max_words_per_line=target_info.get("max_words", 10 if not is_rtl else 8),
        word_ratio_vs_english=target_info.get("ratio", 1.0),
        use_char_ratio=target_info.get("use_char", False),
        direct_pair_ratios=target_info.get("direct_pairs", {}),
        native_unknown_speaker=target_info.get("unknown_speaker", "Unknown"),
        native_setting_label=target_info.get("setting_label", "Unknown"),
        native_opening_summary=target_info.get("opening_summary", "The episode just started."),
        native_label_prev_context=target_info.get("label_prev_context", "Previous Context"),
        native_label_translation_blocks=target_info.get("label_translation_blocks", "Translation Blocks - JSON"),
        native_label_next_context=target_info.get("label_next_context", "Next Context"),
        native_audit_messages=target_info.get("native_audit_messages", {}),
        native_json_schema=target_info.get("native_json_schema", None),
        native_json_schema_lite=target_info.get("native_json_schema_lite", None),
        native_workflow_steps=target_info.get("native_workflow_steps", None),
        native_technical_rules=target_info.get("native_technical_rules", None),
        native_judge_prompt=target_info.get("native_judge_prompt", None),
        native_user_prompt_prefix=target_info.get("native_user_prompt_prefix", None),
        native_special_instructions_header=target_info.get("native_special_instructions_header", None),
        native_technical_rules_header=target_info.get("native_technical_rules_header", None),
        native_exact_count_rule=target_info.get("native_exact_count_rule", None),
        native_exact_indices_rule=target_info.get("native_exact_indices_rule", None),
        native_do_not_translate_rule=target_info.get("native_do_not_translate_rule", None),
        native_tag_rule=target_info.get("native_tag_rule", None),
        native_missing_translation_label=target_info.get("native_missing_translation_label", "Missing Translation"),
        native_schema_descriptions=target_info.get("native_schema_descriptions", {}),
        native_judge_strings=target_info.get("native_judge_strings", {}),
        # New fields for universalization
        native_index_label=target_info.get("native_index_label", "Index"),
        native_feedback_header=target_info.get("native_feedback_header", "### YOU MUST FIX THE FOLLOWING ERRORS BY INDEX (DO NOT REPEAT THESE MISTAKES): ###"),
        native_last_line_label=target_info.get("native_last_line_label", "Last translated line (from previous batch): '{last_line}'"),
        native_continuity_note_label=target_info.get("native_continuity_note_label", "⚠️ Continuity note from previous batch (Attention!): {note}"),
        native_story_context_header=target_info.get("native_story_context_header", "### Story Context (Previous Batches) ###"),
        native_current_setting_label=target_info.get("native_current_setting_label", "Current Setting: {setting}"),
        native_plot_summary_label=target_info.get("native_plot_summary_label", "Plot Summary: {summary}"),
        native_last_speaker_label=target_info.get("native_last_speaker_label", "Last Speaker (previous batch): {speaker}"),
        native_schema_mandatory_label=target_info.get("native_schema_mandatory_label", "### MANDATORY: Respond EXACTLY in the specified JSON Schema format. ###"),
        native_placeholder_indicators=target_info.get("native_placeholder_indicators", []),
        native_robot_phrases=target_info.get("native_robot_phrases", []),
        native_exempt_labels=target_info.get("native_exempt_labels", []),
        native_repair_note_ghost=target_info.get("native_repair_note_ghost", "Auto-repair applied to remove source language ghost fragments. Verify the sentence flows naturally."),
        native_repair_note_newline=target_info.get("native_repair_note_newline", "Auto-repair applied to line format (\\n)."),
        native_stubborn_split_log=target_info.get("native_stubborn_split_log", "💡 Stubborn model detected. Applying programmatic split for index {idx}."),
        native_stubborn_resolved_log=target_info.get("native_stubborn_resolved_log", "✅ Programmatic split resolved the issue. Proceeding..."),
        native_intervention_header=target_info.get("native_intervention_header", "####### MANUAL INTERVENTION REQUIRED #######"),
        native_intervention_instructions=target_info.get("native_intervention_instructions", [
            "1. Edit the translation to the best of your ability.",
            "2. Save the file (Ctrl+S).",
            "3. Close the editor to continue."
        ]),
        native_intervention_source_label=target_info.get("native_intervention_source_label", "SOURCE ENGLISH LINES"),
        native_intervention_target_label=target_info.get("native_intervention_target_label", "TRANSLATED LINES REQUIRING FIX"),
        native_intervention_edit_warning=target_info.get("native_intervention_edit_warning", "Do not change the index numbers, only the translation text."),
        native_intervention_max_words_warning=target_info.get("native_intervention_max_words_warning", "Try to ensure no more than {max_words} words per line."),
        native_intervention_error_label=target_info.get("native_intervention_error_label", "The errors identified in these lines are:")
    )

def load_custom_profile(data: dict) -> LanguageProfile:
    source_code = data.get("source_lang_code", "en")
    target_code = data.get("target_lang_code", "custom")
    base_profile = get_profile(source_code, target_code)
    
    # Override with custom data
    if "max_words_per_line" in data:
        base_profile.max_words_per_line = int(data["max_words_per_line"])
    if "use_native_instructions" in data:
        base_profile.use_native_instructions = bool(data["use_native_instructions"])
        
    return base_profile
