import os
import time
import datetime
import json
import re
import sys
import importlib
import subprocess
import queue

from utils.srt_manager import (
    RE_ITALIC_S, RE_ITALIC_D, RE_ALIGNMENT, 
    parse_srt_blocks, get_upcoming_cues, extract_chunk_metadata
)
import threading
from core.constants import (
    get_json_schema, get_workflow_step_templates, build_technical_rules, 
    STEP_HEADER_EN, get_user_prompt_prefix, get_special_instructions_header,
    get_technical_rules_header, get_exact_count_rule,
    get_exact_indices_rule, get_do_not_translate_rule, get_tag_rule
)
from core.text_processing import fix_rtl, pre_repair_json, check_heuristics, strip_music_glyphs_batch, force_split_overlong_line, cleanup_failed_translation
from core.llm_api import call_llm, call_llm_judge, generate_batch_schema
from utils.app_utils import log, file_log, format_cost_display, get_eta_string, pretty_json
from utils.srt_manager import strip_srt, load_srt_index_to_text, load_srt_full_history, validate_srt_file

from core.translation_stats import _inc_by_size, make_stats, print_stats
from core.session_manager import (
    get_next_checkpoint_file, resolve_checkpoint_paths, save_checkpoint,
    cleanup_checkpoint, build_checkpoint_payload, restore_profile_from_checkpoint
)
from core.audit_manager import run_audit_pipeline

RE_SDH_PUNCT = re.compile(r"[-.\s]*[\[(].*?[\])][-.\s]*")
RE_SYS_IDX = re.compile(r'###\s*(\d+)\.')

