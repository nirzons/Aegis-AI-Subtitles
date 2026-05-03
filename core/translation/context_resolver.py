import os
import json
import re
from utils.srt_manager import parse_srt_blocks
from utils.app_utils import log

RE_SYS_IDX = re.compile(r'###\s*(\d+)\.')

def resolve_initial_context(config, log_queue, session_log_file):
    """
    Parses sys_file / srt_file, extracts SysPrm overrides, 
    calculates dynamic serial indices, and constructs the initial state.
    Returns:
       (profile, series_context, initial_context_str, context_state, 
        last_idx, illegal_labels, srt_content, ordered_srt_indices)
    """
    resume_mode = config["resume_mode"]
    sysprm_dir = config["sysprm_dir"]
    english_subs_dir = config["english_subs_dir"]
    
    profile = config.get("language_profile")
    if not profile:
        from utils.settings import SETTINGS
        profile = SETTINGS.get_active_profile()

    if resume_mode:
        checkpoint_data = config["checkpoint_data"]
        from core.session_manager import resolve_checkpoint_paths, restore_profile_from_checkpoint
        sys_file, srt_file = resolve_checkpoint_paths(checkpoint_data, sysprm_dir, english_subs_dir)
        restore_profile_from_checkpoint(profile, checkpoint_data)
        context_state = checkpoint_data['context_state']
    else:
        sys_file = os.path.join(sysprm_dir, config["sys_name"])
        srt_file = os.path.join(english_subs_dir, config["srt_name"])

    if resume_mode:
        if not os.path.exists(srt_file) or not os.path.exists(sys_file):
            log(log_queue, session_log_file, "❌ Error: Original files missing. Cannot resume.")
            raise RuntimeError("Original files missing. Cannot resume.")

    with open(sys_file, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
    clean_lines = [line for line in lines if not line.strip().startswith("//")]
    raw_sysprm = "".join(clean_lines).strip()

    ratios = list(profile.get_ratios(profile.source_lang_code))
    ratios_source = "Defaults"

    try:
        sysprm_json = json.loads(raw_sysprm)
        if "language" not in sysprm_json or "use_native_instructions" not in sysprm_json["language"]:
            log(log_queue, session_log_file, "❌ Error: SysPrm must be a JSON file and contain 'language': {'use_native_instructions': true/false}. Legacy files are not supported.")
            raise RuntimeError("Invalid SysPrm format")

        lang_cfg = sysprm_json["language"]
        if "source" in lang_cfg: profile.source_lang_code = lang_cfg["source"]
        if "target" in lang_cfg: profile.target_lang_code = lang_cfg["target"]
        profile.use_native_instructions = bool(lang_cfg["use_native_instructions"])
        mode_str = "Native" if profile.use_native_instructions else "English"
        log(log_queue, session_log_file, f"🌐 Mode: {mode_str} Instructions")

        if "max_words_per_line" in lang_cfg:
            profile.max_words_per_line = int(lang_cfg["max_words_per_line"])

        sysprm_overrode = False
        if "min_block_ratio" in lang_cfg:
            ratios[0] = float(lang_cfg["min_block_ratio"])
            sysprm_overrode = True
        if "max_block_ratio" in lang_cfg: 
            ratios[1] = float(lang_cfg["max_block_ratio"])
            sysprm_overrode = True
        if "batch_min_ratio" in lang_cfg: 
            ratios[2] = float(lang_cfg["batch_min_ratio"])
            sysprm_overrode = True
        if "batch_max_ratio" in lang_cfg: 
            ratios[3] = float(lang_cfg["batch_max_ratio"])
            sysprm_overrode = True

        if sysprm_overrode:
            ratios_source = "SysPrm Override"
            if not profile.direct_pair_ratios: profile.direct_pair_ratios = {}
            profile.direct_pair_ratios[profile.source_lang_code] = tuple(ratios)

        log(log_queue, session_log_file, 
            f"📊 Word Ratios ({ratios_source}): MinBlock={ratios[0]}, MaxBlock={ratios[1]}, MinBatch={ratios[2]}, MaxBatch={ratios[3]}")

        if "series_context" in sysprm_json:
            sc = sysprm_json["series_context"]
            series_context = "\n".join(sc) if isinstance(sc, list) else str(sc)
        elif "series_context_lines" in sysprm_json:
            series_context = "\n".join(sysprm_json["series_context_lines"])
        else:
            series_context = ""

        prompt_prefix = sysprm_json.get("prompt_prefix", "")

        initial_context_dict = {
            k: v for k, v in sysprm_json.items() 
            if k not in ["language", "series_context", "series_context_lines", "prompt_prefix"]
        }
        initial_context_str = json.dumps(initial_context_dict, ensure_ascii=False)

    except json.JSONDecodeError:
        log(log_queue, session_log_file, "❌ Error: SysPrm is not a valid JSON file. Legacy markdown profiles are not supported.")
        raise RuntimeError("SysPrm JSON decode error")

    if not resume_mode: log(log_queue, session_log_file, "✅ Loaded project-specific context from sysprm.")

    last_idx = 0
    illegal_labels = []
    
    ranges_str = "".join([f"\\u{s:04x}-\\u{e:04x}" for s, e in profile.target_unicode_ranges])
    re_name_labels = re.compile(rf'([A-Z][a-z]+|\([{ranges_str}]+\))')
    
    if series_context:
        matches = RE_SYS_IDX.findall(series_context)
        if matches:
            last_idx = max([int(m) for m in matches])
        
        name_matches = re_name_labels.findall(series_context)
        for nm in name_matches:
            clean_nm = nm.strip("()")
            if len(clean_nm) > 2 and clean_nm not in illegal_labels:
                illegal_labels.append(clean_nm)
        if "Jeff" not in illegal_labels: illegal_labels.append("Jeff")
        if "Probst" not in illegal_labels: illegal_labels.append("Probst")

    if not resume_mode:
        try:
            context_state = json.loads(initial_context_str) if initial_context_str != "{}" else {}
            if not context_state:
                 context_state = {
                    "last_two_lines_target": [], "last_speaker_info": profile.default_unknown_speaker, 
                    "speakers_gender": {} if profile.gender_tracking else {}, "current_setting": profile.default_setting_label, "summary": profile.default_opening_summary
                 }
        except json.JSONDecodeError:
            log(log_queue, session_log_file, "⚠️ Warning: Could not parse initial JSON. Falling back to default.")
            context_state = {
                "last_two_lines_target": [], "last_speaker_info": profile.default_unknown_speaker, 
                "speakers_gender": {} if profile.gender_tracking else {}, "current_setting": profile.default_setting_label, "summary": profile.default_opening_summary
            }

    with open(srt_file, 'r', encoding='utf-8-sig') as f:
        srt_content = f.read()

    from utils.app_utils import validate_srt_file
    is_valid, srt_errors = validate_srt_file(srt_file)
    if not is_valid:
        log(log_queue, session_log_file, "❌ FATAL: Source SRT file failed sanity check!")
        for err in srt_errors:
            log(log_queue, session_log_file, f"  ! {err}")
        log(log_queue, session_log_file, "🛑 Translation aborted. Please fix the SRT file errors listed above.")
        raise RuntimeError("Source SRT file failed sanity check!")

    blocks, eng_by_index, ordered_srt_indices = parse_srt_blocks(srt_content)

    return (profile, series_context, initial_context_str, context_state, last_idx, illegal_labels, srt_content, ordered_srt_indices, prompt_prefix)
