### modular work stages (translation process) ###
from language_profiles import LanguageProfile

RULE_NO_ENGLISH_EN = "- Strict No-English: Despite any other instruction, you are strictly forbidden from leaving {source_lang} characters in the translated_srt field. Translate or transliterate everything to {target_lang}! **Pay special attention to small words that are sometimes omitted like 'of', 'and' or 'the' — they must be translated or removed.** Any {source_lang} character will disqualify the translation.\n"


### --- ENGLISH METALANGUAGE TEMPLATES (PHASE 2) --- ###

STEP_HEADER_EN = """
### [IDX_WORKFLOW]. Structured Workflow (Mandatory - Do Not Skip) ###
To ensure accurate and natural translation, you must follow these steps in exact order:

In the thought_process field, write your "thought process, strategy, and dilemmas before the final translation." (Keep it concise: 2-3 sentences max).
In the summary field, write a "short summary of what is happening in the plot right now." (Important: Do not copy this sentence! Write an actual summary).
In the translated_srt field, enter the final translations.
In the last_speaker_info field, write the "name of the last speaker (M/F) speaking to target (M/F/Unknown/Camera)." (Do not copy the instruction).
In the continuity_note field, write the "continuity note for the next batch (leave empty if none)." (Do not copy the instruction).
"""

STEP_READ_CONTEXT_EN = """Step {n}: Read the "Previous Context" and "Next Context" text to understand the situation. Note: These texts are provided as clean text without indices or timestamps (Striped Context). **Do not translate them**."""

STEP_CONTINUOUS_DRAFT_EN = """Step {n}: Read the JSON dictionary under the header [Translation Blocks - JSON]. This is the ONLY information you must translate. Translate all texts appearing in the dictionary as one continuous, natural, and flowing paragraph in {target_lang}. Write this translation in the "continuous_translation_draft" JSON field. At this stage, ignore the indices. You are strictly forbidden from including information from the context blocks in the draft."""

STEP_MAPPING_PLAN_EN = """Step {n}: Concise technical mapping of the draft back into indices, strictly adhering to the English source structure. Example: 'Sentence 1 to 14. Sentence 2 to 15. \\n in 16. Speakers split in 17'. Do not explain, just map. Write this in the "mapping_plan" field."""

STEP_CONTEXT_PRIMING_EN = """Step {n}: Write a short summary of what is happening in the plot right now in the summary field. This will help you get into context before you start translating."""

def build_srt_split_rules(profile: LanguageProfile) -> str:
    return f"""Step {{n}}: Line Breaks (\\n) - Critical Requirement: 
1. A subtitle cannot contain more than {profile.max_words_per_line} words in a single line. If the translation is long, you must split it into two short, equally balanced lines using the \\n character. You are allowed (and required) to add the \\n inside formatting tags (e.g.: <i>text... \\n ...text</i>).
2. Two-Speaker Rule: If a subtitle contains a dialogue between two people (indicated by two hyphens -), you must split the subtitle into two lines using \\n so that each speaker gets their own line."""

STEP_FINAL_SRT_EN = """Step {n}: Enter the split and final text into the "translated_srt" object. **You must return a JSON map (Dictionary) where the keys are exactly the same numerical indices you received in the input, and the values are the final translations into {target_lang}**. Ensure speaker names (like 'PROBST:' or 'JEFF:' etc.) are completely removed and not translated."""

STEP_METADATA_UPDATE_EN = """Step {n}: Update the Metadata for the next batch. Fill the 'last_speaker_info' and 'continuity_note' fields based on the text you just translated. **Warning: Do not copy the instructional sentences in quotes (e.g., 'name of speaker...') into the output! You must replace them with actual information from the episode.**"""

STEP_SELF_AUDIT_EN = """Step {n}: Quality Control and Cross-Reference (Self-Audit)
Before closing the JSON, carefully scan the translated_srt object against the source list.
You must answer the following questions to yourself:
- Do all indices exist? Ensure every index number that appeared in the input also appears in the output.
- Are there duplicates? Check if a certain text appears twice under different indices.
- Are there omissions? Ensure all information from the source found its place in the final translation.
- Technical validity: Ensure you did not use incorrect slashes (like \\/) and only used \\n to split lines."""

