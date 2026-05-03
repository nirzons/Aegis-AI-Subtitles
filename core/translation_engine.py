import os
import time
import datetime
import json
import re
import sys
import importlib
import subprocess
import queue
RE_SDH_PUNCT = re.compile(r"[-.\s]*[\[(].*?[\])][-.\s]*")
RE_SYS_IDX = re.compile(r'###\s*(\d+)\.')
RE_NEWLINE_CLEANUP_BASE = re.compile(r'\s*\\+[n]\s*')
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


class TranslationEngine:
    def __init__(self, log_queue, ui_queue, shared_state=None):
        self.log_queue = log_queue
        self.ui_queue = ui_queue
        self.shared_state = shared_state # Added for Web Dashboard V3
        self.should_stop = False
        self.current_output_file = None
        self.intervention_choice_q = queue.Queue() # Communication channel for user decisions

    def request_stop(self):
        self.should_stop = True

    def _calculate_costs(self, tokens_in, tokens_out, tokens_cached, tokens_reasoning, cfg):
        from core.translation.cost_calculator import calculate_costs
        return calculate_costs(tokens_in, tokens_out, tokens_cached, tokens_reasoning, cfg)

    def _recover_schema(self, res_json, stats, session_log_file):
        from core.translation.schema_recovery import recover_schema
        return recover_schema(res_json, stats, session_log_file, log_queue=self.log_queue)


    def run_translation(self, config):
        from core.translation.pipeline import run_pipeline
        return run_pipeline(self, config)

    def _perform_manual_intervention(self, indices, metadata, failed_dict, audit_reason_native, scratch_dir, profile=None):
        """
        Opens Notepad for the user to manually fix a problematic batch.
        Blocks the engine thread until Notepad is closed.
        """
        fix_file = os.path.join(scratch_dir, "manual_intervention_fix.txt")
        os.makedirs(scratch_dir, exist_ok=True)

        # 1. Build Template
        use_native = profile and profile.use_native_instructions
        header = profile.native_intervention_header if use_native else "####### MANUAL INTERVENTION REQUIRED #######"
        instructions = profile.native_intervention_instructions if use_native else [
            "1. Edit the translation to the best of your ability.",
            "2. Save the file (Ctrl+S).",
            "3. Close the editor to continue."
        ]
        source_label = profile.native_intervention_source_label if use_native else "SOURCE ENGLISH LINES"
        target_label = profile.native_intervention_target_label if use_native else "TRANSLATED LINES REQUIRING FIX"
        edit_warning = profile.native_intervention_edit_warning if use_native else "Do not change the index numbers, only the translation text."
        max_words_warning = (profile.native_intervention_max_words_warning if use_native else "Try to ensure no more than {max_words} words per line.").replace("{max_words}", str(profile.max_words_per_line))
        error_label = profile.native_intervention_error_label if use_native else "The errors identified in these lines are:"

        content = [header]
        content.extend(instructions)
        content.append("############################################")
        content.append("")
        content.append(source_label)
        content.append("##############")
        content.append("")
        
        for m in metadata:
            content.append(f"{m['index']}")
            content.append(f"{m['timestamp']}")
            content.append(f"{m['text']}")
            content.append("")
            
        content.append(target_label)
        content.append(edit_warning)
        content.append(max_words_warning)
        content.append(error_label)
        content.append(f"< {audit_reason_native} >")
        content.append("##############")
        content.append("")
        
        for m in metadata:
            idx = m['index']
            content.append(f"{idx}")
            content.append(f"{m['timestamp']}")
            target_val = failed_dict.get(idx, "")
            content.append(f"{target_val}")
            content.append("")
            
        while True:
            # Write/Overwrite the file
            with open(fix_file, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(content))
                
            # Alert UI and wait for user's Yes/No decision
            self.ui_queue.put(("request_intervention", f"{indices[0]}-{indices[-1]}"))
            
            # This blocks until the UI thread puts True or False in the queue
            user_choice = self.intervention_choice_q.get()
            
            if not user_choice:
                log(self.log_queue, None, "🛑 User declined manual intervention. Aborting.")
                return None

            # 2. Launch Notepad & Wait
            try:
                subprocess.run(["notepad.exe", fix_file], check=True)
            except Exception as e:
                log(self.log_queue, None, f"⚠️ Failed to launch Notepad: {e}")
                return None

            # 3. Read back
            try:
                with open(fix_file, "r", encoding="utf-8-sig") as f:
                    updated_content = f.read().replace('\r\n', '\n')
            except Exception as e:
                log(self.log_queue, None, f"⚠️ Failed to read intervention file: {e}")
                return None

            # 4. Parse & Validate
            success, result, err = self._parse_intervention_file(updated_content, metadata)
            if success:
                return result
            else:
                # If validation failed, log it and the loop will re-open Notepad
                log(self.log_queue, None, f"🔍 Format Error: {err}. Re-opening Notepad...")
                # The while loop will re-open notepad.

    def _parse_intervention_file(self, content, metadata):
        marker = self.profile.native_intervention_target_label if self.profile else "TRANSLATED LINES REQUIRING FIX"
        if marker not in content:
            return False, None, "Marker section missing"
            
        # We only care about the text after the marker
        target_part = content.split(marker)[-1]
        
        results = {}
        for m in metadata:
            idx = str(m['index'])
            ts = m['timestamp'].strip()
            
            # Robust Regex: 
            # 1. Match the Index line
            # 2. Match the exact Timestamp line
            # 3. Capture everything until the next index block or section end
            escaped_ts = re.escape(ts)
            pattern = rf"(?:^|\n){idx}[ \t]*\n{escaped_ts}[ \t]*\n(.*?)(?=\n\d+[ \t]*\n|\n[#\-_=]|\Z)"
            
            match = re.search(pattern, target_part, re.DOTALL)
            if not match:
                return False, None, f"Index {idx} or its timestamp was modified or is missing"
            
            results[idx] = match.group(1).strip()
            
        return True, results, None

    def _finalize_batch_success(self, original_metadata, received_dict, f_out, 
                               translated_target_by_index, res_json, context_state, 
                               stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=True):
        """
        Shared logic for successful batches (both AI and Manual).
        Handles file writing, state updates, and telemetry.
        """
        translated_lines = []
        for m in original_metadata:
            idx = m['index']
            target_text = received_dict[idx]
            translated_lines.append(f"{idx}\n{m['timestamp']}\n{fix_rtl(target_text, target_is_rtl)}")
            # Emit each successful segment for GUI updates.
            self.ui_queue.put(("segment", (idx, m['timestamp'], m['text'], target_text)))
        
        f_out.write('\n\n'.join(translated_lines) + '\n\n')
        f_out.flush()

        for m in original_metadata:
            translated_target_by_index[m['index']] = fix_rtl(received_dict[m['index']], target_is_rtl)
        
        # Harvest flattened context state from response root
        context_state['summary'] = res_json.get('summary', context_state.get('summary'))
        context_state['last_speaker_info'] = res_json.get('last_speaker_info', context_state.get('last_speaker_info'))
        context_state['continuity_note'] = res_json.get('continuity_note', context_state.get('continuity_note'))
        if indices:
            last_idx = indices[-1]
            # Use canonical key 'last_two_lines_target' (purge legacy 'last_two_lines_heb' alias)
            context_state['last_two_lines_target'] = [received_dict[last_idx]]
            context_state.pop('last_two_lines_heb', None)

        # Stats and batch progress
        stats["processed_total"] = stats.get("processed_total", 0) + expected_count
        stats["total_batches_succeeded"] += 1
        _inc_by_size(stats["clean_passes_by_size"], expected_count)
        
        # Linguistic Telemetry
        linc = stats.setdefault("linguistics", {})
        for m in original_metadata:
            idx = m['index']
            eng = m['text']
            heb = received_dict.get(idx, "").strip()
            
            # Basic counters
            eng_wc = len(eng.split())
            target_wc = len(heb.split())
            linc["source_chars"] = linc.get("source_chars", 0) + len(eng)
            linc["source_words"] = linc.get("source_words", 0) + eng_wc
            
            # Punctuation & Symbols
            linc["source_punct"] = linc.get("source_punct", 0) + sum(1 for c in eng if c in '.,!?;:"-()[]')
            linc["music_symbols"] = linc.get("music_symbols", 0) + eng.count('♪')

            if not heb:
                linc["empty_subs"] = linc.get("empty_subs", 0) + 1
            else:
                linc["target_chars"] = linc.get("target_chars", 0) + len(heb)
                linc["target_words"] = linc.get("target_words", 0) + target_wc
                linc["target_punct"] = linc.get("target_punct", 0) + sum(1 for c in heb if c in '.,!?;:"-()[]')
                if '\n' in heb:
                    linc["multiline_subs"] = linc.get("multiline_subs", 0) + 1

            # Longest segments tracking
            if len(eng) > linc.get("longest_source_chars", {}).get("value", 0):
                linc["longest_source_chars"] = {"index": idx, "value": len(eng)}
            if eng_wc > linc.get("longest_source_words", {}).get("value", 0):
                linc["longest_source_words"] = {"index": idx, "value": eng_wc}
            if len(heb) > linc.get("longest_target_chars", {}).get("value", 0):
                linc["longest_target_chars"] = {"index": idx, "value": len(heb)}
            if target_wc > linc.get("longest_target_words", {}).get("value", 0):
                linc["longest_target_words"] = {"index": idx, "value": target_wc}

        # Speed Telemetry
        pipeline_duration = time.time() - pipeline_start_time
        pipeline_velocity = pipeline_load / pipeline_duration if pipeline_duration > 0 else 0
        self.ui_queue.put(("pipeline_telemetry", pipeline_velocity))
        if self.shared_state:
            self.shared_state.update_telemetry(tokens_per_sec=pipeline_velocity)

        self.ui_queue.put(("batch_success", None))


    # ─────────────────────────────────────────────────────────────────────────
    # Bypass Intervention Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _create_bypass_log(session_log_file: str) -> str:
        """
        Creates a dedicated bypass log file next to the session log.
        Returns the full path to the new file.
        """
        base = os.path.splitext(session_log_file)[0]
        path = f"{base}_BYPASS_REVIEW.txt"
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write("=" * 62 + "\n")
            f.write("  AEGIS BYPASS LOG — SEGMENTS REQUIRING MANUAL REVIEW\n")
            f.write("  These subtitles were auto-cleaned after 3 AI failures.\n")
            f.write("  Open your output SRT file and correct the lines below.\n")
            f.write("=" * 62 + "\n\n")
        return path

    @staticmethod
    def _write_bypass_entry(bypass_log_file: str, eng_src: list, bypass_dict: dict, reason: str):
        """
        Appends one bypass event to the bypass log file.
        eng_src: list of {index, timestamp, text} dicts.
        bypass_dict: {index: cleaned_heb} mapping.
        """
        with open(bypass_log_file, 'a', encoding='utf-8-sig') as f:
            f.write("\u2500" * 50 + "\n")
            f.write(f"FAILURE REASON: {reason}\n\n")
            for m in eng_src:
                idx = m['index']
                f.write(f"  [{idx}]  {m['timestamp']}\n")
                f.write(f"  EN:  {m['text']}\n")
                f.write(f"  HE:  {bypass_dict.get(idx, '[EMPTY]')}\n\n")
            f.write("\n")
