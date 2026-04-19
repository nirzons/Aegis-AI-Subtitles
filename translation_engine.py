import os
import time
import datetime
import json
import re
import threading
from constants import (
    STEP_HEADER, STEP_READ_CONTEXT, STEP_CONTINUOUS_DRAFT, STEP_MAPPING_PLAN, 
    STEP_SRT_SPLIT_RULES, STEP_FINAL_SRT, STEP_SELF_AUDIT, 
    STEP_CONTEXT_PRIMING, STEP_METADATA_UPDATE,
    GLOBAL_TECHNICAL_RULES, JSON_SCHEMA_TEMPLATE, JSON_SCHEMA_LITE, RULE_NO_ENGLISH
)

from text_processing import fix_rtl, pre_repair_json, check_heuristics, strip_music_glyphs_batch, force_split_overlong_line
from llm_api import call_llm, call_llm_judge, generate_batch_schema
from app_utils import log, file_log, format_cost_display, get_eta_string, strip_srt, load_srt_index_to_text, load_srt_full_history

from translation_stats import _inc_by_size, make_stats, print_stats


class TranslationEngine:
    def __init__(self, log_queue, ui_queue, shared_state=None):
        self.log_queue = log_queue
        self.ui_queue = ui_queue
        self.shared_state = shared_state # Added for Web Dashboard V3
        self.should_stop = False
        self.current_output_file = None

    def request_stop(self):
        self.should_stop = True

    def run_translation(self, config):
        try:
            resume_mode = config["resume_mode"]
            self.debug_mode = config.get("debug_mode", False)
            model_cfg = config["model_cfg"]
            api_key = config["api_key"]
            batch_size = config["batch_size"]  # UI / configured default; may differ from effective_batch_size while running
            session_log_file = config["session_log_file"]
            
            # Paths
            checkpoint_dir = config["checkpoint_dir"]
            sysprm_dir = config["sysprm_dir"]
            english_subs_dir = config["english_subs_dir"]
            output_dir = config["output_dir"]

            if resume_mode:
                checkpoint_data = config["checkpoint_data"]
                
                # Ensure we have full absolute paths even if checkpoint only has basenames
                sys_file_raw = checkpoint_data['sys_file']
                srt_file_raw = checkpoint_data['srt_file']
                sys_file = sys_file_raw if os.path.isabs(sys_file_raw) else os.path.join(sysprm_dir, sys_file_raw)
                srt_file = srt_file_raw if os.path.isabs(srt_file_raw) else os.path.join(english_subs_dir, srt_file_raw)

                output_file = checkpoint_data['output_file']
                current_index = checkpoint_data['current_index']
                processed = checkpoint_data.get('processed', 0)
                total_main_cost = checkpoint_data.get('total_main_cost', checkpoint_data.get('total_cost', 0.0))
                total_judge_cost = checkpoint_data.get('total_judge_cost', 0.0)
                context_state = checkpoint_data['context_state']
                current_checkpoint_file = config["checkpoint_file_path"] # The actual path to the .json file
                
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

                max_num = 0
                while True:
                    max_num += 1
                    current_checkpoint_file = os.path.join(checkpoint_dir, f"translator_checkpoint_{max_num}.json")
                    if not os.path.exists(current_checkpoint_file):
                        try:
                            with open(current_checkpoint_file, 'w', encoding='utf-8') as f:
                                json.dump({"pid": os.getpid(), "processed": 0, "status": "initializing"}, f)
                            break
                        except Exception:
                            continue

                base_name = os.path.basename(srt_file)
                output_file = os.path.join(output_dir, base_name.replace('.srt', f'_{model_cfg["name"]}_heb.srt'))
                self.current_output_file = output_file
                current_index = 0
                processed = 0
                total_main_cost = 0.0
                total_judge_cost = 0.0
                log(self.log_queue, session_log_file, f"\n📁 Creating new Checkpoint File: {current_checkpoint_file}")

            # Initial terminal info
            log(self.log_queue, session_log_file, f"📝 Target File: {os.path.basename(srt_file)}")
            if resume_mode:
                log(self.log_queue, session_log_file, f"🔄 Resuming from index: {current_index}")

            with open(sys_file, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            clean_lines = [line for line in lines if not line.strip().startswith("//")]
            raw_sysprm = "".join(clean_lines).strip()
            
            if "===" in raw_sysprm:
                parts = [p.strip() for p in raw_sysprm.split("===")]
                initial_context_str = parts[0] if len(parts) >= 2 else "{}"
                series_context = parts[1] if len(parts) >= 2 else parts[0]
                prompt_prefix = ""
            else:
                try:
                    sysprm_json = json.loads(raw_sysprm)
                    prompt_prefix = sysprm_json.get("prompt_prefix", "")
                    if "series_context_lines" in sysprm_json:
                        series_context = "\n".join(sysprm_json["series_context_lines"])
                    else:
                        series_context = sysprm_json.get("series_context", "")
                        
                    initial_context_dict = {k: v for k, v in sysprm_json.items() if k not in ["prompt_prefix", "series_context", "series_context_lines"]}
                    initial_context_str = json.dumps(initial_context_dict, ensure_ascii=False)
                except json.JSONDecodeError as e:
                    self.log_queue.put(f"⚠️ Error parsing sysprm JSON: {e}")
                    initial_context_str = "{}"
                    prompt_prefix = ""
                    series_context = raw_sysprm

            if not resume_mode: log(self.log_queue, session_log_file, "✅ Loaded project-specific context from sysprm.")

            # Calculate dynamic serial indexes based on the project sysprm context
            import re
            last_idx = 0
            if series_context:
                matches = re.findall(r'###\s*(\d+)\.', series_context)
                if matches:
                    last_idx = max([int(m) for m in matches])
            
            idx_workflow = last_idx + 1
            idx_tech = idx_workflow + 1
            idx_clean = idx_tech + 1
            
            # Modular System Instruction Assembly
            use_scratchpad = model_cfg.get("enable_scratchpad", True)
            
            workflow_steps = [STEP_READ_CONTEXT, STEP_CONTEXT_PRIMING]
            
            if use_scratchpad:
                # Quality Mode: Add full reasoning stack
                workflow_steps.append(STEP_CONTINUOUS_DRAFT)
                workflow_steps.append(STEP_MAPPING_PLAN)
                
            workflow_steps.append(STEP_SRT_SPLIT_RULES)
            workflow_steps.append(STEP_FINAL_SRT)
            # Metadata bookkeeping happens after the core work
            workflow_steps.append(STEP_METADATA_UPDATE)
            workflow_steps.append(STEP_SELF_AUDIT)
            
            # Format internal steps with correct numbers (שלב 1, 2, ...)
            formatted_steps = []
            for i, step_text in enumerate(workflow_steps, 1):
                formatted_steps.append(step_text.replace("{n}", str(i)))
                
            sys_inst_header = STEP_HEADER.replace("[IDX_WORKFLOW]", str(idx_workflow))
            sys_inst = sys_inst_header + "\n" + "\n".join(formatted_steps)
            
            tech_rules = GLOBAL_TECHNICAL_RULES.replace("[IDX_TECH]", str(idx_tech)).replace("[IDX_CLEAN]", str(idx_clean))
            
            # Inject specific rule for Efficiency Mode (No Scratchpad)
            if not use_scratchpad:
                tech_rules += f"\n\n{RULE_NO_ENGLISH}"

            system_prompt_parts = []
            if prompt_prefix:
                system_prompt_parts.append(prompt_prefix)
            if series_context:
                system_prompt_parts.append(series_context.strip())
            system_prompt_parts.append(sys_inst.strip())
            system_prompt_parts.append(tech_rules.strip())
            
            system_prompt = "\n\n".join(system_prompt_parts) + "\n"
            
            # Efficiency/Quality logging
            log(self.log_queue, session_log_file, f"🚀 [Mode: {'High-Quality (Scratchpad)' if use_scratchpad else 'Efficiency (Direct)'}] Starting translation with {model_cfg['name']}...")

                
            if not resume_mode:
                try:
                    context_state = json.loads(initial_context_str) if initial_context_str != "{}" else {}
                    if not context_state:
                         context_state = {
                            "last_two_lines_heb": [], "last_speaker_info": "לא ידוע", 
                            "speakers_gender": {}, "current_setting": "לא ידוע", "summary": "הפרק רק התחיל."
                         }
                except json.JSONDecodeError:
                    log(self.log_queue, session_log_file, "⚠️ Warning: Could not parse initial JSON. Falling back to default.")
                    context_state = {
                        "last_two_lines_heb": [], "last_speaker_info": "לא ידוע", 
                        "speakers_gender": {}, "current_setting": "לא ידוע", "summary": "הפרק רק התחיל."
                    }

            with open(srt_file, 'r', encoding='utf-8-sig') as f:
                srt_content = f.read()

            srt_content = srt_content.replace('\r\n', '\n')
            blocks = srt_content.strip().split('\n\n')
            total_blocks = len(blocks)

            eng_by_index = {}
            ordered_srt_indices = []
            for b in blocks:
                lines_b = b.split('\n')
                if len(lines_b) >= 2:
                    idx_b = lines_b[0].strip()
                    text_b = "\n".join([l.strip() for l in lines_b[2:]]).strip()
                    eng_by_index[idx_b] = text_b
                    ordered_srt_indices.append(idx_b)

            if resume_mode:
                translated_heb_by_index = load_srt_index_to_text(output_file)
                # Back-fill last 50 segments for web dashboard history
                try:
                    full_heb_history = load_srt_full_history(output_file)
                    # Find where we are in ordered_srt_indices
                    if srt_content and ordered_srt_indices: 
                        processed_indices = []
                        # Only scan up to the resume point. 
                        # Do NOT break on a missing segment (in case the LLM skipped an index previously)
                        for idx_o in ordered_srt_indices[:current_index]:
                            if idx_o in translated_heb_by_index:
                                processed_indices.append(idx_o)
                        
                        last_50_indices = processed_indices[-50:]
                        for idx_h in last_50_indices:
                            h_data = full_heb_history.get(idx_h)
                            if h_data:
                                e_text = eng_by_index.get(idx_h, "")
                                self.ui_queue.put(("segment", (idx_h, h_data["time"], e_text, h_data["text"])))
                except Exception as e:
                    log(self.log_queue, session_log_file, f"⚠️ Warning: History back-fill failed: {e}")
            else:
                translated_heb_by_index = {}

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
            # ─────────────────────────────────────────────────────────────

            start_time = time.time()
            session_processed = 0
            success_streak = 0

            log(self.log_queue, session_log_file, f"\n🚀 Starting Protected AI Translation with {model_cfg['name']}")
            
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
                    upcoming_cues = []
                    for b_up in blocks[current_index : current_index + 2]:
                        l_up = b_up.split('\n')
                        if len(l_up) >= 2:
                            upcoming_cues.append({
                                "index": l_up[0].strip(),
                                "time": l_up[1].strip(),
                                "text": "\n".join([line.strip() for line in l_up[2:]]).strip()
                            })
                    self.ui_queue.put(("upcoming", upcoming_cues))

                    current_batch_size = effective_batch_size
                    batch_success = False
                    min_batch_failures = 0  # at size 2, allow up to 3 attempts before total failure
                    attempted_strides = []  # strides tried this chunk; on success after retries, effective = one-before-last
                    failures_at_current_stride = 0  # need 2 failures at same stride before shrinking (avoids one-off glitches)

                    last_judge_error = ""      # הטקסט של השגיאה
                    last_judged_indices = set() # האינדקסים שהיו בתוך ה-Chunk שנפסל
                    previous_overlong_indices = set() # עקביות אחר שורות ארוכות מדי לצורך תיקון אוטומטי
                    pipeline_start_time = time.time()
                    while not batch_success and not self.should_stop:
                        batch_diagnostics_logged = False
                        this_attempt_auditor_flagged = False  # reset each attempt
                        attempted_strides.append(current_batch_size)
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
                        
                        original_metadata = []
                        for b in chunk:
                            lines_b = b.split('\n')
                            if len(lines_b) >= 2:
                                idx_b = lines_b[0].strip()
                                time_b = lines_b[1].strip()
                                text_b = "\n".join([l.strip() for l in lines_b[2:]]).strip()
                                original_metadata.append({
                                    "index": idx_b,
                                    "timestamp": time_b,
                                    "text": text_b
                                })
                        
                        text_chunk_parts = []
                        if prev_context_blocks: 
                            text_chunk_parts.append(f"### [הקשר קודם - לא לתרגום] ###\n{strip_srt(prev_context_blocks)}\n")
                        
                        input_payload = { m['index']: m['text'] for m in original_metadata }
                        pipeline_load = sum(len(str(v)) for v in input_payload.values())
                        for idx, txt in input_payload.items():
                            # If line is only SDH tags + punctuation, force empty string
                            if re.fullmatch(r"[-.\s]*[\[(].*?[\])][-.\s]*", txt):
                                input_payload[idx] = "" 

                        # --- Italic Passthrough: Pre-Processing ---
                        # We identify subtitles entirely wrapped in <i>...</i>
                        # We strip them to make the LLM's job easier and prevent \nt artifacts.
                        batch_italic_indices = set()
                        final_input_payload = {}
                        for idx, txt in input_payload.items():
                            stripped_txt = txt.strip()
                            # Check if the text starts with <i> and ends with </i> and has NO other tag pairs in between
                            # A simple check: starts/ends with tags + only one occurrence of the opening tag.
                            if stripped_txt.startswith('<i>') and stripped_txt.endswith('</i>') and stripped_txt.count('<i>') == 1:
                                final_input_payload[idx] = stripped_txt[3:-4].strip()
                                batch_italic_indices.add(idx)
                            else:
                                final_input_payload[idx] = txt

                        text_chunk_parts.append(f"### [בלוקים לתרגום - JSON] ###\n{json.dumps(final_input_payload, ensure_ascii=False, indent=2)}\n")
                        
                        if next_context_blocks: 
                            text_chunk_parts.append(f"### [הקשר הבא - לא לתרגום] ###\n{strip_srt(next_context_blocks)}\n")
                        
                        text_chunk = '\n'.join(text_chunk_parts)
                        indices = [d['index'] for d in original_metadata]
                        
                        summary_text = context_state.get('summary', 'הפרק רק התחיל.')
                        last_speaker = context_state.get('last_speaker_info') or context_state.get('last_speaker', 'לא ידוע')
                        setting = context_state.get('current_setting', 'לא ידוע')
                        
                        last_lines = context_state.get('last_two_lines_heb', [])
                        last_line_str = f"שורה מתורגמת אחרונה (מהבאץ' הקודם): '{last_lines[-1]}'" if last_lines else ""
                        
                        continuity_note = context_state.get('continuity_note', '')
                        continuity_str = f"⚠️ הערת רציפות מהבאץ' הקודם (שים לב!): {continuity_note}" if continuity_note and continuity_note.strip() else ""

                        context_section_lines = [
                            "### הסיפור עד כה (הקשר קודם) ###",
                            f"מיקום נוכחי: {setting}",
                            f"תקציר האירועים: {summary_text}",
                            f"הדובר האחרון בבאץ' הקודם: {last_speaker}"
                        ]
                        if last_line_str: context_section_lines.append(last_line_str)
                        if continuity_str: context_section_lines.append(continuity_str)
                            
                        context_section = '\n'.join(context_section_lines)

                        # Structured Outputs check for prompt optimization
                        supports_structured = (model_cfg.get('provider') in ['openai', 'lmstudio'] and 
                                             (model_cfg.get('provider') == 'lmstudio' or any(m in model_cfg.get('name', '').lower() for m in ["gpt-4o", "gpt-4o-mini", "o1"])))

                        # Use Lite Schema for Efficiency Mode if Structured Output isn't being used 
                        # (even if it is, this ensures parity in the prompt instructions)
                        active_schema_template = JSON_SCHEMA_LITE if not use_scratchpad else JSON_SCHEMA_TEMPLATE
                        schema_instruction = f"\n{active_schema_template}\n" if not supports_structured else "\n### חובה: השב בפורמט ה-JSON Schema המוגדר בלבד. ###\n"



                        
                        # Dynamic Rule Injection: Formatting Tags
                        # Only show the tag preservation rule if tags or music symbols are actually present in this batch.
                        has_tags = any("<" in str(val) or "♪" in str(val) for val in input_payload.values())
                        tag_rule = ""
                        if has_tags:
                            tag_rule = "4. תגיות עיצוב (Formatting Tags): שמור על תגיות כמו <i> או <font color=\"...\"> בדיוק במיקומן המקורי. אל תתרגם מילים טכניות (כמו 'color') ואל תמחק אותן. **חשוב: מותר (ואף חובה) להוסיף ירידת שורה `\\n` בתוך תגיות (למשל `<i>טקסט...\\n...טקסט</i>`) כדי לשמור על חוק 8 המילים לשורה.** וודא שערכי צבע מוקפים במירכאות.\n"

                        user_prompt = f"""
אתה מתרגם עכשיו את הבאץ' הבא. זכור: הפלט חייב להיות בעברית בלבד.

{context_section}

{text_chunk}

### חוקים טכניים חובה ###
1. ספירה מדויקת: **חובה עליך להחזיר בדיוק {expected_count} מפתחות באובייקט 'translated_srt'.**
2. אינדקסים מדויקים: השתמש בדיוק באינדקסים הבאים כמפתחות: {', '.join(indices)}.
3. **אל תתרגם ואל תכלול בפלט** אף מילה המופיעה בבלוקי ה"הקשר" (בכל שדה שהוא).
{tag_rule}
{schema_instruction}
"""


                        feedback_injection = ""
                        # אם יש שגיאה מהשופט, ויש לפחות אינדקס אחד משותף בין הבאץ' הנוכחי לבאץ' שנפסל
                        if last_judge_error and set(indices).intersection(last_judged_indices):
                            feedback_injection = "\n### חובה לתקן את השגיאות הבאות לפי אינדקס (אל תחזור על טעויות אלו): ###\n"
                            if isinstance(last_judge_error, dict):
                                for err_idx, err_msg in last_judge_error.items():
                                    if err_idx in ["GLOBAL", "GENERAL", "general"] or str(err_idx).startswith("chunk_") or err_idx in indices or str(err_idx) in [str(i) for i in indices]:
                                        prefix = f"אינדקס {err_idx}: " if err_idx not in ["GLOBAL", "GENERAL", "general"] and not str(err_idx).startswith("chunk_") else ""
                                        feedback_injection += f"{prefix}{err_msg}\n"
                            else:
                                feedback_injection += f"{last_judge_error}\n"
                            feedback_injection += "----------------------------------------\n"
                        final_prompt = user_prompt + feedback_injection

                        raw_res = None
                        _batch_system_prompt = system_prompt
                        _batch_user_prompt = final_prompt
                        try:
                            log(self.log_queue, session_log_file, f"⏳ Sending Batch (Indices: {indices[0]}-{indices[-1]} | cues: {expected_count}, stride: {current_batch_size})...")
                            is_retry = (len(attempted_strides) > 1)
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

                            raw_res, in_tokens, out_tokens, cached_tokens, reasoning_tokens = call_llm(model_cfg, system_prompt, final_prompt, api_key, indices_list=indices)

                            if getattr(self, 'debug_mode', False) and raw_res:
                                timestamp_str = datetime.datetime.now().strftime("%H:%M:%S")
                                file_log(session_log_file, f"\n[{timestamp_str}] --- DEBUG TRANSACTION ---")
                                file_log(session_log_file, f"SYSTEM PROMPT:\n{system_prompt.strip()}\n")
                                file_log(session_log_file, f"USER PROMPT:\n{final_prompt.strip()}\n")
                                
                                # Log Structured Output Schema if batch indices are present
                                if indices:
                                    # Use the same logic as the real call to ensure the log is accurate
                                    schema_dump = json.dumps(generate_batch_schema(indices, use_scratchpad=use_scratchpad), ensure_ascii=False, indent=2)
                                    file_log(session_log_file, f"STRUCTURED OUTPUT SCHEMA:\n{schema_dump}\n")

                                    
                                file_log(session_log_file, f"RAW LLM RESPONSE:\n{raw_res.strip()}\n{'-'*38}\n")

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
                            discount = model_cfg.get('cache_discount', 0.0)
                            hit_pct = 0  # default; overwritten below when cache discount is active

                            if discount > 0 and in_tokens > 0:
                                miss_tokens = in_tokens - cached_tokens
                                # Calculate discounted price based on the percentage provided in settings
                                cache_hit_price = model_cfg['input_price'] * (1 - (discount / 100.0))
                                batch_cost = (miss_tokens / 1e6 * model_cfg['input_price']) + (cached_tokens / 1e6 * cache_hit_price) + (out_tokens / 1e6 * model_cfg['output_price'])
                                hit_pct = (cached_tokens/in_tokens*100)
                                hit_str = f" [Hit: {cached_tokens:,} ({hit_pct:.1f}%)]"
                            else:
                                batch_cost = (in_tokens / 1e6 * model_cfg['input_price']) + (out_tokens / 1e6 * model_cfg['output_price'])
                                hit_str = ""

                            # V3 Telemetry Hook: Speed and Cache
                            if self.shared_state:
                                chars_per_sec = batch_load / _call_duration if _call_duration > 0 else 0
                                self.shared_state.update_telemetry(cache_hit_percent=int(hit_pct), tokens_per_sec=chars_per_sec)                                
                            
                            brain_load = (reasoning_tokens / out_tokens * 100) if out_tokens > 0 else 0
                            brain_str = f" | 🧠 Brain: {reasoning_tokens:,} ({brain_load:.1f}%)" if reasoning_tokens > 0 else ""

                            total_main_cost += batch_cost
                            
                            # Immediate GUI update
                            self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                            
                            # Immediate Terminal logging
                            def fmt_val(v): return f"{int(v):,}" if v > 100 else f"${v:.5f}"
                            log(self.log_queue, session_log_file, f"💰 [Main Model] Batch: {fmt_val(batch_cost)} (In: {in_tokens:,}{hit_str} / Out: {out_tokens:,}{brain_str}) | Total Main: {fmt_val(total_main_cost)}")

                            cleaned_res = pre_repair_json(raw_res)
                            try:
                                res_json = json.loads(cleaned_res)
                            except json.JSONDecodeError:
                                _inc_by_size(stats["json_parse_errors"], current_batch_size)
                                raise

                            # Auditor Warning for Placeholder Copy-Pasting
                            if "<הכנס כאן" in cleaned_res or "<חובה למלא" in cleaned_res:
                                log(self.log_queue, session_log_file, "⚠️ AUDITOR WARNING: The LLM responded with identical placeholder text from the prompt template!")

                            # Schema Recovery Layer: Handle GPT-5 key hallucinations
                            recovered = False
                            if 'translated_srt' not in res_json:
                                possible_keys = ["translation", "translations", "translated", "result", "output", "data"]
                                for pk in possible_keys:
                                    if pk in res_json and isinstance(res_json[pk], dict):
                                        res_json['translated_srt'] = res_json[pk]
                                        recovered = True
                                        log(self.log_queue, session_log_file, f"   ↳ 💡 Recovered schema from hallucinated key: '{pk}'")
                                        break
                                
                                if not recovered:
                                    # Search for any dictionary that contains numeric keys
                                    for key, value in res_json.items():
                                        if isinstance(value, dict) and any(str(k).isdigit() for k in value.keys()):
                                            res_json['translated_srt'] = value
                                            recovered = True
                                            log(self.log_queue, session_log_file, f"   ↳ 💡 Recovered schema from inferred dictionary: '{key}'")
                                            break
                                
                                if not recovered:
                                    # Last ditch: Check if the ROOT object itself has numeric keys
                                    if any(str(k).isdigit() for k in res_json.keys()):
                                        # To avoid losing the original structure if needed, wrap it
                                        res_json = {'translated_srt': res_json}
                                        recovered = True
                                        log(self.log_queue, session_log_file, "   ↳ 💡 Recovered schema from root-level flat dictionary")

                                if recovered:
                                    stats["schema_recoveries"] += 1  # track successful recovery

                            if 'translated_srt' not in res_json or not isinstance(res_json['translated_srt'], dict):
                                raise ValueError(f"Schema collapse: 'translated_srt' missing. Found: {list(res_json.keys())}")

                            received_dict = res_json['translated_srt']

                            # --- Italic Passthrough: Post-Processing ---
                            # Restore global italics for identified indices
                            if batch_italic_indices:
                                restored_count = 0
                                for idx in batch_italic_indices:
                                    if idx in received_dict:
                                        heb_text = str(received_dict[idx]).strip()
                                        if heb_text and not (heb_text.startswith('<i>') and heb_text.endswith('</i>')):
                                            received_dict[idx] = f"<i>{heb_text}</i>"
                                            restored_count += 1
                                if restored_count > 0:
                                    log(self.log_queue, session_log_file, f"✨ [Italic Passthrough] Restored global italics for indices: {', '.join(sorted(batch_italic_indices))}")

                            changes_detected = []
                            repaired_ghost_indices = []
                            for idx in received_dict:
                                original_val = str(received_dict[idx])
                                
                                # 1. Standard newline cleanup
                                cleaned_val = re.sub(r'\s*\\+[nננ]\s*', '\n', original_val)
                                
                                # 2. NEW: Ghost Character Sanitizer (e.g., \nt, \ns echoing original English)
                                # This removes 1-2 english letters immediately after a newline if followed by Hebrew or whitespace
                                ghost_pattern = r'\n[a-zA-Z]{1,2}(?=\s|[א-ת]|<|♪)'
                                if re.search(ghost_pattern, cleaned_val):
                                    cleaned_val = re.sub(ghost_pattern, '\n', cleaned_val)
                                    repaired_ghost_indices.append(idx)
                            
                                # Check if changed
                                if cleaned_val != original_val:
                                    changes_detected.append(idx)
                                    received_dict[idx] = cleaned_val

                            # Logging repairs
                            if changes_detected:
                                if repaired_ghost_indices:
                                    log(self.log_queue, session_log_file, f"🧹 [Sanitizer] Removed English ghost fragments in indices: {', '.join(repaired_ghost_indices)}")
                                log(self.log_queue, session_log_file, f"🧹 [Sanitizer] Fixed escaped line breaks or formatting in indices: {', '.join(changes_detected)}")
                                stats["sanitizer_fixes"] += 1

                            for idx in indices:
                                if idx not in received_dict:
                                    raise ValueError(f"Sync Error: Key '{idx}' missing")

                            strip_music_glyphs_batch(received_dict)

                            illegal_labels = context_state.get("illegal_labels", [])
                            is_suspicious, audit_reason, heb_audit_reason, skip_judge = check_heuristics(input_payload, received_dict, illegal_labels=illegal_labels)
                            
                            # Forced Escalation for Repairs
                            if changes_detected:
                                is_suspicious = True
                                repair_note = f"IDX:{','.join(repaired_ghost_indices)}|בוצע תיקון אוטומטי להסרת שאריות אנגלית (Ghost fragments). וודא היטב שהמשפט תקין וזורם." if repaired_ghost_indices else "בוצע תיקון אוטומטי לפורמט השורות (n\\)."
                                heb_audit_reason = f"{repair_note}; {heb_audit_reason}" if heb_audit_reason else repair_note
                                audit_reason = f"Repaired by Sanitizer; {audit_reason}" if audit_reason else "Repaired by Sanitizer"

                            if is_suspicious:
                                this_attempt_auditor_flagged = True  # mark for clean-pass tracking

                                if not batch_diagnostics_logged:
                                    file_log(session_log_file, f"--- BATCH {indices[0] if indices else '?'}-{indices[-1] if indices else '?'} DIAGNOSTICS (PRIMARY) ---")
                                    file_log(session_log_file, f"SYSTEM PROMPT:\n{_batch_system_prompt}")
                                    file_log(session_log_file, f"USER PROMPT:\n{_batch_user_prompt}")
                                    file_log(session_log_file, f"RAW LLM RESPONSE:\n{raw_res}\n--------------------------------------")
                                    batch_diagnostics_logged = True

                                if skip_judge:
                                    # אם יש לנו הערה בעברית מהאודיטור, נשתמש בה. 
                                    # אם היא ריקה (כי שלחנו לשופט), נשתמש רק בתוצאה של השופט בהמשך.
                                    parsed_audit_map = {}
                                    for p in heb_audit_reason.split("; "):
                                        if "|" in p:
                                            scope, msg = p.split("|", 1)
                                            if scope.startswith("IDX:"):
                                                idx_list = scope[4:].split(",")
                                                for idx_val in idx_list:
                                                    parsed_audit_map[idx_val] = parsed_audit_map.get(idx_val, "") + msg + " "
                                            else:
                                                parsed_audit_map["GLOBAL"] = parsed_audit_map.get("GLOBAL", "") + msg + " "
                                        else:
                                            if p.strip():
                                                parsed_audit_map["GENERAL"] = parsed_audit_map.get("GENERAL", "") + p + " "
                                    
                                    # Cleanup extra spaces
                                    parsed_audit_map = {k: v.strip() for k, v in parsed_audit_map.items()}
                                    
                                    # === NEW: Stubbornness Fallback (Auto-Correction) ===
                                    # אם אנחנו בבאץ' מינימלי (2) והאודיטור מזהה שוב את אותה בעיית אורך מילים, נתקן אוטומטית.
                                    fixed_any = False
                                    if current_batch_size == 2:
                                        overlong_in_this_attempt = {idx for idx, msg in parsed_audit_map.items() if "9 מילים" in msg}
                                        
                                        # אם האינדקס כבר הופיע כ"ארוך מדי" בניסיון הקודם של הבאץ' הזה
                                        indices_to_fix = overlong_in_this_attempt.intersection(previous_overlong_indices)
                                        
                                        if indices_to_fix:
                                            for idx_to_fix in indices_to_fix:
                                                # וודא שזו השגיאה היחידה לאינדקס הזה (כדי לא לפספס הזיות או אנגלית)
                                                if parsed_audit_map[idx_to_fix].strip() == "נמצאה שורה ארוכה מדי (מעל 9 מילים).":
                                                    old_text = received_dict[idx_to_fix]
                                                    new_text = force_split_overlong_line(old_text)
                                                    if new_text != old_text:
                                                        received_dict[idx_to_fix] = new_text
                                                        fixed_any = True
                                                        log(self.log_queue, session_log_file, f"💡 Stubborn model detected. Applying programmatic split for index {idx_to_fix}.")
                                        
                                        # עדכון הזיכרון לניסיון הבא (אם יהיה)
                                        previous_overlong_indices = overlong_in_this_attempt

                                    if fixed_any:
                                        # הרצה חוזרת של האודיטור כדי לראות אם התיקון הספיק
                                        is_suspicious, audit_reason, heb_audit_reason, skip_judge = check_heuristics(input_payload, received_dict, illegal_labels=illegal_labels)
                                        if not is_suspicious:
                                            # התיקון האוטומטי עבר! נמשיך כאילו הכל תקין.
                                            log(self.log_queue, session_log_file, f"✅ Programmatic split resolved the issue. Proceeding...")
                                            # We don't raise ValueError, so the loop continues to 'batch_success = True' eventually
                                        elif not skip_judge:
                                            # התיקון עזר חלקית אבל עדיין צריך שופט
                                            pass 
                                        else:
                                            # עדיין דורש ריטריי (אולי בעיה אחרת צצה)
                                            last_judge_error = parsed_audit_map
                                            last_judged_indices = set(indices)
                                            _inc_by_size(stats["auditor_skip_judge"], current_batch_size)
                                            log(self.log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Immediate retry (skipping Judge).")
                                            raise ValueError(f"Heuristic Rejection (post-fix): {audit_reason}")
                                    else:
                                        last_judge_error = parsed_audit_map
                                        last_judged_indices = set(indices)
                                        _inc_by_size(stats["auditor_skip_judge"], current_batch_size)
                                        log(self.log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Immediate retry (skipping Judge).")
                                        # V3 Audit Hook: Auditor Rejection Ruling
                                        if self.shared_state:
                                            self.shared_state.update_audit(last_decision="Auditor: Failed & Retry", batch_trend=-1)
                                        raise ValueError(f"Heuristic Rejection (skip judge): {audit_reason}")

                                _inc_by_size(stats["auditor_sent_to_judge"], current_batch_size)
                                log(self.log_queue, session_log_file, f"🔍 Auditor Flag: {audit_reason}. Calling Judge...")
                                # V3 Audit Hook: Auditor Passing Ruling
                                if self.shared_state:
                                    self.shared_state.update_audit(last_decision="Auditor: Sent to Judging", batch_trend=0)
                                self.ui_queue.put(("judge_start", None))
                                
                                judge_cfg = config["judge_cfg"]
                                judge_api_key = config["judge_api_key"]
                                judge_batch_size = config["judge_batch_size"]
                                
                                j_start = time.time()
                                is_valid, judge_reason, j_in, j_out, j_cached, j_reasoning = call_llm_judge(
                                    judge_cfg, indices, input_payload, received_dict, judge_api_key,
                                    judge_batch_size=judge_batch_size,
                                    ordered_srt_indices=ordered_srt_indices,
                                    eng_by_index=eng_by_index,
                                    heb_completed_by_index=translated_heb_by_index,
                                    log_func=lambda m: log(self.log_queue, session_log_file, m),
                                    file_log_func=lambda m: file_log(session_log_file, m),
                                    audit_reason_heb=heb_audit_reason,
                                    progress_func=lambda c, t: self.ui_queue.put(("judge_progress", (c, t))),
                                    ui_queue=self.ui_queue
                                )
                                self.ui_queue.put(("judge_stop", None))

                                # ── Track judge activity ───────────────────
                                _inc_by_size(stats["judge_invocations"], current_batch_size)
                                # ──────────────────────────────────────────
                                
                                # JUDGE Cost Calculation
                                j_discount = judge_cfg.get('cache_discount', 0.0)
                                if j_discount > 0 and j_in > 0:
                                    j_miss = j_in - j_cached
                                    j_hit_price = judge_cfg['input_price'] * (1 - (j_discount / 100.0))
                                    j_cost = (j_miss / 1e6 * judge_cfg['input_price']) + (j_cached / 1e6 * j_hit_price) + (j_out / 1e6 * judge_cfg['output_price'])
                                    j_hit_pct = (j_cached / j_in * 100)
                                    j_hit_str = f" [Hit: {j_cached:,} ({j_hit_pct:.1f}%)]"
                                else:
                                    j_cost = (j_in / 1e6 * judge_cfg['input_price']) + (j_out / 1e6 * judge_cfg['output_price'])
                                    j_hit_str = ""
                                
                                j_brain_load = (j_reasoning / j_out * 100) if j_out > 0 else 0
                                j_brain_str = f" | 🧠 Brain: {j_reasoning:,} ({j_brain_load:.1f}%)" if j_reasoning > 0 else ""

                                total_judge_cost += j_cost
                                
                                # Immediate GUI update
                                self.ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
                                
                                # Immediate Terminal logging
                                log(self.log_queue, session_log_file, f"⚖️ [Judge Model] Batch: {fmt_val(j_cost)} (In: {j_in:,}{j_hit_str} / Out: {j_out:,}{j_brain_str}) | Total Judge: {fmt_val(total_judge_cost)}")
                                file_log(session_log_file, f"⚖️ Judge Stats (Batch {indices[0]}-{indices[-1]}) - Tokens: In {j_in:,} / Out {j_out:,}{j_brain_str} | Total Judge Cost: ${total_judge_cost:.5f}")

                                if not is_valid:
                                    if judge_reason == "FAILED":
                                        # Judge itself errored — declare ruling as FAILED and use auditor output as retry feedback
                                        log(self.log_queue, session_log_file, "   ↳ ❌ Judge ruling: FAILED (judge error). Retrying with auditor feedback.")
                                        parsed_audit_map = {}
                                        for p in heb_audit_reason.split("; "):
                                            if "|" in p:
                                                scope, msg = p.split("|", 1)
                                                if scope.startswith("IDX:"):
                                                    idx_list = scope[4:].split(",")
                                                    for idx_val in idx_list:
                                                        parsed_audit_map[idx_val] = parsed_audit_map.get(idx_val, "") + msg + " "
                                                else:
                                                    parsed_audit_map["GLOBAL"] = parsed_audit_map.get("GLOBAL", "") + msg + " "
                                            else:
                                                if p.strip():
                                                    parsed_audit_map["GENERAL"] = parsed_audit_map.get("GENERAL", "") + p + " "
                                        parsed_audit_map = {k: v.strip() for k, v in parsed_audit_map.items()}
                                        last_judge_error = parsed_audit_map
                                        _inc_by_size(stats["judge_failed_errors"], current_batch_size)
                                    else:
                                        # Normal judge rejection — use judge's error map as feedback
                                        last_judge_error = judge_reason
                                        _inc_by_size(stats["judge_rejections"], current_batch_size)
                                    
                                    # V3 Audit Hook: Judge Rejection Ruling
                                    if self.shared_state:
                                        self.shared_state.update_audit(last_decision="Judge: Failed & Retry", batch_trend=-1)

                                    last_judged_indices = set(indices)
                                    raise ValueError("Judge Rejection")
                                else:
                                    last_judge_error = ""
                                    last_judged_indices = set()
                                    _inc_by_size(stats["judge_approvals"], current_batch_size)
                                    _inc_by_size(stats["judge_approved_passes_by_size"], current_batch_size)
                                    
                                    # V3 Audit Hook: Judge Approval Ruling
                                    if self.shared_state:
                                        self.shared_state.update_audit(last_decision="Judge: Approved", batch_trend=1)

                                    msg = f"✅ Judge Approved: {judge_reason}" if judge_reason and judge_reason != {} else "✅ Judge Approved"
                                    log(self.log_queue, session_log_file, msg)

                            translated_lines = []
                            for m in original_metadata:
                                idx = m['index']
                                heb_text = received_dict[idx]
                                translated_lines.append(f"{idx}\n{m['timestamp']}\n{fix_rtl(heb_text)}")
                                # Emit each successful segment for high-frequency web dashboard updates. 
                                # Note: We use RAW heb_text here because it's already 'Logical RTL' from the LLM.
                                self.ui_queue.put(("segment", (idx, m['timestamp'], m['text'], heb_text)))
                            
                            f_out.write('\n\n'.join(translated_lines) + '\n\n')
                            f_out.flush()

                            for m in original_metadata:
                                translated_heb_by_index[m['index']] = fix_rtl(received_dict[m['index']])
                            
                            # Harvest flattened context state from response root
                            context_state['summary'] = res_json.get('summary', context_state.get('summary'))
                            context_state['last_speaker_info'] = res_json.get('last_speaker_info', context_state.get('last_speaker_info'))
                            context_state['continuity_note'] = res_json.get('continuity_note', context_state.get('continuity_note'))
                            if indices:
                                last_idx = indices[-1]
                                context_state['last_two_lines_heb'] = [received_dict[last_idx]]

                            processed += expected_count 
                            session_processed += expected_count
                            batch_success = True

                            # ── Batch success tracking ─────────────────────
                            stats["total_batches_succeeded"] += 1
                            
                            # Forensic Linguistic Analysis
                            linc = stats.get("linguistics", {})
                            for m in original_metadata:
                                idx = m['index']
                                eng = m['text']
                                heb = received_dict.get(idx, "").strip()
                                
                                # Character & Word Load (Defensive increment)
                                linc["source_chars"] = linc.get("source_chars", 0) + len(eng)
                                linc["source_words"] = linc.get("source_words", 0) + len(eng.split())
                                
                                # Punctuation Flux & Musicality
                                linc["source_punct"] = linc.get("source_punct", 0) + len(re.findall(r'[!.?]', eng))
                                linc["music_symbols"] = linc.get("music_symbols", 0) + len(re.findall(r'[♪♫#]', eng))
                                
                                if not heb:
                                    linc["empty_subs"] = linc.get("empty_subs", 0) + 1
                                    if re.search(r"[\[(].*?[\])]", eng):
                                        linc["sdh_filtered"] = linc.get("sdh_filtered", 0) + 1
                                else:
                                    linc["target_chars"] = linc.get("target_chars", 0) + len(heb)
                                    linc["target_words"] = linc.get("target_words", 0) + len(heb.split())
                                    linc["target_punct"] = linc.get("target_punct", 0) + len(re.findall(r'[!.?]', heb))
                                    if "\n" in heb:
                                        linc["multiline_subs"] = linc.get("multiline_subs", 0) + 1
                                        
                                    # Track Extremes (Longest Target)
                                    h_len = len(heb)
                                    h_words = len(heb.split())
                                    
                                    # Ensure extreme dicts exist
                                    if "longest_target_chars" not in linc: linc["longest_target_chars"] = {"index": -1, "value": 0}
                                    if "longest_target_words" not in linc: linc["longest_target_words"] = {"index": -1, "value": 0}
                                    
                                    if h_len > linc["longest_target_chars"]["value"]:
                                        linc["longest_target_chars"] = {"index": idx, "value": h_len}
                                    if h_words > linc["longest_target_words"]["value"]:
                                        linc["longest_target_words"] = {"index": idx, "value": h_words}

                                # Track Extremes (Longest Source)
                                e_len = len(eng)
                                e_words = len(eng.split())
                                
                                # Ensure extreme dicts exist
                                if "longest_source_chars" not in linc: linc["longest_source_chars"] = {"index": -1, "value": 0}
                                if "longest_source_words" not in linc: linc["longest_source_words"] = {"index": -1, "value": 0}
                                
                                if e_len > linc["longest_source_chars"]["value"]:
                                    linc["longest_source_chars"] = {"index": idx, "value": e_len}
                                if e_words > linc["longest_source_words"]["value"]:
                                    linc["longest_source_words"] = {"index": idx, "value": e_words}

                            # Engine Reasoning & Trust
                            if this_attempt_auditor_flagged:
                                # If we reached here, it means batch_success is True. 
                                # If it was flagged but succeeded, it was a Judge Approval (or a retry pass).
                                # We count it as 'Sensitivity' metric.
                                stats["auditor_false_positives"] = stats.get("auditor_false_positives", 0) + 1

                            if len(attempted_strides) == 1 and not this_attempt_auditor_flagged:
                                _inc_by_size(stats["clean_passes_by_size"], current_batch_size)
                            # ──────────────────────────────────────────────

                            # ── Pipeline Velocity Telemetry ───────────────
                            pipeline_duration = time.time() - pipeline_start_time
                            pipeline_velocity = pipeline_load / pipeline_duration if pipeline_duration > 0 else 0
                            self.ui_queue.put(("pipeline_telemetry", pipeline_velocity))
                            if self.shared_state:
                                self.shared_state.update_telemetry(tokens_per_sec=pipeline_velocity)
                            # ──────────────────────────────────────────────

                            self.ui_queue.put(("batch_success", None))
                            
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
                                file_log(session_log_file, f"SYSTEM PROMPT:\n{_batch_system_prompt}")
                                file_log(session_log_file, f"USER PROMPT:\n{_batch_user_prompt}")
                                if raw_res is not None:
                                    file_log(session_log_file, f"RAW LLM RESPONSE:\n{raw_res}")
                                else:
                                    file_log(session_log_file, f"RAW LLM RESPONSE: None (call_llm failed)")
                                file_log(session_log_file, f"ERROR: {e}")
                                batch_diagnostics_logged = True
                            else:
                                file_log(session_log_file, f"⚠️ Batch retry failure event for {batch_label} (Retry action follows).")
                            
                            if current_batch_size <= 2:
                                min_batch_failures += 1
                                if min_batch_failures >= 3:
                                    log(self.log_queue, session_log_file, "❌ Failed minimal batch size (2) after 3 attempts. Stopping.")
                                    self.should_stop = True
                                    break
                                log(self.log_queue, session_log_file, f"🔁 Minimal batch (size 2) attempt {min_batch_failures}/3 failed; retrying same size...")
                            else:
                                failures_at_current_stride += 1
                                if failures_at_current_stride < 2:
                                    log(self.log_queue, session_log_file, f"🔁 Same stride ({current_batch_size}): first failure—retrying without reducing (guards against accidental glitches).")
                                else:
                                    failures_at_current_stride = 0
                                    reduce_by = max(3, current_batch_size // 6)
                                    current_batch_size = max(2, current_batch_size - reduce_by)
                                    stats["batch_shrink_events"] += 1
                                    log(self.log_queue, session_log_file, f"📉 Second failure at this stride; reducing by {reduce_by} → {current_batch_size} and retrying...")

                    if batch_success:
                        prev_effective = effective_batch_size
                        # If we succeeded on the FIRST attempt, increment streak
                        if len(attempted_strides) == 1:
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
                        elif len(attempted_strides) >= 2:
                            # e.g. strides 60→50→42 succeeded at 42 → next chunk uses 50 (penultimate attempt)
                            effective_batch_size = attempted_strides[-2]
                        else:
                            effective_batch_size = current_batch_size
                        if effective_batch_size != prev_effective:
                            log(self.log_queue, session_log_file, f"📌 Effective batch size → {effective_batch_size} (penultimate stride after retries; following chunks start here)")
                        current_index += expected_count

                        # ── Update accumulated elapsed time & write checkpoint ─
                        stats["total_elapsed_seconds"] = elapsed_at_session_start + (time.time() - session_start_time)
                        checkpoint_data = {
                            "pid": os.getpid(),
                            "model_choice": config["model_choice"],
                            "judge_model_choice": config["judge_model_choice"],
                            "batch_size": batch_size,
                            "effective_batch_size": effective_batch_size,
                            "judge_batch_size": config["judge_batch_size"],
                            "sys_file": config["sys_name"],
                            "srt_file": config["srt_name"],
                            "output_file": output_file,
                            "current_index": current_index,
                            "processed": processed,
                            "total_blocks": total_blocks,
                            "total_main_cost": total_main_cost,
                            "total_judge_cost": total_judge_cost,
                            "context_state": context_state,
                            "stats": stats,
                        }
                        with open(current_checkpoint_file, 'w', encoding='utf-8') as ckpt_f:
                            json.dump(checkpoint_data, ckpt_f, ensure_ascii=False, indent=4)
                    
                    total_elapsed = stats.get("total_elapsed_seconds", 0.0)
                    time_str, finish_str, eta_secs = get_eta_string(total_elapsed, processed, processed, total_blocks)

                    self.ui_queue.put(("progress", (processed, total_blocks)))
                    self.ui_queue.put(("eta", (time_str, finish_str, eta_secs)))
                        
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

                if current_checkpoint_file and os.path.exists(current_checkpoint_file):
                    os.remove(current_checkpoint_file)
                    log(self.log_queue, session_log_file, f"🧹 Cleaned up checkpoint.")
                
        except Exception as e:
            log(self.log_queue, config.get("session_log_file"), f"❌ Fatal Error: {e}")
        finally:
            self.ui_queue.put(("finished", None))
            self.ui_queue.put(("refresh", None))