def run_pipeline(self, config):
    try:
        resume_mode = config["resume_mode"]
        self.debug_mode = config.get("debug_mode", False)
        model_cfg = config["model_cfg"]
        api_key = config["api_key"]
        batch_size = config["batch_size"]  # UI / configured default; may differ from effective_batch_size while running
        session_log_file = config["session_log_file"]
        
        profile = config.get("language_profile")
        if not profile:
            from utils.settings import SETTINGS
            profile = SETTINGS.get_active_profile()
        self.profile = profile # Store for secondary methods
        
        # Universalization: Dynamic Regex compilation based on profile
        ranges_str = "".join([f"\\u{s:04x}-\\u{e:04x}" for s, e in profile.target_unicode_ranges])
        self.re_ghost_chars = re.compile(rf'\n[a-zA-Z]{{1,2}}(?=\s|[{ranges_str}]|<|♪)')
        self.re_name_labels = re.compile(rf'([A-Z][a-z]+|\([{ranges_str}]+\))')
        
        self.re_newline_cleanup = re.compile(profile.newline_regex)
        
        # Paths
        checkpoint_dir = config["checkpoint_dir"]
        sysprm_dir = config["sysprm_dir"]
        english_subs_dir = config["english_subs_dir"]
        output_dir = config["output_dir"]

        if resume_mode:
            checkpoint_data = config["checkpoint_data"]
            sys_file, srt_file = resolve_checkpoint_paths(checkpoint_data, sysprm_dir, english_subs_dir)
            
            output_file = checkpoint_data['output_file']
            current_index = checkpoint_data['current_index']
            processed = checkpoint_data.get('processed', 0)
            total_main_cost = checkpoint_data.get('total_main_cost', checkpoint_data.get('total_cost', 0.0))
            total_judge_cost = checkpoint_data.get('total_judge_cost', 0.0)
            context_state = checkpoint_data['context_state']
            
            restore_profile_from_checkpoint(profile, checkpoint_data)
            current_checkpoint_file = config["checkpoint_file_path"]
            
            if not os.path.exists(srt_file) or not os.path.exists(sys_file):
                log(self.log_queue, session_log_file, "❌ Error: Original files missing. Cannot resume.")
                self.ui_queue.put(("finished", None))
                return

            self.current_output_file = output_file
            log(self.log_queue, session_log_file, f"\n✅ Resuming session: {srt_file} from block {current_index}")
            log(self.log_queue, session_log_file, f"📁 Using Checkpoint File: {current_checkpoint_file}")

        else:
            sys_file = os.path.join(sysprm_dir, config["sys_name"])
            srt_file = os.path.join(english_subs_dir, config["srt_name"])
            current_checkpoint_file = get_next_checkpoint_file(checkpoint_dir)

            base_name = os.path.basename(srt_file)
            output_file = os.path.join(output_dir, base_name.replace('.srt', f'_{model_cfg["name"]}_{profile.target_lang_code}.srt'))
            self.current_output_file = output_file
            current_index = 0
            processed = 0
            total_main_cost = 0.0
            total_judge_cost = 0.0
            log(self.log_queue, session_log_file, f"\n📁 Creating new Checkpoint File: {current_checkpoint_file}")

        # Bypass intervention tracking (only active when config["bypass_intervention"] is True)
        bypass_log_file = None  # Created on first bypass event
        bypass_count = 0

        # Initial terminal info
        log(self.log_queue, session_log_file, f"📝 Target File: {os.path.basename(srt_file)}")
        if resume_mode:
            log(self.log_queue, session_log_file, f"🔄 Resuming from index: {current_index}")

        with open(sys_file, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
        clean_lines = [line for line in lines if not line.strip().startswith("//")]
        raw_sysprm = "".join(clean_lines).strip()
        
        # ── Ratio Resolution & Logging ──
        ratios = list(profile.get_ratios(profile.source_lang_code))
        ratios_source = "Defaults"
        
        try:
            sysprm_json = json.loads(raw_sysprm)
            
            # 1. Parse Language Overrides (Tier 0)
            if "language" not in sysprm_json or "use_native_instructions" not in sysprm_json["language"]:
                log(self.log_queue, session_log_file, "❌ Error: SysPrm must be a JSON file and contain 'language': {'use_native_instructions': true/false}. Legacy files are not supported.")
                self.ui_queue.put(("finished", None))
                return

            lang_cfg = sysprm_json["language"]
            if "source" in lang_cfg: profile.source_lang_code = lang_cfg["source"]
            if "target" in lang_cfg: profile.target_lang_code = lang_cfg["target"]
            profile.use_native_instructions = bool(lang_cfg["use_native_instructions"])
            mode_str = "Native" if profile.use_native_instructions else "English"
            log(self.log_queue, session_log_file, f"🌐 Mode: {mode_str} Instructions")
            
            if "max_words_per_line" in lang_cfg:
                profile.max_words_per_line = int(lang_cfg["max_words_per_line"])
            
            # Ratio Overrides
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

            log(self.log_queue, session_log_file, 
                f"📊 Word Ratios ({ratios_source}): MinBlock={ratios[0]}, MaxBlock={ratios[1]}, MinBatch={ratios[2]}, MaxBatch={ratios[3]}")

            # 2. Parse Series Context
            if "series_context" in sysprm_json:
                sc = sysprm_json["series_context"]
                series_context = "\n".join(sc) if isinstance(sc, list) else str(sc)
            elif "series_context_lines" in sysprm_json: # Legacy support for early JSON format
                series_context = "\n".join(sysprm_json["series_context_lines"])
            else:
                series_context = ""

            # 3. Parse Prompt Prefix (Legacy JSON)
            prompt_prefix = sysprm_json.get("prompt_prefix", "")

            # 4. Extract Bookkeeping / Initial Context
            # Everything not 'language' or 'series_context' is initial context
            initial_context_dict = {
                k: v for k, v in sysprm_json.items() 
                if k not in ["language", "series_context", "series_context_lines", "prompt_prefix"]
            }
            initial_context_str = json.dumps(initial_context_dict, ensure_ascii=False)

        except json.JSONDecodeError:
            log(self.log_queue, session_log_file, "❌ Error: SysPrm is not a valid JSON file. Legacy markdown profiles are not supported.")
            self.ui_queue.put(("finished", None))
            return

        if not resume_mode: log(self.log_queue, session_log_file, "✅ Loaded project-specific context from sysprm.")

        # Calculate dynamic serial indexes based on the project sysprm context
        last_idx = 0
        illegal_labels = [] # List of names that should be purged if found with colons
        if series_context:
            matches = RE_SYS_IDX.findall(series_context)
            if matches:
                last_idx = max([int(m) for m in matches])
            
            # Extract potential speaker names from the gender tracking lists for the auditor
            # Searches for words in parentheses or capitalize English names
            name_matches = self.re_name_labels.findall(series_context)
            for nm in name_matches:
                clean_nm = nm.strip("()")
                if len(clean_nm) > 2 and clean_nm not in illegal_labels:
                    illegal_labels.append(clean_nm)
            # Add common technical labels
            if "Jeff" not in illegal_labels: illegal_labels.append("Jeff")
            if "Probst" not in illegal_labels: illegal_labels.append("Probst")
        
        self.illegal_labels = illegal_labels # Store as instance variable
        idx_workflow = last_idx + 1
        idx_tech = idx_workflow + 1
        idx_clean = idx_tech + 1
        
        # Modular System Instruction Assembly
        use_scratchpad = model_cfg.get("enable_scratchpad", True)
        
        workflow_steps = get_workflow_step_templates(profile, use_scratchpad)
        formatted_steps = []
        for i, step_text in enumerate(workflow_steps, 1):
            formatted_steps.append(step_text.replace("{n}", str(i)))
            
        # Default to English header
        sys_inst_header = STEP_HEADER_EN.replace("[IDX_WORKFLOW]", str(idx_workflow))
        
        # Check if profile provides its own header for native instructions
        if profile.use_native_instructions and profile.native_workflow_steps and 'header' in profile.native_workflow_steps:
            sys_inst_header = profile.native_workflow_steps['header'].replace("[IDX_WORKFLOW]", str(idx_workflow))

        sys_inst = sys_inst_header + "\n" + "\n".join(formatted_steps)
        
        tech_rules = build_technical_rules(profile)
        tech_rules = tech_rules.replace("[IDX_TECH]", str(idx_tech)).replace("[IDX_CLEAN]", str(idx_clean))

        system_prompt_parts = []
        if prompt_prefix:
            system_prompt_parts.append(prompt_prefix)
        if series_context:
            system_prompt_parts.append(series_context.strip())
        system_prompt_parts.append(sys_inst.strip())
        system_prompt_parts.append(tech_rules.strip())
        
        legacy_sys = "\n\n".join(system_prompt_parts) + "\n"

        from core.translation.prompt_builder import build_system_prompt
        new_sys = build_system_prompt(profile, model_cfg, idx_workflow, idx_tech, idx_clean, prompt_prefix, series_context)

        if legacy_sys != new_sys:
            err_msg = "💥 System Prompt building Delta mismatch!"
            log(self.log_queue, None, err_msg)
            raise RuntimeError(err_msg)

        system_prompt = legacy_sys
        
        # Efficiency/Quality logging
        log(self.log_queue, session_log_file, f"🚀 [Mode: {'High-Quality (Scratchpad)' if use_scratchpad else 'Efficiency (Direct)'}] Starting translation with {model_cfg['name']}...")

            
        if not resume_mode:
            try:
                context_state = json.loads(initial_context_str) if initial_context_str != "{}" else {}
                if not context_state:
                     context_state = {
                        "last_two_lines_target": [], "last_speaker_info": profile.default_unknown_speaker, 
                        "speakers_gender": {} if profile.gender_tracking else {}, "current_setting": profile.default_setting_label, "summary": profile.default_opening_summary
                     }
            except json.JSONDecodeError:
                log(self.log_queue, session_log_file, "⚠️ Warning: Could not parse initial JSON. Falling back to default.")
                context_state = {
                    "last_two_lines_target": [], "last_speaker_info": profile.default_unknown_speaker, 
                    "speakers_gender": {} if profile.gender_tracking else {}, "current_setting": profile.default_setting_label, "summary": profile.default_opening_summary
                }

        with open(srt_file, 'r', encoding='utf-8-sig') as f:
            srt_content = f.read()

        # --- Sanity Check ---
        from utils.app_utils import validate_srt_file
        is_valid, srt_errors = validate_srt_file(srt_file)
        if not is_valid:
            log(self.log_queue, session_log_file, "❌ FATAL: Source SRT file failed sanity check!")
            for err in srt_errors:
                log(self.log_queue, session_log_file, f"  ! {err}")
            log(self.log_queue, session_log_file, "🛑 Translation aborted. Please fix the SRT file errors listed above.")
            self.ui_queue.put(("finished", None))
            return
        # --------------------

        blocks, eng_by_index, ordered_srt_indices = parse_srt_blocks(srt_content)
        total_blocks = len(blocks)


        if resume_mode:
            translated_target_by_index = load_srt_index_to_text(output_file)
            # Back-fill last 50 segments for web dashboard history
            try:
                full_target_history = load_srt_full_history(output_file)
                # Find where we are in ordered_srt_indices
                if srt_content and ordered_srt_indices: 
                    processed_indices = []
                    # Only scan up to the resume point. 
                    # Do NOT break on a missing segment (in case the LLM skipped an index previously)
                    for idx_o in ordered_srt_indices[:current_index]:
                        if idx_o in translated_target_by_index:
                            processed_indices.append(idx_o)
                    
                    last_50_indices = processed_indices[-50:]
                    for idx_h in last_50_indices:
                        h_data = full_target_history.get(idx_h)
                        if h_data:
                            e_text = eng_by_index.get(idx_h, "")
                            self.ui_queue.put(("segment", (idx_h, h_data["time"], e_text, h_data["text"])))
            except Exception as e:
                log(self.log_queue, session_log_file, f"⚠️ Warning: History back-fill failed: {e}")
        else:
            translated_target_by_index = {}

        if resume_mode:
            ckpt_batch_original = int(checkpoint_data.get("batch_size", batch_size))
            if batch_size != ckpt_batch_original:
                # Manual override detected in UI
                effective_batch_size = batch_size
                override_msg = f" (Manual override: reset to {batch_size})"
            else:
                effective_batch_size = int(checkpoint_data.get("effective_batch_size", batch_size))
                override_msg = ""
        else:
            effective_batch_size = batch_size
            override_msg = ""
        
        effective_batch_size = max(2, effective_batch_size)

        # ── Stats initialization ──────────────────────────────────────
        if resume_mode:
            stats = make_stats(resume_from=checkpoint_data.get("stats"))
        else:
            stats = make_stats()

        # Capture elapsed time accumulated in previous sessions
        elapsed_at_session_start = stats["total_elapsed_seconds"]
        session_start_time = time.time()

        def push_eta():
            """Push a fresh ETA to both GUIs. Reads current processed/elapsed at call time."""
            if processed > 0:
                t = elapsed_at_session_start + (time.time() - session_start_time)
                time_str, finish_str, eta_secs = get_eta_string(t, processed, total_blocks)
                self.ui_queue.put(("eta", (time_str, finish_str, eta_secs)))
                if self.shared_state:
                    self.shared_state.update_eta(time_str, finish_str)
        # ─────────────────────────────────────────────────────────────

        start_time = time.time()
        session_processed = 0
        success_streak = 0

        # Initial GUI priming
        self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
        if self.shared_state:
            self.shared_state.update_cost(total_main_cost, total_judge_cost, format_cost_display(total_main_cost, total_judge_cost))
        if stats.get("total_interventions", 0) > 0:
            self.ui_queue.put(("intervention_count", stats["total_interventions"]))

        log(self.log_queue, session_log_file, f"🚀 Starting Protected AI Translation with {model_cfg['provider']}")
        
        if resume_mode:
            if override_msg:
                log(self.log_queue, session_log_file, f"📦 Batch: {batch_size}{override_msg}")
            elif effective_batch_size != batch_size:
                log(self.log_queue, session_log_file, f"📦 Batch: configured {batch_size} | continuing with effective size {effective_batch_size} (checkpoint memory)")
            else:
                log(self.log_queue, session_log_file, f"📦 Batch Size: {effective_batch_size}")
        else:
            log(self.log_queue, session_log_file, f"📦 Batch Size: {effective_batch_size} | Safety Net: ACTIVE")

        self.ui_queue.put(("progress", (processed, total_blocks)))
        if self.shared_state:
            self.shared_state.update_progress(processed, total_blocks)

        # Pre-seed web dashboard and desktop GUI with historical context on resume
        if resume_mode:
            historical_speed = 0.0
            all_calls = stats.get("llm_call_times_new", []) + stats.get("llm_call_times_retry", [])
            total_duration = sum(c[0] for c in all_calls)
            total_load = sum(c[1] for c in all_calls)
            if total_duration > 0:
                historical_speed = total_load / total_duration
            
            # Update both dashboards immediately
            self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
            
            if self.shared_state:
                self.shared_state.update_cost(total_main_cost, total_judge_cost)

        file_mode = 'a' if resume_mode else 'w'
        with open(output_file, file_mode, encoding='utf-8') as f_out:
            
            while current_index < total_blocks and not self.should_stop:
                # Emit upcoming 2 cues for web viewer preview
                upcoming_cues = get_upcoming_cues(blocks, current_index)
                self.ui_queue.put(("upcoming", upcoming_cues))

                current_batch_size = effective_batch_size
                batch_success = False
                min_batch_failures = 0  # at size 2, allow up to 3 attempts before total failure
                attempted_batch_sizes = []  # sizes tried this chunk; on success after retries, effective = one-before-last
                failures_at_current_size = 0  # need 2 failures at same size before shrinking (avoids one-off glitches)

                last_judge_error = ""      # The error text
                last_judged_indices = set() # The indices that were in the rejected Chunk
                previous_overlong_indices = set() # Track overlong lines for auto-repair consistency
                pipeline_start_time = time.time()
                while not batch_success and not self.should_stop:
                    batch_diagnostics_logged = False
                    this_attempt_auditor_flagged = False  # reset each attempt
                    native_audit_reason = ""  # ensure always defined if call_llm fails before check_heuristics
                    attempted_batch_sizes.append(current_batch_size)
                    start_idx = current_index
                    end_idx = min(current_index + current_batch_size, total_blocks)
                    expected_count = end_idx - start_idx
                    
                    prev_context_blocks = []
                    if start_idx >= 2: prev_context_blocks = blocks[start_idx - 2 : start_idx]
                    elif start_idx == 1: prev_context_blocks = [blocks[0]]
                        
                    next_context_blocks = []
                    if end_idx <= total_blocks - 2: next_context_blocks = blocks[end_idx : end_idx + 2]
                    elif end_idx == total_blocks - 1: next_context_blocks = [blocks[total_blocks - 1]]

                    chunk = blocks[start_idx:end_idx]
                    
                    original_metadata = extract_chunk_metadata(chunk)
                    
                    text_chunk_parts = []
                    if prev_context_blocks: 
                        suffix = profile.label_do_not_translate
                        text_chunk_parts.append(f"### [{profile.label_prev_context} - {suffix}] ###\n{strip_srt(prev_context_blocks)}\n")
                    
                    input_payload = { m['index']: m['text'] for m in original_metadata }
                    pipeline_load = sum(len(str(v)) for v in input_payload.values())
                    for idx, txt in input_payload.items():
                        # If line is only SDH tags + punctuation, force empty string
                        if RE_SDH_PUNCT.fullmatch(txt):
                            input_payload[idx] = ""

                    # --- Tag Passthrough: Pre-Processing ---
                    # We identify and strip special tags to simplify the LLM payload.
                    batch_italic_indices = set()
                    batch_alignment_map = {} # stores {line_idx: pos} for each subtitle index
                    final_input_payload = {}
                    
                    for idx, txt in input_payload.items():
                        lines = txt.split('\n')
                        cleaned_lines = []
                        subtitle_aligns = {}
                        
                        for i, line in enumerate(lines):
                            l_strip = line.strip()
                            align_match = RE_ALIGNMENT.match(l_strip)
                            if align_match:
                                subtitle_aligns[i] = align_match.group('pos')
                                cleaned_lines.append(align_match.group('rest').strip())
                            else:
                                cleaned_lines.append(line)
                        
                        if subtitle_aligns:
                            batch_alignment_map[idx] = subtitle_aligns
                        
                        current_txt = '\n'.join(cleaned_lines).strip()

                        # 2. Italic Strip: Check for <i>...</i>
                        match_s = RE_ITALIC_S.match(current_txt)
                        match_d = RE_ITALIC_D.match(current_txt)
                        
                        if match_s:
                            # Case 1: Single wrap (even if multi-line)
                            final_input_payload[idx] = match_s.group('c').strip()
                            batch_italic_indices.add(idx)
                        elif match_d:
                            # Case 2: Double wrap (each line has its own pair)
                            final_input_payload[idx] = f"{match_d.group('c1').strip()}\n{match_d.group('c2').strip()}"
                            batch_italic_indices.add(idx)
                        else:
                            # Case 3: Mixed text or complex tags - leave current_txt (which might have had align stripped)
                            final_input_payload[idx] = current_txt
                            
                    from core.translation.text_cleaner import clean_and_strip_tags
                    new_final_input, new_italic_indices, new_alignment_map = clean_and_strip_tags(input_payload, profile)

                    if final_input_payload != new_final_input or batch_italic_indices != new_italic_indices or batch_alignment_map != new_alignment_map:
                        err_msg = "💥 Text Cleaner Delta mismatch!"
                        log(self.log_queue, None, err_msg)
                        raise RuntimeError(err_msg)
                            
                    if batch_italic_indices and getattr(self, 'debug_mode', False):
                        log(self.log_queue, session_log_file, f"✨ [Italic Passthrough] Stripped outer italics for indices: {', '.join(sorted(batch_italic_indices))}")

                    text_chunk_parts.append(f"### [{profile.label_translation_blocks}] ###\n{json.dumps(final_input_payload, ensure_ascii=False, indent=2)}\n")
                    
                    if next_context_blocks:
                        suffix = profile.label_do_not_translate
                        text_chunk_parts.append(f"### [{profile.label_next_context} - {suffix}] ###\n{strip_srt(next_context_blocks)}\n")
                    
                    text_chunk = '\n'.join(text_chunk_parts)
                    indices = [d['index'] for d in original_metadata]
                    
                    summary_text = context_state.get('summary', profile.default_opening_summary)
                    last_speaker = context_state.get('last_speaker_info') or context_state.get('last_speaker', profile.default_unknown_speaker)
                    setting = context_state.get('current_setting', profile.default_setting_label)
                    
                    last_lines = context_state.get('last_two_lines_target', context_state.get('last_two_lines_heb', []))
                    use_native = profile.use_native_instructions
                    
                    last_line_str = ""
                    if last_lines:
                        last_line_template = profile.native_last_line_label if use_native else "Last translated line (from previous batch): '{last_line}'"
                        last_line_str = last_line_template.replace("{last_line}", last_lines[-1])
                        
                    continuity_note = context_state.get('continuity_note', '')
                    continuity_str = ""
                    if continuity_note and continuity_note.strip():
                        continuity_template = profile.native_continuity_note_label if use_native else "⚠️ Continuity note from previous batch (Attention!): {note}"
                        continuity_str = continuity_template.replace("{note}", continuity_note)

                    story_header = profile.native_story_context_header if use_native else "### Story Context (Previous Batches) ###"
                    setting_label = (profile.native_current_setting_label if use_native else "Current Setting: {setting}").replace("{setting}", setting)
                    summary_label = (profile.native_plot_summary_label if use_native else "Plot Summary: {summary}").replace("{summary}", summary_text)
                    speaker_label = (profile.native_last_speaker_label if use_native else "Last Speaker (previous batch): {speaker}").replace("{speaker}", last_speaker)

                    context_section_lines = [
                        story_header,
                        setting_label,
                        summary_label,
                        speaker_label
                    ]
                    if last_line_str: context_section_lines.append(last_line_str)
                    if continuity_str: context_section_lines.append(continuity_str)
                        
                    context_section = '\n'.join(context_section_lines)

                    # Structured Outputs check for prompt optimization
                    supports_structured = (model_cfg.get('provider') in ['openai', 'lmstudio'] and 
                                         (model_cfg.get('provider') == 'lmstudio' or any(m in model_cfg.get('name', '').lower() for m in ["gpt-4o", "gpt-4o-mini", "o1"])))

                    # Use Lite Schema for Efficiency Mode if Structured Output isn't being used 
                    # (even if it is, this ensures parity in the prompt instructions)
                    active_schema_template = get_json_schema(profile, is_lite=(not use_scratchpad))
                    
                    mandatory_schema_msg = profile.native_schema_mandatory_label if profile.use_native_instructions else "### MANDATORY: Respond EXACTLY in the specified JSON Schema format. ###"
                    
                    if not supports_structured:
                        schema_instruction = f"\n{active_schema_template}\n"
                    else:
                        schema_instruction = f"\n{mandatory_schema_msg}\n"

                    # Dynamic Rule Injection: Formatting Tags
                    # Only show the tag preservation rule if tags or music symbols are actually present in this batch.
                    has_tags = any("<" in str(val) or "♪" in str(val) for val in input_payload.values())
                    tag_rule = ""
                    if has_tags:
                        tag_rule = get_tag_rule(profile) + "\n"


                    # --- PROMPT INJECTION: Pre-emptive Support ---
                    # We scan the SOURCE text to see if there are tricky spots (Names, SDH)
                    # and warn the translator in advance.
                    from core import text_processing
                    importlib.reload(text_processing)
                    pre_warnings = text_processing.pre_audit_source(input_payload, illegal_labels=self.illegal_labels, profile=profile)
                    
                    warning_section = ""
                    if pre_warnings:
                        # Build the surgical instruction for the LLM
                        warning_list = [f"Index {idx}: {msg}" for idx, msg in pre_warnings]
                        header = get_special_instructions_header(profile)
                        warning_section = f"\n{header}\n" + "\n".join([f"• {w}" for w in warning_list]) + "\n"
                        
                        # Conditional Logging to terminal
                        flagged_indices = sorted(list(set(str(idx) for idx, msg in pre_warnings)), key=lambda x: int(x) if x.isdigit() else 0)
                        if getattr(self, 'debug_mode', False):
                            log(self.log_queue, session_log_file, f"🔍 Forensic Scout: Detailed analysis for indices {flagged_indices}.")
                            for idx, msg in pre_warnings:
                                log(self.log_queue, session_log_file, f"   ↳ Index {idx}: {msg}")
                        else:
                            log(self.log_queue, session_log_file, f"🔍 Forensic Scout: Targets flagged at indices {flagged_indices}.")

                    user_prompt_prefix = get_user_prompt_prefix(profile)
                    tech_rules_header = get_technical_rules_header(profile)
                    rule_count = get_exact_count_rule(profile, expected_count)
                    rule_indices = get_exact_indices_rule(profile, indices)
                    rule_do_not_translate = get_do_not_translate_rule(profile)

                    user_prompt = f"""
{user_prompt_prefix}
{warning_section}
{context_section}

{text_chunk}

{tech_rules_header}
{rule_count}
{rule_indices}
{rule_do_not_translate}
{tag_rule}
{schema_instruction}
"""

                    feedback_injection = ""
                    # If there is a judge error, and at least one index is shared between current batch and rejected batch
                    if last_judge_error and set(indices).intersection(last_judged_indices):
                        idx_label = profile.native_index_label if profile.use_native_instructions else "Index"
                        feedback_injection = "\n" + (profile.native_feedback_header if profile.use_native_instructions else "### YOU MUST FIX THE FOLLOWING ERRORS BY INDEX (DO NOT REPEAT THESE MISTAKES): ###") + "\n"
                        
                        if isinstance(last_judge_error, dict):
                            for err_idx, err_msg in last_judge_error.items():
                                if err_idx in ["GLOBAL", "GENERAL", "general"] or str(err_idx).startswith("chunk_") or err_idx in indices or str(err_idx) in [str(i) for i in indices]:
                                    prefix = f"{idx_label} {err_idx}: " if err_idx not in ["GLOBAL", "GENERAL", "general"] and not str(err_idx).startswith("chunk_") else ""
                                    feedback_injection += f"{prefix}{err_msg}\n"
                        else:
                            feedback_injection += f"{last_judge_error}\n"
                        
                        feedback_injection += "----------------------------------------\n"
                    final_prompt = user_prompt + feedback_injection

                    from core.translation.prompt_builder import build_user_prompt
                    new_user_prompt = build_user_prompt(
                        profile, model_cfg, context_state, expected_count, indices, 
                        text_chunk, input_payload, use_scratchpad, warning_section, 
                        tag_rule, last_judge_error, last_judged_indices
                    )

                    if final_prompt != new_user_prompt:
                        err_msg = "💥 User Prompt building Delta mismatch!"
                        log(self.log_queue, None, err_msg)
                        raise RuntimeError(err_msg)

                    raw_res = None
                    _batch_system_prompt = system_prompt
                    _batch_user_prompt = final_prompt
                    try:
                        log(self.log_queue, session_log_file, f"⏳ Sending Batch (Indices: {indices[0]}-{indices[-1]} | Batch Size: {expected_count})...")
                        is_retry = (len(attempted_batch_sizes) > 1)
                        # Calculate load (total character count of English text)
                        batch_load = sum(len(str(val)) for val in input_payload.values())
                        self.ui_queue.put(("timer_start", {"size": len(input_payload), "load": batch_load, "is_retry": is_retry}))

                        # V3 Audit Hook: Active Batch & Status
                        if self.shared_state:
                            trend = -1 if is_retry else 0
                            if not is_retry:
                                # Reset cause label for fresh batches — retries keep the ruling that explains why they're retrying
                                self.shared_state.update_audit(batch_size=expected_count, batch_trend=trend, last_decision="✦ Fresh Batch")
                            else:
                                self.shared_state.update_audit(batch_size=expected_count, batch_trend=trend)
                            
                            # Update only the pulsing status pill (Activity vs Ruling)
                            status_txt = "Translating (Retry)" if is_retry else "Translating"
                            status_clr = "#f59e0b" if is_retry else "#0ea5e9"
                            self.shared_state.update_status(status_txt, status_clr)

                        # ── Track attempt ──────────────────────────────
                        stats["total_batches_attempted"] += 1
                        if is_retry:
                            stats["total_retries"] += 1
                        batch_call_start = time.time()
                        # ──────────────────────────────────────────────

                        # --- Dynamic Temperature (Heat-up) Logic ---
                        # Only applied to batch size 2 to overcome deterministic stagnation.
                        temp_cfg = model_cfg.copy()
                        if current_batch_size == 2:
                            if min_batch_failures == 1:
                                temp_cfg['temperature'] = 0.3
                                log(self.log_queue, session_log_file, "🌡️ [Heat-up] Minimal batch attempt 2: Setting temperature to 0.3")
                            elif min_batch_failures == 2:
                                temp_cfg['temperature'] = 0.7
                                log(self.log_queue, session_log_file, "🔥 [High Heat] Minimal batch attempt 3: Setting temperature to 0.7")
                        # -------------------------------------------

                        raw_res, in_tokens, out_tokens, cached_tokens, reasoning_tokens = call_llm(temp_cfg, system_prompt, final_prompt, api_key, indices_list=indices)

                        if getattr(self, 'debug_mode', False) and raw_res:
                            timestamp_str = datetime.datetime.now().strftime("%H:%M:%S")
                            file_log(session_log_file, f"\n[{timestamp_str}] --- DEBUG TRANSACTION ---")
                            file_log(session_log_file, f"SYSTEM PROMPT:\n{system_prompt.strip()}\n")
                            file_log(session_log_file, f"USER PROMPT:\n{final_prompt.strip()}\n")
                            
                            # Log Structured Output Schema if batch indices are present
                            if indices:
                                # Use the same logic as the real call to ensure the log is accurate
                                schema_dump = json.dumps(generate_batch_schema(indices, use_scratchpad=use_scratchpad, profile=profile), ensure_ascii=False, indent=2)
                                file_log(session_log_file, f"STRUCTURED OUTPUT SCHEMA:\n{schema_dump}\n")

                                
                            # Pretty-print JSON for logs if possible
                            try:
                                pretty_res = json.dumps(json.loads(pre_repair_json(raw_res)), indent=4, ensure_ascii=False)
                            except:
                                pretty_res = raw_res.strip()

                            file_log(session_log_file, f"RAW LLM RESPONSE:\n{pretty_res}\n{'-'*38}\n")

                            batch_diagnostics_logged = True

                        # ── Record LLM call duration ───────────────────
                        _call_duration = time.time() - batch_call_start
                        if is_retry:
                            stats["llm_call_times_retry"].append((_call_duration, batch_load))
                        else:
                            stats["llm_call_times_new"].append((_call_duration, batch_load))
                        # ──────────────────────────────────────────────

                        self.ui_queue.put(("timer_stop", batch_load))
                        
                        # MAIN MODEL Cost Calculation
                        batch_cost, hit_str, hit_pct, brain_str = self._calculate_costs(in_tokens, out_tokens, cached_tokens, reasoning_tokens, model_cfg)

                        # V3 Telemetry Hook: Speed and Cache
                        if self.shared_state:
                            self.shared_state.update_telemetry(cache_hit_percent=int(hit_pct)) 

                        total_main_cost += batch_cost
                        
                        # Immediate GUI update
                        self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                        if self.shared_state:
                            self.shared_state.update_cost(total_main_cost, total_judge_cost, format_cost_display(total_main_cost, total_judge_cost))
                        
                        def fmt_val(v): return f"{int(v):,}" if v > 100 else f"${v:.5f}"

                        # Immediate Terminal logging
                        log(self.log_queue, session_log_file, f"💰 [Main Model] Batch: {fmt_val(batch_cost)} (In: {in_tokens:,}{hit_str} / Out: {out_tokens:,}{brain_str}) | Total: {fmt_val(total_main_cost)}")

                        # --- Calculate Velocity for Telemetry ---
                        pipeline_velocity = batch_load / _call_duration if _call_duration > 0 else 0

                        cleaned_res = pre_repair_json(raw_res)
                        try:
                            res_json = json.loads(cleaned_res)
                        except json.JSONDecodeError:
                            _inc_by_size(stats["json_parse_errors"], current_batch_size)
                            raise

                        # Auditor Warning for Placeholder Copy-Pasting
                        has_placeholder = False
                        if profile.use_native_instructions and profile.native_placeholder_indicators:
                            for indicator in profile.native_placeholder_indicators:
                                if indicator in cleaned_res:
                                    has_placeholder = True
                                    break
                        elif "<insert" in cleaned_res or "<brief summary" in cleaned_res:
                            has_placeholder = True

                        if has_placeholder:
                            log(self.log_queue, session_log_file, "⚠️ AUDITOR WARNING: The LLM responded with identical placeholder text from the prompt template!")

                        # Schema Recovery Layer: Handle GPT-5 key hallucinations
                        received_dict = self._recover_schema(res_json, stats, session_log_file)

                        # --- Italic Passthrough: Authoritative Enforcement ---
                        # We ensure italics exist ONLY where they existed in the source.
                        it_restored = 0
                        it_stripped = 0
                        for idx in indices:
                            if idx not in received_dict: continue
                            target_text = str(received_dict[idx]).strip()
                            
                            # Case A: Should have italics
                            if idx in batch_italic_indices:
                                if target_text and not (target_text.startswith('<i>') and target_text.endswith('</i>')):
                                    received_dict[idx] = f"<i>{target_text}</i>"
                                    it_restored += 1
                            
                            # Case B: Should NOT have italics (Hallucination removal)
                            else:
                                source_text = str(input_payload.get(idx, ""))
                                if "<i>" not in source_text:
                                    match = re.match(r"^<i>(.*)</i>$", target_text, re.DOTALL)
                                    if match:
                                        received_dict[idx] = match.group(1).strip()
                                        it_stripped += 1

                        if (it_restored > 0 or it_stripped > 0) and getattr(self, 'debug_mode', False):
                            log_msg = f"✨ [Italic Passthrough] Enforcement: Restored {it_restored} | Stripped hallucinated {it_stripped}"
                            log(self.log_queue, session_log_file, log_msg)

                        # --- Alignment Passthrough: Restoration ---
                        al_restored = 0
                        for idx in indices:
                            if idx in batch_alignment_map:
                                target_text = received_dict[idx]
                                # If the translation is empty (LLM removed SDH/etc), don't restore tags
                                if not target_text.strip():
                                    continue

                                subtitle_aligns = batch_alignment_map[idx]
                                h_lines = target_text.split('\n')
                                
                                # Case A: Line count matches perfectly
                                if len(h_lines) >= max(subtitle_aligns.keys()) + 1:
                                    for line_idx, pos in subtitle_aligns.items():
                                        # We ensure the standard {\anX} format with a backslash.
                                        # Using a raw string to prevent \a from being interpreted as a BELL character.
                                        h_lines[line_idx] = rf"{{\an{pos}}}{h_lines[line_idx]}"
                                        al_restored += 1
                                    received_dict[idx] = '\n'.join(h_lines)
                                
                                # Case B: Line count mismatch (e.g. LLM merged lines)
                                # Prepend unique alignment tags to the first line
                                else:
                                    unique_pos = sorted(list(set(subtitle_aligns.values())))
                                    # Standardize to {\anX} using raw string
                                    tags = "".join([rf"{{\an{p}}}" for p in unique_pos])
                                    received_dict[idx] = f"{tags}{target_text}"
                                    al_restored += len(unique_pos)
                        
                        if al_restored > 0 and getattr(self, 'debug_mode', False):
                            log(self.log_queue, session_log_file, f"✨ [Alignment Passthrough] Restored {{\\anX}} for {al_restored} lines.")

                        # --- Auditing & Judging Pipeline ---
                        # Inject illegal_labels into config so audit_manager can access it.
                        # (It's built from the sysprm series_context and stored on the engine instance.)
                        config["illegal_labels"] = getattr(self, 'illegal_labels', [])
                        batch_passed, last_judge_error, last_judged_indices, j_cost_delta, previous_overlong_indices = run_audit_pipeline(
                            indices=indices,
                            input_payload=input_payload,
                            received_dict=received_dict,
                            config=config,
                            profile=profile,
                            stats=stats,
                            log_queue=self.log_queue,
                            ui_queue=self.ui_queue,
                            session_log_file=session_log_file,
                            shared_state=self.shared_state,
                            previous_overlong_indices=previous_overlong_indices,
                            current_batch_size=current_batch_size,
                            ordered_srt_indices=ordered_srt_indices,
                            eng_by_index=eng_by_index,
                            translated_target_by_index=translated_target_by_index,
                            calculate_costs_func=self._calculate_costs,
                            push_eta_func=push_eta
                        )

                        if not batch_passed:
                            raise ValueError("Audit/Judge Rejection")

                        total_judge_cost += j_cost_delta
                        self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                        if self.shared_state:
                            self.shared_state.update_cost(total_main_cost, total_judge_cost, format_cost_display(total_main_cost, total_judge_cost))

                        self._finalize_batch_success(
                            original_metadata, received_dict, f_out, 
                            translated_target_by_index, res_json, context_state, 
                            stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
                        )

                        processed += expected_count 
                        session_processed += expected_count
                        batch_success = True
                        
                        speed_fmt = f"{pipeline_velocity:.2f}" if pipeline_velocity < 10 else f"{pipeline_velocity:.1f}"
                        log(self.log_queue, session_log_file, f"✅ Batch {indices[0]}-{indices[-1]} saved successfully. {speed_fmt}ch/s")
                        last_judge_error = ""
                        last_judged_indices = set()

                        # V3 Audit Hook: Return to Idle
                        if self.shared_state:
                            self.shared_state.update_status("Idle", "#7f8c8d") # <--- THIS MAKES IT GRAY

                    except Exception as e:
                        success_streak = 0
                        batch_label = f"{indices[0] if indices else '?'}-{indices[-1] if indices else '?'}"
                        
                        # Log error TO TERMINAL ONLY (to prevent cascading in file log)
                        self.log_queue.put(f"⚠️ Batch Failure: {e}")

                        # V3 Audit Hook: Generic failure cause for exceptions not caught by heuristic/judge hooks
                        if self.shared_state:
                            e_str = str(e)
                            # Heuristic/Judge failures already called update_audit before raising — don't override
                            if "Heuristic Rejection" not in e_str and "Judge Rejection" not in e_str:
                                if isinstance(e, json.JSONDecodeError):
                                    _cause = "⚠️ Parse Error: Retry"
                                elif "Schema collapse" in e_str or "translated_srt" in e_str:
                                    _cause = "⚠️ Schema Error: Retry"
                                elif "Sync Error" in e_str:
                                    _cause = "⚠️ Sync Error: Retry"
                                else:
                                    _cause = "⚠️ API Error: Retry"
                                self.shared_state.update_audit(last_decision=_cause)


                        if not batch_diagnostics_logged:
                            file_log(session_log_file, f"--- BATCH {batch_label} FAILURE DIAGNOSTICS (PRIMARY) ---")
                            file_log(session_log_file, f"SYSTEM PROMPT:\n{pretty_json(_batch_system_prompt)}")
                            file_log(session_log_file, f"USER PROMPT:\n{pretty_json(_batch_user_prompt)}")
                            if raw_res is not None:
                                file_log(session_log_file, f"RAW LLM RESPONSE:\n{pretty_json(raw_res)}")
                            else:
                                file_log(session_log_file, f"RAW LLM RESPONSE: None (call_llm failed)")
                            file_log(session_log_file, f"ERROR: {e}")
                            batch_diagnostics_logged = True
                        else:
                            log(self.log_queue, session_log_file, f"⚠️ Batch retry failure event for {batch_label} (Retry action follows). Reason: {e}")
                            push_eta()  # ETA rises to reflect time lost on this failure
                        
                        if current_batch_size <= 2:
                            min_batch_failures += 1
                            if min_batch_failures >= 3:
                                log(self.log_queue, session_log_file, "❌ Persistent failure at minimal batch size. Triggering intervention...")
                                
                                stats["total_interventions"] = stats.get("total_interventions", 0) + 1
                                self.ui_queue.put(("intervention_count", stats["total_interventions"]))

                                # Collect English source for the failed batch
                                eng_src_for_intervention = []
                                for idx in indices:
                                    eng_src_for_intervention.append({
                                        "index": idx,
                                        "timestamp": next(m['timestamp'] for m in original_metadata if m['index'] == idx),
                                        "text": eng_by_index[idx]
                                    })
                                    
                                # Build a detailed error message
                                reason_for_human = native_audit_reason if native_audit_reason else "System Error (AI succeeded but Engine crashed)"
                                if "pipeline_velocity" in str(e):
                                    reason_for_human += " [Internal Bug: 'pipeline_velocity' missing]"
                                else:
                                    reason_for_human += f" [System Error: {str(e)}]"

                                # ── BYPASS PATH ──────────────────────────────────────────
                                if getattr(self, 'bypass_intervention', False):
                                    log(self.log_queue, session_log_file,
                                        f"🚫 [BYPASS] Skipping manual intervention. Auto-cleaning {len(indices)} subtitle(s)...")

                                    bypass_dict = {}
                                    last_received = received_dict if 'received_dict' in locals() else {}
                                    for m in eng_src_for_intervention:
                                        raw_target = str(last_received.get(m['index'], ""))
                                        cleaned = cleanup_failed_translation(raw_target, m['text'], reason_for_human, profile=profile)
                                        bypass_dict[m['index']] = cleaned
                                        log(self.log_queue, session_log_file,
                                            f"   🚫 IDX {m['index']}: {repr(raw_target)[:60]} → {repr(cleaned)[:60]}")

                                    # Create bypass log on first occurrence
                                    if bypass_log_file is None:
                                        bypass_log_file = self._create_bypass_log(session_log_file)
                                    self._write_bypass_entry(bypass_log_file, eng_src_for_intervention, bypass_dict, reason_for_human)
                                    bypass_count += 1

                                    received_dict = bypass_dict
                                    res_json = {
                                        "translated_srt": bypass_dict,
                                        "summary": context_state.get('summary'),
                                        "last_speaker_info": context_state.get('last_speaker_info'),
                                        "continuity_note": context_state.get('continuity_note')
                                    }

                                    log(self.log_queue, session_log_file,
                                        f"🚫 [BYPASS] Auto-cleanup complete for batch {batch_label}. Resuming...")

                                    self._finalize_batch_success(
                                        original_metadata, received_dict, f_out,
                                        translated_target_by_index, res_json, context_state,
                                        stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
                                    )

                                    min_batch_failures = 0
                                    failures_at_current_size = 0
                                    batch_success = True
                                    continue

                                # ── MANUAL INTERVENTION PATH (unchanged) ─────────────────
                                
                                intervention_start_t = time.time()
                                manual_fix_dict = self._perform_manual_intervention(
                                    indices, 
                                    eng_src_for_intervention, 
                                    received_dict if 'received_dict' in locals() else {}, 
                                    reason_for_human,
                                    config.get("scratch_dir", "scratch"),
                                    profile=profile
                                )
                                intervention_duration = time.time() - intervention_start_t
                                session_start_time += intervention_duration # Exclude from ETA
                                

                                if manual_fix_dict:
                                    # Success! Inject the manual fix and pretend it was an LLM success
                                    received_dict = manual_fix_dict
                                    # Use empty/legacy context for manual fixes
                                    res_json = {
                                        "translated_srt": manual_fix_dict,
                                        "summary": context_state.get('summary'),
                                        "last_speaker_info": context_state.get('last_speaker_info'),
                                        "continuity_note": context_state.get('continuity_note')
                                    }
                                    
                                    log(self.log_queue, session_log_file, "✅ Manual Intervention successful. Resuming automated flow...")
                                    
                                    # Detailed Audit Trail for File Log
                                    file_log(session_log_file, f"--- MANUAL INTERVENTION AUDIT (Batch {indices[0]}-{indices[-1]}) ---")
                                    for m in eng_src_for_intervention:
                                        idx = m['index']
                                        file_log(session_log_file, f"IDX {idx} | EN: {m['text']}")
                                        file_log(session_log_file, f"IDX {idx} | HE (HUMAN): {manual_fix_dict.get(idx, 'MISSING')}")
                                    file_log(session_log_file, "--------------------------------------------------------")
                                    
                                    # --- NEW: Call Finalization logic for Manual Fix ---
                                    self._finalize_batch_success(
                                        original_metadata, received_dict, f_out, 
                                        translated_target_by_index, res_json, context_state, 
                                        stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
                                    )

                                    # Reset failure counters
                                    min_batch_failures = 0
                                    failures_at_current_size = 0
                                    batch_success = True
                                    continue 
                                else:
                                    log(self.log_queue, session_log_file, "❌ Manual Intervention cancelled or failed. Stopping.")
                                    self.should_stop = True
                                    break
                            log(self.log_queue, session_log_file, f"🔁 Minimal batch (size 2) attempt {min_batch_failures}/3 failed; retrying same size...")
                        else:
                            failures_at_current_size += 1
                            if failures_at_current_size < 2:
                                log(self.log_queue, session_log_file, f"🔁 Same size ({current_batch_size}): first failure—retrying without reducing (guards against accidental glitches).")
                            else:
                                failures_at_current_size = 0
                                reduce_by = max(3, current_batch_size // 6)
                                current_batch_size = max(2, current_batch_size - reduce_by)
                                stats["batch_shrink_events"] += 1
                                log(self.log_queue, session_log_file, f"📉 Second failure at this size; reducing by {reduce_by} → {current_batch_size} and retrying...")

                if batch_success:
                    prev_effective = effective_batch_size
                    # If we succeeded on the FIRST attempt, increment streak
                    if len(attempted_batch_sizes) == 1:
                        success_streak += 1
                    else:
                        success_streak = 0 # Reset if it took retries                        
                    
                    # Check for Climb-Up Trigger
                    if success_streak >= 3 and effective_batch_size < batch_size:
                        # Dynamic climb: proportional to target but capped to prevent extreme jumps
                        climb_amount = max(2, min(8, batch_size // 4))
                        effective_batch_size = min(batch_size, effective_batch_size + climb_amount)
                        stats["batch_grow_events"] += 1
                        log(self.log_queue, session_log_file, f"📈 Success streak {success_streak}: Climbing up → {effective_batch_size}")
                        success_streak = 0 # Reset streak to stabilize at new size
                    elif len(attempted_batch_sizes) >= 2:
                        # e.g. sizes 60→50→42 succeeded at 42 → next chunk uses 50 (penultimate attempt)
                        effective_batch_size = attempted_batch_sizes[-2]
                    else:
                        effective_batch_size = current_batch_size
                    if effective_batch_size != prev_effective:
                        log(self.log_queue, session_log_file, f"📌 Effective batch size → {effective_batch_size} (penultimate size after retries; following chunks start here)")
                    current_index += expected_count

                    # ── Re-sync processed from stats (updated by _finalize_batch_success) ──
                    # This MUST happen before the checkpoint write and the UI update.
                    processed = stats.get("processed_total", processed)

                    # ── Update accumulated elapsed time & write checkpoint ─
                    stats["total_elapsed_seconds"] = elapsed_at_session_start + (time.time() - session_start_time)
                    checkpoint_data = build_checkpoint_payload(
                        config, current_index, processed, total_blocks, total_main_cost, total_judge_cost, 
                        context_state, profile, stats, output_file,
                        effective_batch_size=effective_batch_size
                    )
                    save_checkpoint(current_checkpoint_file, checkpoint_data)
                
                total_elapsed = stats.get("total_elapsed_seconds", 0.0)
                time_str, finish_str, eta_secs = get_eta_string(total_elapsed, processed, total_blocks)

                self.ui_queue.put(("progress", (processed, total_blocks)))
                self.ui_queue.put(("eta", (time_str, finish_str, eta_secs)))
                if self.shared_state:
                    self.shared_state.update_progress(processed, total_blocks)
                    self.shared_state.update_eta(time_str, finish_str)
                    
        if not self.should_stop:
            log(self.log_queue, session_log_file, f"\n✅ Translation Complete!")
            log(self.log_queue, session_log_file, f"📂 Output saved to: {output_file}")

            # ── Finalize elapsed and print stats ──────────────────────
            stats["total_elapsed_seconds"] = elapsed_at_session_start + (time.time() - session_start_time)
            print_stats(
                stats=stats,
                total_blocks=total_blocks,
                total_main_cost=total_main_cost,
                total_judge_cost=total_judge_cost,
                srt_file=srt_file,
                sys_file=sys_file,
                output_file=output_file,
                model_cfg=model_cfg,
                judge_cfg=config.get("judge_cfg", model_cfg),
                batch_size=batch_size,
                final_eff_batch_size=effective_batch_size,
                judge_batch_size=config.get("judge_batch_size", "?"),
                log_fn=lambda msg: log(self.log_queue, session_log_file, msg),
            )
            # ─────────────────────────────────────────────────────────

            if cleanup_checkpoint(current_checkpoint_file):
                log(self.log_queue, session_log_file, f"🧹 Cleaned up checkpoint.")

            # ── Bypass end-of-session warning ─────────────────────────────
            if bypass_count > 0:
                bypass_basename = os.path.basename(bypass_log_file) if bypass_log_file else "bypass_review.txt"
                banner_line = "⚠️  " * 14
                log(self.log_queue, session_log_file, f"\n{banner_line}")
                log(self.log_queue, session_log_file,
                    f"  ⚠️  {bypass_count} SUBTITLE BLOCK(S) WERE AUTO-BYPASSED AND MAY CONTAIN ERRORS  ⚠️")
                log(self.log_queue, session_log_file,
                    f"  📋 Review file: {bypass_basename}")
                log(self.log_queue, session_log_file, f"{banner_line}\n")
            
    except Exception as e:
        log(self.log_queue, config.get("session_log_file"), f"❌ Fatal Error: {e}")
    finally:
        self.ui_queue.put(("finished", (processed, total_blocks) if 'processed' in locals() and 'total_blocks' in locals() else None))
        self.ui_queue.put(("refresh", None))
