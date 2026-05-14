import re
import difflib

# Pre-compiled Regex Patterns for Performance Optimization
RE_RTL_ESCAPE_BASE = re.compile(r'\s*\\+[n]\s*')
RE_HTML_TAGS = re.compile(r'^((?:<[^>]+>)*)(.*?)((?:<[^>]+>)*)$')
RE_PUNCTUATION_END = re.compile(r'([.,?!\\\'\":;♪]+)$')
RE_PUNCTUATION_START = re.compile(r'^([.,?!\\\'\":;♪]+)')
RE_MUSIC_TRIM = re.compile(r"[-.\s]*")
RE_TRAILING_COMMA_OBJ = re.compile(r',\s*\}')
RE_TRAILING_COMMA_ARR = re.compile(r',\s*\]')
RE_MISSING_COLON = re.compile(r'([{,])\s*"([^"\\:]+)"\s*(?=[,}\]])')
RE_TRUNCATED_KEY = re.compile(r'([{,])\s*"[^"\\:]+"$')
RE_HEBREW_ABBR_QUOTE = re.compile(r'([\u05d0-\u05ea])"([\u05d0-\u05ea])')
RE_NON_PRINTABLE = re.compile(r'[\x00-\x1F\x7F]')
RE_INVALID_ESCAPE = re.compile(r'(\\["\\/bfnrtu]|\\u[0-9a-fA-F]{4})|\\')
RE_SDH_CLEANER = re.compile(r'\[.*?\]|\(.*?\)|♪|<.*?>|\{.*?\}')
# RE_FOREIGN_CHARS: Matches characters that are neither standard ASCII nor within the target language range.
# This is used for heuristic validation and cleanup.
RE_FOREIGN_CHARS_BASE = re.compile(r'[^\x00-\x7F\u200E\u200F\u202A-\u202C\u2018-\u201D\u2026\u2013\u2014\u20AA\u20AC\u00A3\xA0\xB0♪♫]')
RE_ENGLISH_WORDS = re.compile(r'[a-zA-Z]+')
RE_EXEMPT_ACRONYM = re.compile(r'[A-Z]{2,}')
RE_EXEMPT_SPELLED = re.compile(r'\b[A-Z](-[A-Z])+\b')
RE_SPEAKER_NAME = re.compile(r'(?m)^(?:\s*-\s*)?([^:\n]{1,15}):')
RE_ECHO_CLEANER = re.compile(r'[.,!?:;♪\-_]+')
RE_SDH_BRACKETS = re.compile(r'[\[(].*?[\])]')


def fix_rtl(text, is_rtl=True, profile=None):
    if not is_rtl: return text
    if not text: return text
    
    # Step 0: Clean up textual escape characters that the LLM tends to produce in JSON.
    # We turn them into real newlines so that the following split will recognize them.
    re_escape = re.compile(profile.newline_regex) if profile else RE_RTL_ESCAPE_BASE
    text = re_escape.sub('\n', str(text))
    
    lines = text.split('\n')
    fixed_lines = []
    for line in lines:
        clean_line = line.strip()
        
        # Skip empty lines, indices, timestamps or lines starting with technical tags (like {anX})
        if not clean_line or clean_line.isdigit() or '-->' in clean_line or clean_line.startswith('{'):
            fixed_lines.append(line)
            continue
            
        is_dialogue = clean_line.startswith('-')
        if is_dialogue: clean_line = re.sub(r'^-\s*', '', clean_line)
        
        # HTML Tag handling (e.g. <i>)
        match = RE_HTML_TAGS.match(clean_line)
        if match:
            leading_tags, inner_content, trailing_tags = match.group(1), match.group(2).strip(), match.group(3)
        else:
            leading_tags, inner_content, trailing_tags = "", clean_line.strip(), ""
            
        # Punctuation reversal logic for RTL
        punctuation_search = RE_PUNCTUATION_END.search(inner_content)
        if punctuation_search:
            punctuation = punctuation_search.group(1)
            main_text = inner_content[:-len(punctuation)].strip()
            # Reverse the order: Punctuation moves to the start (viewed from right-to-left it will appear at the end)
            inner_content = f"{punctuation}{main_text}"
            
        new_line = f"{leading_tags}{inner_content}{trailing_tags}"
        
        # If it's a dialogue, the dash moves to the end of the line (which appears at the start on the right)
        if is_dialogue: new_line = f"{new_line} -"
        
        fixed_lines.append(new_line)
        
    return '\n'.join(fixed_lines)