BASE_TECHNICAL_RULES_EN = """
### [IDX_TECH]. Technical Rules and Visual Formatting (CRITICAL) ###
- Gender Tracking: Carefully track the speakers' gender throughout the batch. If multiple consecutive lines belong to the same speaker (or talk about the same character from the dictionary), you must maintain the exact same gender for adjectives and verbs. Do not switch gender mid-paragraph.
- Translation Boundaries: Translate ONLY the values appearing in the JSON dictionary under [Translation Blocks - JSON]. Under no circumstances should you include text found in the context blocks in the translation.
- 1:1 Rule (Key Map Accuracy): You must return in 'translated_srt' ALL keys (indices) that appeared in the input. Do not omit any key and do not add new keys.
- No Source Language: Do not leave words in {source_lang} in the final translation (except for brand names or acronyms without accepted translation, like CNN or CBS). Critical Exception: When a single English letter appears to describe a shape or object (e.g., The "I" piece, V-shaped), you must transliterate the letter's name to {target_lang}. Never leave the English letters in the output.
"""

RTL_SPECIFIC_RULES_EN = """
- Conjunction Rule (Critical): In {target_lang}, certain conjunctions must be attached as a prefix to the next word without a space. If the source line ends with a conjunction and the sentence continues, you must attach the conjunction prefix to the beginning of the first word on the next line. Preserving speech pauses (Cliffhangers) with dashes or ellipses at the end of the line is required.
"""

CLEANUP_RULES_EN = """
### [IDX_CLEAN]. Cleanup and Formatting Rules (MUST apply to final JSON output) ###
1. Delete Speaker Labels: Completely delete speaker identification tags that appear at the beginning of a subtitle and end with a colon (e.g., "PROBST:", "JEFF:"). You must ensure the speaker's name does not remain in the final translation. Warning: If a name is written as a natural part of the sentence (e.g., "-Julie drops"), do not delete it.
2. Clean Sound Elements (SDH): Delete sound descriptions in brackets [] or () (e.g.: [cheering], (coughs)). **Important:** If the text inside the parentheses is spoken dialogue (e.g., whispering), you must translate it and keep the parentheses. If the line contains only a sound description, return an empty string "".
3. Line Breaks (\\n): You must split long sentences! If the translated text for a specific index exceeds {max_words_per_line} words, you must use the `\\n` character in a syntactically logical place (after a comma, period, or conjunction) to divide it into two lines. It is permitted and encouraged to split inside formatting tags (e.g., inside <i>).
4. Quantitative Audit (Audit): It is strictly forbidden to "invent" text to fill indices or to duplicate text from a previous index.
"""

def build_workflow_steps(profile: LanguageProfile) -> list[str]:
    """Returns ordered list of workflow step instructions in English."""
    steps = [
        STEP_READ_CONTEXT_EN,
        STEP_CONTEXT_PRIMING_EN,
    ]
    # We will assume use_scratchpad is passed down or always true here, 
    # but the engine will filter these out if needed.
    # We'll just build all of them, and translation_engine will use them.
    # Actually, we can return the template strings, and the engine formats them.
    return []

