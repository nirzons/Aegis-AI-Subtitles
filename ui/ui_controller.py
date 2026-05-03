import os
import sys
import subprocess
import tkinter as tk
from tkinter import messagebox

# Internal Modules
from utils.settings import SETTINGS
from ui.gui_windows import SettingsWindow, CheckpointsWindow, LiveViewer
from utils.app_utils import log
from ui.queue_dispatcher import QueueDispatcher

class UIController:
    def __init__(self, app):
        self.app = app
        self.queue_dispatcher = QueueDispatcher(self.app, self)

    def open_settings(self):
        self.app.smoke_test_settings_opened = True
        SettingsWindow(self.app.root, self.app)

    def open_checkpoints_manager(self):
        self.app.smoke_test_checkpoints_opened = True
        CheckpointsWindow(self.app.root, self.app)

    def open_orig_srt(self): 
        path = os.path.join(self.app.english_subs_dir, self.app.ui.widgets.srt_var.get())
        if os.path.exists(path):
            subprocess.Popen(['notepad.exe', path])

    def open_translated_srt(self):
        if hasattr(self.app.engine, 'current_output_file') and self.app.engine.current_output_file:
            path = os.path.join(self.app.english_subs_dir, self.app.ui.widgets.srt_var.get())
            self.app.ui.widgets.btn_open_translated.config(state=tk.DISABLED)
            
            def re_enable():
                self.app.ui.widgets.btn_open_translated.config(state=tk.NORMAL)
                
            profile = SETTINGS.get_active_profile()
            LiveViewer(self.app.root, path, self.app.engine.current_output_file, profile=profile, on_close=re_enable)

    def open_prompt_generator(self):
        """Launches the prompt_generator.pyw utility."""
        try:
            script_path = os.path.join(self.app.curr_dir, "prompt_generator.pyw")
            if os.path.exists(script_path):
                subprocess.Popen([sys.executable, script_path])
            else:
                messagebox.showerror("Error", f"Could not find {script_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch Prompt Generator: {e}")

    def restart_app(self):
        """Cleanly restarts the entire application to reload code changes."""
        log(self.app.log_queue, self.app.session_log_file, "🔄 Restarting application to reload modules...")
        self.app.on_closing() # Trigger cleanup
        
        # Replace current process with a fresh one
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def refresh_languages_ui(self):
        from core.language_profiles import BUILT_IN_PROFILES
        codes = sorted(BUILT_IN_PROFILES.keys())
        self.app.ui.widgets.source_combo['values'] = codes
        self.app.ui.widgets.target_combo['values'] = codes
        
        # Load from settings
        trans_cfg = SETTINGS.config.get("translation", {})
        self.app.ui.widgets.source_lang_var.set(trans_cfg.get("source_lang_code", "en"))
        self.app.ui.widgets.target_lang_var.set(trans_cfg.get("target_lang_code", "he"))
        
        self.on_language_change() # Trigger initial output_dir sync

    def on_language_change(self, event=None):
        self.app.smoke_test_lang_changed = True
        source = self.app.ui.widgets.source_lang_var.get()
        target_code = self.app.ui.widgets.target_lang_var.get()
        
        # 1. Update config FIRST to ensure SETTINGS.get_active_profile() works correctly
        if "translation" not in SETTINGS.config:
            SETTINGS.config["translation"] = {}
            
        SETTINGS.config["translation"]["source_lang_code"] = source
        SETTINGS.config["translation"]["target_lang_code"] = target_code
        SETTINGS.save_settings()

        # 2. Now fetch the profile (it will reflect the new target_code)
        profile = SETTINGS.get_active_profile()

        # Update source and output directories dynamically
        self.app.english_subs_dir = os.path.join(self.app.curr_dir, f"{profile.source_lang} subtitles")
        self.app.output_dir = os.path.join(self.app.curr_dir, f"Translated {profile.target_lang} subtitles")
        
        for d in [self.app.english_subs_dir, self.app.output_dir]:
            os.makedirs(d, exist_ok=True)
        
        if not self.app.is_running:
            self.refresh_files()
            log(self.app.log_queue, self.app.session_log_file, f"🌐 Profile: {profile.source_lang} → {profile.target_lang}")

    def on_model_change(self, event=None):
        idx_str = self.app.ui.widgets.model_var.get().split(" - ")[0]
        if idx_str in SETTINGS.config["models"]:
            self.app.ui.widgets.batch_size_var.set(str(SETTINGS.config["models"][idx_str]['batch_size']))

    def on_resume_selection(self, event=None):
        import re
        resume_val = self.app.ui.widgets.resume_var.get()
        if not resume_val or resume_val.startswith("[0]"):
            self.app._reset_ui_for_new_session()
            return
        
        match = re.search(r'\[(\d+)\]', resume_val)
        if match:
            choice_idx = int(match.group(1))
            if 0 < choice_idx <= len(self.app.available_checkpoints):
                ckpt = self.app.available_checkpoints[choice_idx - 1]
                self.app._update_ui_from_checkpoint(ckpt)

    def toggle_debug_mode(self):
        self.app.smoke_test_debug_toggled = True
        is_debug = self.app.ui.widgets.debug_var.get()
        if is_debug:
            ans = messagebox.askyesno("Enable Debug Mode", "Enabling Debug Mode will write massive Input/Output transactions to the log file for EVERY batch.\n\nThis can cause your .txt log files to become extremely large.\n\nAre you sure you want to enable this?", parent=self.app.root)
            if not ans:
                self.app.ui.widgets.debug_var.set(False)
                return
                
        state_str = "ENABLED" if is_debug else "DISABLED"
        if hasattr(self.app, 'engine'):
            self.app.engine.debug_mode = is_debug
        log(self.app.log_queue, getattr(self.app, 'session_log_file', None), f"\n🐞 Debug Mode {state_str}\n")

    def toggle_web_gui(self):
        import threading
        from services.web_server import start_web_server
        is_enabled = self.app.ui.widgets.web_gui_var.get()
        if is_enabled:
            # First time enablement check
            if not self.app.web_server_started:
                log(self.app.log_queue, self.app.session_log_file, "🌐 Initiating Web Dashboard binding...")
                threading.Thread(target=start_web_server, args=(self.app.shared_state, "0.0.0.0", None, self.app.log_queue), daemon=True).start()
                self.app.web_server_started = True
                # Give the server thread ~300ms to bind and write web_port, then update the label
                self.app.root.after(300, self.app._update_web_port_label)
            else:
                port = self.app.shared_state.web_port or 7860
                log(self.app.log_queue, self.app.session_log_file, f"🌐 Web Dashboard updates resumed. (http://localhost:{port})")
        else:
            log(self.app.log_queue, self.app.session_log_file, "🌐 Web Dashboard updates paused.")

    def toggle_bypass_intervention(self):
        """Toggles bypass intervention mode. Enabling requires explicit user acknowledgement."""
        if self.app.ui.widgets.bypass_intervention_var.get():
            ans = messagebox.askyesno(
                "⚠️ Enable Bypass Intervention Mode",
                "By enabling 'Bypass Intervention', the engine will automatically use a "
                "cleaned-up version of a failed AI output instead of pausing for manual correction.\n\n"
                "⚠️ This WILL introduce translation errors into your output file.\n\n"
                "A dedicated bypass log will be created so you can review and fix affected "
                "segments after the session ends.\n\n"
                "Do you understand and wish to proceed?",
                parent=self.app.root
            )
            if not ans:
                self.app.ui.widgets.bypass_intervention_var.set(False)
                return
            log(self.app.log_queue, self.app.session_log_file, "🚫 [BYPASS] Bypass Intervention Mode ENABLED — errors will be auto-logged.")
            if hasattr(self.app, 'engine'):
                self.app.engine.bypass_intervention = True
        else:
            log(self.app.log_queue, self.app.session_log_file, "🚫 [BYPASS] Bypass Intervention Mode DISABLED.")
            if hasattr(self.app, 'engine'):
                self.app.engine.bypass_intervention = False

    def refresh_files(self):
        import re
        import json
        from core.llm_api import is_process_alive
        source_code = self.app.ui.widgets.source_lang_var.get()
        target_code = self.app.ui.widgets.target_lang_var.get()

        all_sysprm = sorted([f for f in os.listdir(self.app.sysprm_dir) if f.lower().endswith('.sysprm')])
        
        filtered_sysprm = []
        for f_name in all_sysprm:
            path = os.path.join(self.app.sysprm_dir, f_name)
            try:
                # Use utf-8-sig to handle possible BOM
                with open(path, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                    lang_cfg = data.get("language", {})
                    if lang_cfg.get("source") == source_code and lang_cfg.get("target") == target_code:
                        filtered_sysprm.append(f_name)
            except Exception:
                pass # Skip files that aren't valid JSON or don't match

        srt_files = sorted([f for f in os.listdir(self.app.english_subs_dir) if f.endswith('.srt')])
        self.app.ui.widgets.srt_combo['values'] = srt_files
        self.app.ui.widgets.sysprm_combo['values'] = filtered_sysprm
        
        # If current selection is no longer in the list, clear it
        if self.app.ui.widgets.sysprm_var.get() not in filtered_sysprm:
            self.app.ui.widgets.sysprm_var.set("")

        # Scan for Checkpoints
        self.app.available_checkpoints = []
        current_srt = self.app.ui.widgets.srt_var.get()
        try:
            for f in os.listdir(self.app.checkpoint_dir):
                if re.match(r'^translator_checkpoint_\d+\.json$', f):
                    path = os.path.join(self.app.checkpoint_dir, f)
                    mtime = os.path.getmtime(path)
                    with open(path, 'r', encoding='utf-8') as cp:
                        data = json.load(cp)
                        if data.get("processed", 0) > 0 and (data.get("pid") == os.getpid() or not is_process_alive(data.get("pid"))):
                            data["file_path"] = path
                            data["mtime"] = mtime
                            self.app.available_checkpoints.append(data)
            
            # Sort: Newest first
            self.app.available_checkpoints.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        except Exception: pass

        resume_options = ["[0] Start a NEW session (Ignore checkpoints)"]
        auto_select_idx = 0
        
        for i, ckpt in enumerate(self.app.available_checkpoints):
            total_str = f"/{ckpt['total_blocks']}" if ckpt['total_blocks'] else ""
            display_name = f"[{i+1}] Resume: {os.path.basename(ckpt['srt_file'])} ({ckpt['processed']}{total_str} blocks)"
            resume_options.append(display_name)
            
            # Auto-latch logic: If we have a match for the current SRT and we haven't selected anything yet (or were in new session)
            if auto_select_idx == 0 and os.path.basename(ckpt['srt_file']) == current_srt:
                auto_select_idx = i + 1

        self.app.ui.widgets.resume_combo['values'] = resume_options
        
        # Decide what to select
        current_val = self.app.ui.widgets.resume_var.get()
        if getattr(self.app, 'just_finished', False):
            self.app.just_finished = False
        elif not current_val or current_val.startswith("[0]"):
            if auto_select_idx > 0:
                self.app.ui.widgets.resume_combo.current(auto_select_idx)
                self.on_resume_selection()
            else:
                self.app.ui.widgets.resume_combo.current(0)
        
        log(self.app.log_queue, self.app.session_log_file, "✅ File lists refreshed.")

    def _toggle_ui_state(self, state):
        for w in [self.app.ui.widgets.model_combo, self.app.ui.widgets.batch_entry, self.app.ui.widgets.srt_combo, 
                  self.app.ui.widgets.sysprm_combo, self.app.ui.widgets.judge_model_combo, self.app.ui.widgets.judge_batch_entry,
                  self.app.ui.widgets.resume_combo, self.app.ui.widgets.btn_settings, self.app.ui.widgets.btn_manage_checkpoints,
                  self.app.ui.widgets.btn_restart, self.app.ui.widgets.btn_start]:
            w.config(state=state)
        self.app.ui.widgets.btn_stop.config(state=tk.NORMAL if state == tk.DISABLED else tk.DISABLED)
        self.app.ui.widgets.btn_open_translated.config(state=tk.NORMAL)

    def refresh_models_ui(self):
        model_list = [f"{k} - {v['name']} ({v['provider']})" for k, v in SETTINGS.config["models"].items()]
        self.app.ui.widgets.model_combo['values'] = model_list
        self.app.ui.widgets.judge_model_combo['values'] = model_list
        self.on_model_change()

    def _reset_ui_for_new_session(self):
        self.app.ui.widgets.progress_var.set(0)
        self.app.ui.widgets.lbl_progress.config(text="Progress: 0/0 (0%)")
        self.app.ui.widgets.lbl_eta.config(text="ETA: --:--")
        self.app.ui.widgets.lbl_cost.config(text="Cost: $0.00")
        self.app.ui.widgets.btn_open_translated.config(state=tk.DISABLED)
        self.app.ui.widgets.btn_start.config(text="Start Translation")
        self.app.ui.widgets.srt_combo.config(state="readonly")
        self.app.ui.widgets.sysprm_combo.unbind("<<ComboboxSelected>>")
        
        # Reset Web GUI
        if self.app.ui.widgets.web_gui_var.get():
            self.app.shared_state.update_progress(0, 0)
            self.app.shared_state.update_eta("--:--", "--:--")
            self.app.shared_state.update_cost(0.0, 0.0, display_text="Cost: $0.00")

    def _update_ui_from_checkpoint(self, ckpt):
        from utils.app_utils import format_cost_display, get_eta_string
        processed, total = ckpt.get("processed", 0), ckpt.get("total_blocks", 0)
        pct = (processed / total * 100) if total else 0
        self.app.ui.widgets.progress_var.set(pct)
        self.app.ui.widgets.lbl_progress.config(text=f"Progress: {processed}/{total} ({pct:.1f}%)")
        self.app.ui.widgets.lbl_cost.config(text=format_cost_display(ckpt.get("total_main_cost", 0.0), ckpt.get("total_judge_cost", 0.0)))

        # ── Persistent Performance & ETA ──
        stats = ckpt.get("stats", {})
        self.app.perf_history_new = list(stats.get("llm_call_times_new", []))
        self.app.perf_history_retry = list(stats.get("llm_call_times_retry", []))
        
        # Calculate and show immediate ETA from checkpoint stats
        elapsed = stats.get("total_elapsed_seconds", 0.0)
        time_str, finish_str, eta_secs = get_eta_string(elapsed, processed, total)
        
        self.app.total_eta_seconds = eta_secs
        self.app.last_finish_time_str = finish_str

        if processed > 0:
            self.app.ui.widgets.lbl_eta.config(text=f"ETA: {time_str} | End: {finish_str}")
        else:
            self.app.ui.widgets.lbl_eta.config(text="ETA: --:--")

        # Sync with Web Dashboard
        if self.app.ui.widgets.web_gui_var.get():
            self.app.shared_state.update_progress(processed, total)
            self.app.shared_state.update_eta(time_str if processed > 0 else "--:--", finish_str if processed > 0 else "--:--")
            self.app.shared_state.update_cost(ckpt.get("total_main_cost", 0.0), ckpt.get("total_judge_cost", 0.0), 
                                          display_text=self.app.ui.widgets.lbl_cost.cget("text"))
        # ──────────────────────────────────
        
        # ── Language & Profile Restoration ──
        if "source_lang_code" in ckpt:
            self.app.ui.widgets.source_lang_var.set(ckpt["source_lang_code"])
        if "target_lang_code" in ckpt:
            self.app.ui.widgets.target_lang_var.set(ckpt["target_lang_code"])
        
        # Trigger directory/profile sync (calls refresh_files)
        self.on_language_change()
        
        self.app.ui.widgets.srt_var.set(ckpt.get("srt_file", ""))
        self.app.ui.widgets.sysprm_var.set(ckpt.get("sys_file", ""))
        self.app.ui.widgets.batch_size_var.set(str(ckpt.get("batch_size", "30")))
        self.app.ui.widgets.judge_batch_var.set(str(ckpt.get("judge_batch_size", "20")))
        
        # Select matching model strings in Comboboxes
        for var, key in [(self.app.ui.widgets.model_var, "model_choice"), (self.app.ui.widgets.judge_model_var, "judge_model_choice")]:
            target_idx = str(ckpt.get(key, "1"))
            for val in self.app.ui.widgets.model_combo['values']:
                if val.startswith(f"{target_idx} - "):
                    var.set(val)
                    break

        self.app.ui.widgets.btn_start.config(text="Resume Translation")
        self.app.ui.widgets.srt_combo.config(state="disabled")
        self.app.ui.widgets.btn_open_translated.config(state=tk.NORMAL if ckpt.get("output_file") else tk.DISABLED)

    def _update_web_port_label(self):
        """Called ~300ms after the web server thread starts to display the actual bound port."""
        port = self.app.shared_state.web_port
        if port:
            log(self.app.log_queue, self.app.session_log_file, f"🌐 Web Dashboard ready → http://localhost:{port}")
            self.app.ui.widgets.lbl_web_clients.config(text=f"(:{port})")
        else:
            # Server hasn't bound yet — retry once more after another 500ms
            self.app.root.after(500, self._update_web_port_label)

    def start_translation(self):
        import re
        import datetime
        import json
        import threading
        from core.llm_api import ping_model

        if self.app.is_running: return
        
        resume_val = self.app.ui.widgets.resume_var.get()
        choice_idx = int(re.search(r'\[(\d+)\]', resume_val).group(1)) if resume_val else 0
        resume_mode = choice_idx > 0
        
        # Config gathering
        model_idx = self.app.ui.widgets.model_var.get().split(" - ")[0]
        judge_idx = self.app.ui.widgets.judge_model_var.get().split(" - ")[0]
        model_cfg = SETTINGS.config["models"].get(model_idx).copy()
        judge_cfg = (SETTINGS.config["models"].get(judge_idx) or model_cfg).copy()
        
        # Inject API keys into configs for the ping test
        api_key = SETTINGS.config["api_keys"].get(model_cfg['provider'])
        judge_api_key = SETTINGS.config["api_keys"].get(judge_cfg['provider'])
        model_cfg['api_key'] = api_key
        judge_cfg['api_key'] = judge_api_key

        # 1. Basic Key Presence Validation
        if not api_key:
            messagebox.showerror("Key Missing", f"API Key for '{model_cfg['provider'].upper()}' is missing.\n\nPlease click the ⚙️ Settings button to enter your key.")
            return
        if not judge_api_key:
            messagebox.showerror("Key Missing", f"API Key for Judge Provider '{judge_cfg['provider'].upper()}' is missing.\n\nPlease click the ⚙️ Settings button to enter your key.")
            return

        # --- Pre-Flight Connectivity Checks ---
        log(self.app.log_queue, getattr(self.app, 'session_log_file', None), f"🔌 Testing connectivity for {model_cfg.get('name', 'Main Model')}...")
        ok, msg = ping_model(model_cfg)
        if not ok:
            messagebox.showerror("Connectivity Error (Main Model)", msg, parent=self.app.root)
            log(self.app.log_queue, getattr(self.app, 'session_log_file', None), f"❌ Pre-flight check FAILED: {msg}")
            return
            
        # 2. Judge Model Ping (if different)
        if judge_idx != model_idx:
            log(self.app.log_queue, getattr(self.app, 'session_log_file', None), f"🔌 Testing connectivity for Judge ({judge_cfg.get('name', 'Judge')})...")
            ok, msg = ping_model(judge_cfg)
            if not ok:
                messagebox.showerror("Connectivity Error (Judge Model)", msg, parent=self.app.root)
                log(self.app.log_queue, getattr(self.app, 'session_log_file', None), f"❌ Pre-flight check (Judge) FAILED: {msg}")
                return
        
        log(self.app.log_queue, getattr(self.app, 'session_log_file', None), "✅ All models reached successfully. Initializing engine...")
        # --------------------------------------

        # 2. File Selection Validation

        srt_name = self.app.ui.widgets.srt_var.get()
        sys_name = self.app.ui.widgets.sysprm_var.get()
        if not resume_mode and (not srt_name or not sys_name):
            messagebox.showerror("Error", "Please select both an SRT file and a System Prompt for a new session.")
            return

        # --- Sysprm Language Sanity Check ---
        sys_path = os.path.join(self.app.sysprm_dir, sys_name)
        if os.path.exists(sys_path):
            try:
                with open(sys_path, 'r', encoding='utf-8-sig') as f:
                    sys_content = f.read()
                
                from utils.app_utils import detect_sysprm_language
                detected_lang_type = detect_sysprm_language(sys_content) # "English" or "Native"
                
                profile = SETTINGS.get_active_profile()
                try:
                    sysprm_json = json.loads(sys_content.lstrip('\ufeff'))
                    use_native = bool(sysprm_json.get("language", {}).get("use_native_instructions", False))
                except Exception:
                    use_native = (detected_lang_type == "Native")
                
                sys_name_lower = sys_name.lower()
                source_lang_name = profile.source_lang.lower()
                target_lang_name = profile.target_lang.lower()
                
                lang_variants = {
                    "hebrew": ["hebrew", "heb", "he", "עברית"],
                    "french": ["french", "fra", "fre", "fr", "צרפתית"],
                    "spanish": ["spanish", "esp", "es", "ספרדית"],
                    "english": ["english", "eng", "en", "אנגלית"],
                    "chinese": ["chinese", "zh", "chi", "סינית"],
                    "portuguese": ["portuguese", "port", "pt", "פורטוגזית"],
                    "russian": ["russian", "ru", "rus", "רוסית"],
                    "italian": ["italian", "it", "ita", "איטלקית"],
                    "polish": ["polish", "pl", "pol", "פולנית"],
                    "ukrainian": ["ukrainian", "uk", "ukr", "אוקראינית"]
                }
                
                # Check for "<source>_2_<target>" pattern
                mismatch = False
                mismatch_reason = ""
                
                # 2. Filename Source/Target check
                if not mismatch and "_2_" in sys_name_lower:
                    try:
                        parts = sys_name_lower.split('_')
                        if "2" in parts:
                            idx = parts.index("2")
                            file_source = parts[idx-1]
                            file_target = parts[idx+1]
                            
                            source_expected = lang_variants.get(source_lang_name, [source_lang_name])
                            target_expected = lang_variants.get(target_lang_name, [target_lang_name])
                            
                            if not any(k in file_source or file_source in k for k in source_expected):
                                mismatch_reason = f"Source language mismatch: Selected {profile.source_lang} but SysPrm says '{file_source}'."
                                mismatch = True
                            elif not any(k in file_target or file_target in k for k in target_expected):
                                mismatch_reason = f"Target language mismatch: Selected {profile.target_lang} but SysPrm says '{file_target}'."
                                mismatch = True
                    except Exception: pass
                
                # 3. Fallback Keyword check
                if not mismatch:
                    target_expected = lang_variants.get(target_lang_name, [target_lang_name])
                    has_target_keyword = any(k in sys_name_lower for k in target_expected)
                    
                    if not has_target_keyword and ("_ni" in sys_name_lower or detected_lang_type == "Native"):
                        mismatch_reason = f"The selected SysPrm '{sys_name}' does not appear to be for {profile.target_lang}."
                        mismatch = True
                    
                if mismatch:
                    mismatch_msg = f"⚠️ Language Mismatch Warning:\n\n{mismatch_reason}\n\nThis will likely cause the AI to output the wrong language or hallucinate. Would you like to proceed anyway?"
                    ans = messagebox.askyesno("Language Mismatch Warning", mismatch_msg, parent=self.app.root)
                    if not ans:
                        log(self.app.log_queue, self.app.session_log_file, "🛑 Session aborted by user due to language mismatch.")
                        return
                
                log(self.app.log_queue, self.app.session_log_file, f"🔍 SysPrm Analysis: Detected {detected_lang_type} formatting.")
            except Exception as e:
                log(self.app.log_queue, self.app.session_log_file, f"⚠️ SysPrm sanity check failed: {e}")

        config = {
            "resume_mode": resume_mode,
            "debug_mode": self.app.ui.widgets.debug_var.get(),
            "model_cfg": model_cfg,
            "model_choice": model_idx,
            "api_key": api_key,
            "batch_size": int(self.app.ui.widgets.batch_size_var.get() or 30),
            "session_log_file": self.app.session_log_file,
            "srt_name": self.app.ui.widgets.srt_var.get(),
            "sys_name": self.app.ui.widgets.sysprm_var.get(),
            "judge_cfg": judge_cfg,
            "judge_api_key": SETTINGS.config["api_keys"].get(judge_cfg['provider']),
            "judge_model_choice": judge_idx,
            "judge_batch_size": self.app.ui.widgets.judge_batch_var.get(),
            "checkpoint_dir": self.app.checkpoint_dir,
            "sysprm_dir": self.app.sysprm_dir,
            "english_subs_dir": self.app.english_subs_dir,
            "output_dir": self.app.output_dir,
            "scratch_dir": os.path.join(self.app.curr_dir, "scratch"),
            "bypass_intervention": self.app.ui.widgets.bypass_intervention_var.get(),
            "logs_dir": self.app.logs_dir,
            "language_profile": SETTINGS.get_active_profile()
        }

        if resume_mode:
            ckpt = self.app.available_checkpoints[choice_idx - 1]
            config.update({"checkpoint_data": ckpt, "checkpoint_file_path": ckpt["file_path"]})

        # Launch Engine
        self.app.is_running = True
        self.app.engine.should_stop = False
        self.app.engine.bypass_intervention = self.app.ui.widgets.bypass_intervention_var.get()
        self._toggle_ui_state(tk.DISABLED)
        
        # In Hot Resume mode, don't wipe the terminal. Add a separator instead.
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if resume_mode:
            log(self.app.log_queue, self.app.session_log_file, f"\n{'='*30}\n🔄 [{timestamp}] SESSION RESUMED\n{'='*30}\n")
        else:
            self.app.ui.widgets.log_text.delete(1.0, tk.END)
            log(self.app.log_queue, self.app.session_log_file, f"🚀 [{timestamp}] NEW SESSION STARTED")
        
        self.app.shared_state.set_running(True)
        threading.Thread(target=self.app.engine.run_translation, args=(config,), daemon=True).start()

    def stop_translation(self):
        if self.app.is_running:
            self.app.engine.request_stop()
            log(self.app.log_queue, self.app.session_log_file, "🛑 Stop signal received. Finishing current batch...")
            self.app.ui.widgets.btn_stop.config(state=tk.DISABLED)

    def process_queues(self):
        self.queue_dispatcher.process_queues()
        self.app.root.after(100, self.process_queues)