def unfix_rtl(text, is_rtl=True):
    """
    Undoes 'Visual RTL' logic to restore a 'Logical RTL' string for web browsers.
    Moves punctuation from the start back to the end, and dialogue dashes to the start.
    """
    if not is_rtl: return text
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
        punc_match = RE_PUNCTUATION_START.match(clean_line)
        if punc_match:
            punctuation = punc_match.group(1)
            main_text = clean_line[len(punctuation):].strip()
            clean_line = f"{main_text}{punctuation}"
            
        unfixed_lines.append(clean_line)
    return '\n'.join(unfixed_lines)

def strip_music_glyphs_batch(target_dict):
    """
    1. Removes music note symbols.
    2. Wipes lines that contain only punctuation/notes/SDH artifacts.
    This prevents 'Dangling Hyphen' or 'Music Note Only' Judge rejections.
    """
    if not isinstance(target_dict, dict):
        return
        
    for k, v in list(target_dict.items()):
        if isinstance(v, str):
            # First, do the standard character cleaning
            cleaned = v.replace("♪", "").strip()
            
            # Now, apply the 'Empty String' logic:
            # If the resulting string is just a hyphen, a dot, or empty...
            if RE_MUSIC_TRIM.fullmatch(cleaned):
                target_dict[k] = ""
            else:
                target_dict[k] = cleaned

def pre_repair_json(raw_res):
    """
    Attempts to fix common LLM JSON errors locally before parsing.
    Handles: Code blocks, trailing commas, broken keys (missing colons), and truncated JSON.
    """
    if not raw_res: return ""
    cleaned = raw_res.strip()
    
    # 1. Remove code blocks ```json ... ```
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
        
    # 2. Fix trailing commas in objects or arrays
    cleaned = RE_TRAILING_COMMA_OBJ.sub('}', cleaned)
    cleaned = RE_TRAILING_COMMA_ARR.sub(']', cleaned)
    
    # 2.1 Escape raw double-quotes in Hebrew abbreviations (Gershayim, e.g. ס"מ -> ס\"מ)
    cleaned = RE_HEBREW_ABBR_QUOTE.sub(r'\1\\"\2', cleaned)
    
    # 2.2 Smart Schema-Aware Double-Quote Hardening
    # Finds known text fields and escapes unescaped inner double quotes that break JSON structure.
    for key in ["current_he", "replacement_he", "reason"]:
        pattern = rf'("{key}"\s*:\s*")(.*?)("\s*(?=,\s*"(?:index|current_he|replacement_he|reason|severity|confidence)"|\s*}}))'
        def escape_inner(match):
            return match.group(1) + re.sub(r'(?<!\\)"', r'\\"', match.group(2)) + match.group(3)
        cleaned = re.sub(pattern, escape_inner, cleaned, flags=re.DOTALL)
    
    # 3. Fix broken keys (Missing Colons/Values)
    # Search for a key (string) followed by a comma or bracket, without a colon before it.
    # Pattern: (Start of object or comma) + whitespace + "key" + whitespace + (?= comma or end-brace)
    # This specifically fixes: "key", -> "key": null,
    cleaned = RE_MISSING_COLON.sub(r'\1 "\2": null', cleaned)
    
    # 4. Handle Truncated JSON
    # If the LLM stopped mid-stream, attempt to close braces/brackets to salvage partial data.
    open_braces = cleaned.count('{') - cleaned.count('}')
    open_brackets = cleaned.count('[') - cleaned.count(']')
    
    if open_braces > 0 or open_brackets > 0:
        # If truncation happened mid-key or mid-value (ends with comma or quote)
        if cleaned.endswith(','):
            cleaned = cleaned.rstrip(',')
        elif cleaned.endswith('"'):
            # If it ends with a quote, check if it's a broken key at the end of the truncated JSON
            # If before these quotes there's a sequence that looks like the start of an object or a comma,
            # attempt to add : null
            if RE_TRUNCATED_KEY.search(cleaned):
                cleaned += ': null'
        
        # Close brackets/braces in reverse order
        cleaned += ']' * max(0, open_brackets)
        cleaned += '}' * max(0, open_braces)


    # 5. Fix invalid escape sequences: Keep valid JSON escapes untouched, escape any lone backslashes.
    def _escape_replacer(match):
        if match.group(1):
            return match.group(1)
        return r'\\'
    cleaned = RE_INVALID_ESCAPE.sub(_escape_replacer, cleaned)
    
    # 6. Clean non-printable and control characters
    cleaned = RE_NON_PRINTABLE.sub('', cleaned)
    
    return cleaned