def get_workflow_step_templates(profile: LanguageProfile, use_scratchpad: bool) -> list[str]:
    """Returns the unformatted workflow templates."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_workflow_steps:
            nw = profile.native_workflow_steps
            steps = [nw['read_context'], nw['priming']]
            if use_scratchpad:
                steps += [nw['draft'], nw['mapping']]
            steps += [
                nw['split_rules'].replace("{max_words}", str(profile.max_words_per_line)),
                nw['final_srt'],
                nw['metadata'],
                nw['audit']
            ]
            return steps
            
    # Always fall back to English if no native instructions provided or enabled
    return get_workflow_step_templates_en(profile, use_scratchpad)

def get_workflow_step_templates_en(profile: LanguageProfile, use_scratchpad: bool) -> list[str]:
    """Internal helper to build English workflow templates."""
    steps = [STEP_READ_CONTEXT_EN, STEP_CONTEXT_PRIMING_EN]
    if use_scratchpad:
        steps += [STEP_CONTINUOUS_DRAFT_EN, STEP_MAPPING_PLAN_EN]
    steps += [
        build_srt_split_rules(profile),
        STEP_FINAL_SRT_EN.replace("{target_lang}", profile.target_lang),
        STEP_METADATA_UPDATE_EN,
        STEP_SELF_AUDIT_EN
    ]
    return steps

def build_technical_rules(profile: LanguageProfile) -> str:
    """Assembles the technical rules block for the given language pair."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_technical_rules:
            return profile.native_technical_rules.replace("{max_words}", str(profile.max_words_per_line))
            
    # Always fall back to English if no native rules provided or enabled
    return build_technical_rules_en(profile)

def build_technical_rules_en(profile: LanguageProfile) -> str:
    """Internal helper to build English technical rules."""
    rules = [BASE_TECHNICAL_RULES_EN.replace("{source_lang}", profile.source_lang).replace("{target_lang}", profile.target_lang).strip()]
    if profile.target_is_rtl:
        rules.append(RTL_SPECIFIC_RULES_EN.replace("{target_lang}", profile.target_lang).strip())
    rules.append(CLEANUP_RULES_EN.replace("{max_words_per_line}", str(profile.max_words_per_line)).strip())
    rules.append(RULE_NO_ENGLISH_EN.replace("{source_lang}", profile.source_lang).replace("{target_lang}", profile.target_lang).strip())
    return "\n\n".join(rules)

def get_user_prompt_prefix(profile: LanguageProfile) -> str:
    """Returns the localized user prompt prefix."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_user_prompt_prefix:
            return profile.native_user_prompt_prefix
    
    return f"You are now translating the following batch. Remember: The output must be in {profile.target_lang} only."

def get_special_instructions_header(profile: LanguageProfile) -> str:
    """Returns the localized special instructions header."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_special_instructions_header:
            return profile.native_special_instructions_header
    return "### Special Instructions for this Batch (Your Responsibility!) ###"

def get_technical_rules_header(profile: LanguageProfile) -> str:
    """Returns the localized technical rules header."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_technical_rules_header:
            return profile.native_technical_rules_header
    return "### Mandatory Technical Rules ###"

def get_exact_count_rule(profile: LanguageProfile, expected_count: int) -> str:
    """Returns the localized exact count rule."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_exact_count_rule:
            return profile.native_exact_count_rule.replace("{expected_count}", str(expected_count))
    return f"1. Exact Count: **You must return exactly {expected_count} keys in the 'translated_srt' object.**"

def get_exact_indices_rule(profile: LanguageProfile, indices: list[str]) -> str:
    """Returns the localized exact indices rule."""
    indices_str = ', '.join(indices)
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_exact_indices_rule:
            return profile.native_exact_indices_rule.replace("{indices}", indices_str)
    return f"2. Exact Indices: Use EXACTLY the following indices as keys: {indices_str}."

