from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional
import os
import importlib
import importlib.util

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

def _load_built_in_profiles() -> Dict[str, dict]:
    """
    Dynamically loads all language profiles from the 'profiles' subdirectory.
    Each .py file (except __init__.py) is treated as a language profile.
    """
    profiles = {}
    profiles_dir = os.path.join(os.path.dirname(__file__), "profiles")
    
    if not os.path.exists(profiles_dir):
        return profiles

    for filename in os.listdir(profiles_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            lang_code = filename[:-3]
            try:
                # Try loading as a module within the package
                module_name = f"core.profiles.{lang_code}"
                module = importlib.import_module(module_name)
                if hasattr(module, "PROFILE"):
                    profiles[lang_code] = module.PROFILE
            except Exception:
                # Fallback: Load directly from file path
                try:
                    file_path = os.path.join(profiles_dir, filename)
                    spec = importlib.util.spec_from_file_location(f"profile_{lang_code}", file_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        if hasattr(module, "PROFILE"):
                            profiles[lang_code] = module.PROFILE
                except Exception:
                    continue
    return profiles

BUILT_IN_PROFILES = _load_built_in_profiles()

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
        native_intervention_error_label=target_info.get("native_intervention_error_label", "The errors identified in these lines are:"),
        native_do_not_translate_label=target_info.get("native_do_not_translate_label", "DO NOT TRANSLATE"),
        native_overlong_word=target_info.get("native_overlong_word", "words"),
        native_overlong_phrase=target_info.get("native_overlong_phrase", "too long"),
        native_newline_regex=target_info.get("native_newline_regex", r'\s*\\+[n]\s*')
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