def check_heuristics(eng_dict, target_dict, illegal_labels=None, profile=None):
    """
    Local validation check (Heuristics) without the need for AI.
    Returns (is_suspicious: bool, reason: str, skip_judge: bool).

    skip_judge=True when there are square brackets [ ] in the translation, or more than X words in a single target line —
    in these cases immediate retry without Judge. SDH leakage in parentheses or ♪ triggers the judge
    when the above conditions are not met.
    """
    if illegal_labels is None:
        illegal_labels = []
    
    reasons = []
    native_reasons = []
    use_native = profile and getattr(profile, 'use_native_instructions', False)
    
    def get_msg(key, fallback, **kwargs):
        if use_native and profile and profile.native_audit_messages and key in profile.native_audit_messages:
            return profile.native_audit_messages[key].format(**kwargs)
        return fallback.format(**kwargs)
        
    has_bracket_sdh = False
    has_overlong_target_line = False
    has_expansion_anomaly = False
    
    total_eng_words = 0
    total_target_words = 0
    
    for idx, eng_text in eng_dict.items():
        target_text = str(target_dict.get(idx, "")).strip()
        
        # 0. Critical upgrade: Remove SDH and tags before word count
        # Removes: [SDH], (SDH), ♪, and HTML tags <...>
        eng_text_clean = RE_SDH_CLEANER.sub(' ', eng_text)
        target_text_clean = RE_SDH_CLEANER.sub(' ', target_text)
        
        # Count words (or characters for CJK) for batch density and single-block ratio
        eng_wc = len([w for w in eng_text_clean.split() if any(c.isalnum() for c in w)])
        
        if profile and profile.use_char_ratio:
            # For CJK, count characters that are alphanumeric or in the target script ranges
            # We don't use split() because CJK languages often don't use spaces.
            target_wc = len([c for c in target_text_clean if not c.isspace() and c.isalnum()])
            if target_wc == 0 and target_text_clean.strip():
                # Fallback: if no alphanumeric (e.g. only ideographs), count non-whitespace
                target_wc = len(target_text_clean.strip())
        else:
            target_wc = len([w for w in target_text_clean.split() if any(c.isalnum() for c in w)])

        total_eng_words += eng_wc
        total_target_words += target_wc
        
        if eng_wc > 0:
            # Special case: If single English word > 12 chars, use char ratio instead of word ratio
            if eng_wc == 1 and len(eng_text_clean.strip()) > 12:
                block_ratio = len(target_text) / len(eng_text_clean.strip())
            else:
                block_ratio = target_wc / eng_wc
                
            # Dynamic ratios based on profile
            ratio_base = profile.word_ratio_vs_english if profile else 0.75
            
            # CJK expansion thresholds are more relaxed because characters are counted
            max_v_mult = 6.0 if (profile and profile.use_char_ratio) else 4.0
            max_h_mult = 4.0 if (profile and profile.use_char_ratio) else 2.66
            
            if block_ratio > (ratio_base * max_v_mult):
                reasons.append(f"Verbosification at index {idx} ({block_ratio:.1f}x)")
                native_reasons.append(get_msg("heur_verbosification", "IDX:{idx}|Significant translation length anomaly (Verbosification) detected compared to source ({block_ratio:.1f}x).", idx=idx, block_ratio=block_ratio))
                has_expansion_anomaly = True
            elif block_ratio > (ratio_base * max_h_mult):
                reasons.append(f"High expansion at index {idx} ({block_ratio:.1f}x)")
                native_reasons.append(get_msg("heur_high_expansion", "IDX:{idx}|Translation is unusually long compared to source (High expansion) ({block_ratio:.1f}x).", idx=idx, block_ratio=block_ratio))
            elif block_ratio < (ratio_base * 0.46) and eng_wc >= 6:
                reasons.append(f"Extreme omission at index {idx} ({block_ratio:.1f}x)")
                native_reasons.append(get_msg("heur_extreme_omission", "IDX:{idx}|Suspected omission - translation is significantly shorter than source ({block_ratio:.1f}x). Ensure no plot information was omitted.", idx=idx, block_ratio=block_ratio))

        # 1. "Silent Skip" check (Target empty but Eng not)
        # If after cleaning SDH and punctuation nothing is left - it's a pure SDH index
        is_pure_sdh = len(RE_MUSIC_TRIM.sub('', eng_text_clean)) == 0

        if not target_text and eng_text.strip():
            if not is_pure_sdh:
                # Flag as 'Silent Skip' ONLY IF the clean source_text contains more than 2 words
                if eng_wc > 2 or len(eng_text_clean.strip()) > 12:
                    reasons.append(f"Silent Skip at index {idx}")
                    native_reasons.append(get_msg("heur_silent_skip", "IDX:{idx}|Silent Skip detected - The target text is empty even though the source has text.", idx=idx))

        # 3. Line length in words/chars (Exactly max_words + 1 -> Judge; more than that -> retry without Judge)
        sub_lines = target_text.split('\n')
        max_words = profile.max_words_per_line if profile else 8
        label = "chars" if (profile and profile.use_char_ratio) else "words"
        for line in sub_lines:
            # Smart count: ignore standalone symbols like '-' or '♪'
            if profile and profile.use_char_ratio:
                wc = len([c for c in line if not c.isspace() and c.isalnum()])
                if wc == 0 and line.strip(): wc = len(line.strip())
            else:
                words = [w for w in line.split() if any(c.isalnum() for c in w)]
                wc = len(words)
            
            if wc == max_words + 1:
                reasons.append(f"{wc}-{label} line at index {idx}")
                native_reasons.append(get_msg("heur_exact_word_match", "IDX:{idx}|Line contains exactly {wc} {words_label}. Ensure no length violation or added information.", idx=idx, wc=wc, words_label=(profile.overlong_word if profile else "words")))
            elif wc > max_words + 1:
                reasons.append(f"More than {max_words + 1} {label} in a line at index {idx}")
                native_reasons.append(get_msg("heur_line_too_long", "IDX:{idx}|Line is {overlong_phrase} (over {max_words_plus_1} {words_label}).", idx=idx, overlong_phrase=(profile.overlong_phrase if profile else "too long"), max_words_plus_1=(max_words + 1), words_label=(profile.overlong_word if profile else "words")))
                has_overlong_target_line = True

        # 4. Prohibited content check: Speaker names, SDH, Source Lang, Foreign chars
        if target_text:  # Only check content if there IS text
            
            # Foreign character check (e.g. Chinese, Russian, etc.) - uses tag-cleaned text
            if profile:
                foreign_chars = profile.build_allowed_charset().findall(target_text_clean)
            else:
                foreign_chars = RE_FOREIGN_CHARS_BASE.findall(target_text_clean)
            
            if foreign_chars:
                reasons.append(f"STRICT: Foreign characters found in {idx} ({''.join(set(foreign_chars))})")
                native_reasons.append(get_msg("heur_foreign_chars", "IDX:{idx}|Foreign characters or unknown symbols found ({chars}).", idx=idx, chars=''.join(set(foreign_chars))))
            
            # Only check for explicit English leak if source is English and target is NOT Latin script
            if (not profile) or (profile.source_lang_code == 'en' and not profile.target_uses_latin_script):
                found_eng = RE_ENGLISH_WORDS.findall(target_text_clean)
                if found_eng:
                    # Exempt: all-caps acronyms (CNN, CBS), spelled-out letters (S-I-F-U)
                    actual_errors = []
                    for word in found_eng:
                        is_exempt = bool(
                            RE_EXEMPT_ACRONYM.fullmatch(word) or
                            RE_EXEMPT_SPELLED.search(word)
                        )
                        if not is_exempt:
                            actual_errors.append(word)
                    
                    if actual_errors:
                        err_str = ", ".join(set(actual_errors))
                        reasons.append(f"STRICT: Source language letters found in {idx} ({err_str})")
                        native_reasons.append(get_msg("heur_source_lang_words", "IDX:{idx}|Source language words found in index {idx} ({err_str}). You must translate or delete them!", idx=idx, err_str=err_str))


            # Refined Speaker Name Check (Checks every line, including dialogue dashes)
            # Looks for: [Optional -] [Name 1-15 chars] :
            speaker_match = RE_SPEAKER_NAME.search(target_text)
            if speaker_match:
                found_name = speaker_match.group(1).strip()
                # Absolute prohibited labels (Dynamic from sysprm)
                if found_name.lower() in [val.lower() for val in illegal_labels]:
                    reasons.append(f"STRICT: Illegal label detected in {idx} ('{found_name}')")
                    native_reasons.append(get_msg("heur_illegal_label", "IDX:{idx}|Host name or illegal label detected ('{found_name}:') at index {idx}. It is strictly forbidden to include speaker or host names. Delete it immediately!", idx=idx, found_name=found_name))
                # General name labels
                else:
                    is_exempt = False
                    if profile and profile.use_native_instructions and profile.native_exempt_labels:
                        if found_name.lower() in [val.lower() for val in profile.native_exempt_labels]:
                            is_exempt = True
                    elif found_name.lower() in ["note", "attention", "p.s"]:
                         is_exempt = True
                    
                    if not is_exempt:
                        reasons.append(f"Speaker name found in {idx} ('{found_name}')")
                        native_reasons.append(get_msg("heur_speaker_name", "IDX:{idx}|Speaker name detected ('{found_name}:') at index {idx}. Speaker names must be deleted!", idx=idx, found_name=found_name))

            if '[' in target_text or ']' in target_text:
                reasons.append(f"Square bracket SDH found in {idx}")
                has_bracket_sdh = True
                native_reasons.append(get_msg("heur_square_bracket_sdh", "IDX:{idx}|Square brackets (SDH) found at index {idx}. Do not include facial expressions or background sounds.", idx=idx))

            # Flag parentheses/music ONLY if text exists (guards against your empty SDH lines)
            if any(c in target_text for c in "()♪"):
                reasons.append(f"Parenthesis or music SDH found in {idx}") 
                native_reasons.append(get_msg("heur_parentheses_sdh", "IDX:{idx}|Parentheses or music symbols (SDH) found at index {idx}.", idx=idx))           

        # 5. Robot Talk check (AI Filler)
        robot_phrases = ["here is the translation", "here is the", "translation:", "the following subtitle"]
        if profile and profile.use_native_instructions and profile.native_robot_phrases:
            robot_phrases = profile.native_robot_phrases
            
        if any(p in target_text for p in robot_phrases):
            reasons.append(f"Robot talk phrases in {idx}")
            native_reasons.append(get_msg("heur_robot_talk", "IDX:{idx}|'Robot Talk' pattern (filler words) detected at index {idx}.", idx=idx))

        # 6. Tag Integrity check
        if target_text.count('<') != target_text.count('>') or target_text.count('<i>') != target_text.count('</i>'):
            reasons.append(f"Tag mismatch in {idx}")
            native_reasons.append(get_msg("heur_tag_mismatch", "IDX:{idx}|Imbalance in HTML tags or music symbols compared to source at index {idx}.", idx=idx))
            
        # 7. Glitch check (suspiciously long words) - using clean text
        words = target_text_clean.split()
        if any(len(w) > 16 for w in words):
            reasons.append(f"Suspiciously long word in {idx}")
            native_reasons.append(get_msg("heur_glitch_long_word", "IDX:{idx}|Highly unusual character sequences detected at index {idx}.", idx=idx))


    # 8. Semantic Echo check between adjacent subtitles
    # Checks if the end of one subtitle repeats at the start of the next (common LLM hallucination)
    indices = sorted(eng_dict.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
    for i in range(len(indices) - 1):
        idx1, idx2 = indices[i], indices[i+1]
        h1 = str(target_dict.get(idx1, "")).strip().split('\n')
        h2 = str(target_dict.get(idx2, "")).strip().split('\n')
        
        if h1 and h2:
            # Clean the last line of 1 and first line of 2 for comparison (no punctuation/symbols)
            last_line = RE_ECHO_CLEANER.sub('', h1[-1]).strip()
            first_line = RE_ECHO_CLEANER.sub('', h2[0]).strip()
            
            # Check for duplication of a significant phrase (3+ words)
            wc_last = len([w for w in last_line.split() if any(c.isalnum() for c in w)])
            if last_line == first_line and wc_last >= 3:
                # Check if the duplication exists in the source:
                # Case A: The boundary between blocks - last line of 1 is same as first line of 2
                # Case B: Any line from block 1 appearing in block 2 (e.g. crowd chanting same phrase)
                # Case C: Block 2 itself contains repeated lines
                e1 = [RE_ECHO_CLEANER.sub('', l).strip().lower() for l in str(eng_dict.get(idx1, "")).strip().split('\n')]
                e2 = [RE_ECHO_CLEANER.sub('', l).strip().lower() for l in str(eng_dict.get(idx2, "")).strip().split('\n')]
                
                e_repeated = False
                if e1 and e2:
                    # Case A: last line of block 1 == first line of block 2
                    if e1[-1] and e2[0] and e1[-1] == e2[0] and len(e1[-1].split()) >= 2:
                        e_repeated = True
                    # Case B: any line from block 1 appears anywhere in block 2 (chant/crowd repetition)
                    elif any(l1 and l1 in e2 and len(l1.split()) >= 2 for l1 in e1):
                        e_repeated = True
                    # Case C: block 2 itself has internal repetition (same line appears twice)
                    elif len(e2) > 1 and len(set(l for l in e2 if l)) < len([l for l in e2 if l]):
                        e_repeated = True
                
                if not e_repeated:
                    reasons.append(f"Semantic Echo between {idx1} and {idx2}")
                    native_reasons.append(get_msg("heur_semantic_echo", "IDX:{idx1},{idx2}|Semantic text duplication (Echo) detected between adjacent indices. Ensure you didn't repeat a sentence.", idx1=idx1, idx2=idx2))

    # 9. Batch Density check
    if total_eng_words > 0:
        batch_ratio = total_target_words / total_eng_words
        # CJK (char-based) naturally has higher ratio vs English words
        max_batch = 1.6 if (profile and profile.use_char_ratio) else 1.3
        if batch_ratio < 0.4 or batch_ratio > max_batch:
            reasons.append(f"Batch Density anomaly ({batch_ratio:.2f}x)")
            native_reasons.append(get_msg("heur_batch_density", "GLOBAL|Word ratio for the entire batch is significantly anomalous ({batch_ratio:.2f}x).", batch_ratio=batch_ratio))

    skip_judge = has_bracket_sdh or has_overlong_target_line or has_expansion_anomaly or any("STRICT:" in r for r in reasons)

    if reasons:
        return True, "; ".join(reasons), "; ".join(native_reasons), skip_judge
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
    # Reassemble tokens with a newline at the selected boundary
    part1 = " ".join(tokens[:split_token_idx + 1])
    part2 = " ".join(tokens[split_token_idx + 1:])
    
    return f"{part1}\n{part2}"

def pre_audit_source(eng_dict, illegal_labels=None, profile=None):
    """
    Scans English source text for potential translation pitfalls (SDH, names) 
    BEFORE sending to the LLM. Returns a list of (index, message) tuples.
    """
    if illegal_labels is None:
        illegal_labels = []
        
    warnings = []
    use_native = profile and getattr(profile, 'use_native_instructions', False)
    
    def get_msg(key, fallback, **kwargs):
        if use_native and profile.native_audit_messages and key in profile.native_audit_messages:
            return profile.native_audit_messages[key].format(**kwargs)
        return fallback.format(**kwargs)
    
    for idx, txt in eng_dict.items():
        if not txt: continue
        
        # 1. Look for Speaker Names (e.g., JEFF:, ROCKSROY:)
        speaker_match = RE_SPEAKER_NAME.search(txt)
        if speaker_match:
            found_name = speaker_match.group(1).strip()
            msg = get_msg("pre_speaker_name", "Speaker name ('{found_name}:') - Delete name, keep dialogue.", found_name=found_name)
            warnings.append((idx, msg))
            
        # 2. Look for SDH tags in brackets (e.g., [music], (coughs))
        sdh_match = RE_SDH_BRACKETS.search(txt)
        if sdh_match:
            content = sdh_match.group(0)
            msg = get_msg("pre_sdh_brackets", "SDH ({content}) - Delete sound, keep dialogue.", content=content)
            warnings.append((idx, msg))

        # 3. Look for Source Tag Mismatches (Extreme technical hardening)
        if txt.count('<') != txt.count('>') or txt.count('<i>') != txt.count('</i>'):
            msg = get_msg("pre_tag_mismatch", "Tag mismatch in source - Fix or ensure validity.")
            warnings.append((idx, msg))

        # 4. Look for Music symbols
        if "♪" in txt:
            msg = get_msg("pre_music_symbol", "Music symbol ♪ - Delete from translation.")
            warnings.append((idx, msg))
            
    return warnings


# Pre-compiled regexes for cleanup_failed_translation (module-level for performance)
_RE_HTML_STRIP   = re.compile(r'<[^>]+>')
_RE_LATIN_STRIP  = re.compile(r'[a-zA-Z]+(?![^{]*\})')  # Strips English letters EXCEPT those inside {tags}
_RE_SDH_NON_TARGET_GENERIC_HE = re.compile(r'[\[\(][^\u05d0-\u05ea\n\r]{0,60}[\]\)]')  # Hebrew fallback


def cleanup_failed_translation(target_text: str, eng_text: str, failure_reason: str, profile=None) -> str:
    """
    Attempts to salvage a failed Hebrew subtitle translation using a targeted
    cleanup pipeline. Called by the Bypass Intervention path when the AI fails
    3 consecutive times and manual intervention is disabled.

    Strategies applied (in order):
      1. Always:  Strip all HTML/formatting tags (<i>, <b>, <font ...>)
      2. Always:  Strip Latin characters (A-Z, a-z) — fixes English leak (only if target doesn't use Latin script)
      3. Always:  Strip SDH brackets [ ] / ( ) that contain no text in target script
      4. Always:  Normalize whitespace; drop blank lines
      5. Targeted: Verbosification → truncate to max 2 lines × max words
      6. Targeted: Echo → deduplicate repeated lines
      7. Targeted: Silent Skip / omission → if still empty, write a "[Missing Translation]" placeholder
      8. Safety:  If completely empty after all steps → "[...]"

    Args:
        target_text:    Last AI-produced target translation (may be garbled).
        eng_text:       Original English source (used for word-count placeholder).
        failure_reason: The heuristic/judge reason string from the audit.
        profile:        Optional LanguageProfile to adapt cleanup for other languages.

    Returns:
        Best-effort cleaned target string.
    """
    result = str(target_text or "")

    # 1. Strip HTML tags
    result = _RE_HTML_STRIP.sub('', result)

    # 2. Strip Latin characters (Only if target does not use Latin script)
    if not profile or not profile.target_uses_latin_script:
        result = _RE_LATIN_STRIP.sub('', result)

    # 3. Strip SDH brackets that have no target script content inside
    if profile:
        ranges_str = "".join([f"\\u{s:04x}-\\u{e:04x}" for s, e in profile.target_unicode_ranges])
        dynamic_sdh_pattern = rf'[\[\(][^{ranges_str}\n\r]{{0,60}}[\]\)]'
        result = re.sub(dynamic_sdh_pattern, '', result)
    else:
        result = _RE_SDH_NON_TARGET_GENERIC_HE.sub('', result)

    # 4. Normalize: collapse multiple spaces / tabs; drop blank lines
    result = re.sub(r'[ \t]+', ' ', result)
    lines = [l.strip() for l in result.split('\n') if l.strip()]
    result = '\n'.join(lines)

    # 5. Targeted: Verbosification — truncate to 2 lines of ≤ max words each
    reason_lower = failure_reason.lower()
    if 'verbosification' in reason_lower or 'high expansion' in reason_lower:
        trimmed = []
        max_w = profile.max_words_per_line if profile else 8
        for line in result.split('\n')[:2]:        # keep at most 2 lines
            words = line.split()
            trimmed.append(' '.join(words[:max_w]))    # max words per line
        result = '\n'.join(t for t in trimmed if t)

    # 6. Targeted: Echo — remove duplicate lines
    elif 'echo' in reason_lower:
        seen = []
        for line in result.split('\n'):
            if line not in seen:
                seen.append(line)
        result = '\n'.join(seen)

    # 7. Targeted: omission / silent skip — supply a labelled placeholder
    if (not result.strip()) and ('omission' in reason_lower or 'silent skip' in reason_lower):
        eng_wc = len([w for w in eng_text.split() if any(c.isalnum() for c in w)])
        missing_label = profile.native_missing_translation_label if profile else "Missing Translation"
        result = f"[{missing_label} — {eng_wc} words]"

    # 8. Final safety — guarantee non-empty output
    if not result.strip():
        result = "[...]"

    return result.strip()