def get_do_not_translate_rule(profile: LanguageProfile) -> str:
    """Returns the localized do-not-translate rule."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_do_not_translate_rule:
            return profile.native_do_not_translate_rule
    return '3. **DO NOT translate and DO NOT include** any word appearing in the "Context" blocks (in any field).'

def get_tag_rule(profile: LanguageProfile) -> str:
    """Returns the localized tag preservation rule."""
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_tag_rule:
            return profile.native_tag_rule.replace("{max_words}", str(profile.max_words_per_line))
    
    return f"4. Formatting Tags: Keep tags like <i> or <font color=\"...\"> exactly in their original position. Do not translate technical words (like 'color') and do not delete them. **Important: You are allowed (and required) to add a line break `\\n` inside tags (e.g. `<i>text...\\n...text</i>`) to maintain the {profile.max_words_per_line} words per line rule.** Ensure color values are surrounded by quotes."





JSON_SCHEMA_TEMPLATE = """
{
  "thought_process": "<thought process, 2-3 sentences max>",
  "summary": "<brief summary of what is happening in the plot right now>",
  "continuous_translation_draft": "<insert the entire translation as a single continuous text paragraph>",
  "mapping_plan": "<insert the mapping plan against the index distribution here. e.g.: 'sentence 1 to 14'>",
  "translated_srt": {
    "1": "<the final {target_lang} translation for index 1 relevant to the batch>",
    "2": "<the final {target_lang} translation for index 2 relevant to the batch>"
  },
  "last_speaker_info": "<speaker name (M/F) speaking to target (M/F/Unknown/Camera)>",
  "continuity_note": "<continuity instruction for the next batch, leave empty if none>"
}
"""

JSON_SCHEMA_LITE = """
{
  "thought_process": "<thought process, 2-3 sentences max>",
  "summary": "<brief summary of what is happening in the plot right now>",
  "translated_srt": {
    "1": "<the final {target_lang} translation for index 1 relevant to the batch>",
    "2": "<the final {target_lang} translation for index 2 relevant to the batch>"
  },
  "last_speaker_info": "<speaker name (M/F) speaking to target (M/F/Unknown/Camera)>",
  "continuity_note": "<continuity instruction for the next batch, leave empty if none>"
}
"""

def get_json_schema(profile, is_lite: bool = False) -> str:
    """Returns the profile-specific JSON schema if requested, otherwise formats the English default."""
    if getattr(profile, 'use_native_instructions', False):
        if is_lite and profile.native_json_schema_lite:
            return profile.native_json_schema_lite
        if not is_lite and profile.native_json_schema:
            return profile.native_json_schema
            
    # Fallback to English generic schemas
    base_schema = JSON_SCHEMA_LITE if is_lite else JSON_SCHEMA_TEMPLATE
    return base_schema.replace("{target_lang}", profile.target_lang)

def build_judge_system_prompt(profile) -> str:
    if getattr(profile, 'use_native_instructions', False):
        if profile.native_judge_prompt:
            return profile.native_judge_prompt
            
    # Always fall back to English if no native instructions provided or enabled
    return build_judge_system_prompt_en(profile)

def build_judge_system_prompt_en(profile: LanguageProfile) -> str:
    """Internal helper to build English judge system prompt."""
    return f"""You are a ruthless QA auditor for {profile.target_lang} subtitle translations.
Source language: {profile.source_lang}. Target language: {profile.target_lang}.

### REJECTION RULES (reject if ANY is true): ###
1. Text Omission: Source has meaningful text (>2 words) but translation is empty.
2. Speaker Label Leak: Speaker tag remains in translation (e.g., "JEFF:" or its transliteration).
3. SDH Leak: Sound descriptors (e.g., [music], (coughs)) remain in translation.
   EXCEPTION: Dialogue in parentheses (e.g., whispers) is valid.
4. Source Language Leak: {profile.source_lang} text appears in the translation without justification.
   EXCEPTION: Internationally recognized acronyms (CNN, NASA) and brand names are acceptable.
5. Tag Mismatch: HTML/formatting tags (like <i>) do not match the source.

### CRITICAL ANTI-HALLUCINATION RULES: ###
- Ignore formatting tags and hex color codes when checking for {profile.source_lang} leaks.
- Not all words ending in a colon are speaker names. "Date:", "Chapter:" are valid content.
- Verify errors exist in the {profile.target_lang} text, NOT the {profile.source_lang} source.
- Do NOT hallucinate errors. Check EACH index individually.
- If the batch is completely flawless, set `is_rejected: false` and leave error descriptions empty.
- If even one tiny error is found, set `is_rejected: true` and detail it.
- **You must respond entirely in English.** Do not use {profile.target_lang} in your thought process.
"""
