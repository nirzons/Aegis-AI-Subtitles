import os
import sys
import datetime
import re
import json
import subprocess
import threading
import queue
from collections import deque
import tkinter as tk
from tkinter import messagebox, ttk

# Internal Modules
from utils.settings import SETTINGS
from core.llm_api import is_process_alive
from ui.gui_windows import LiveViewer, SettingsWindow, CheckpointsWindow
from utils.app_utils import log, format_cost_display, get_eta_string
from ui.ui_layout import MainUILayout
from core.translation_engine import TranslationEngine
from ui.ui_controller import UIController


# Web GUI Modules
from utils.shared_state import SharedState
from services.web_server import start_web_server


class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🛡️ Aegis AI Subtitles")
        self.root.geometry("698x750")

        self._apply_styles()

        self.smoke_test_settings_opened = False
        self.smoke_test_checkpoints_opened = False
        self.smoke_test_lang_changed = False
        self.smoke_test_debug_toggled = False
        self.smoke_test_sim_completed = False

        smoke_test_phase = None
        for i, arg in enumerate(sys.argv):
            if arg == "--smoke_test":
                if i + 1 < len(sys.argv) and sys.argv[i+1] in ["1", "2", "3"]:
                    smoke_test_phase = int(sys.argv[i+1])

        if smoke_test_phase is not None:
            # Create interactive test banner frame at the top (packed first!)
            test_frame = tk.Frame(self.root, bg="#f39c12", height=40)
            test_frame.pack(fill=tk.X, side=tk.TOP, pady=5)
            
            lbl_banner = tk.Label(test_frame, text=f"[TESTING MODE: PHASE {smoke_test_phase}]", fg="white", bg="#f39c12", font=("Segoe UI", 11, "bold"))
            lbl_banner.pack(side=tk.LEFT, padx=10, pady=5)
            
            def on_continue():
                from tkinter import messagebox
                if smoke_test_phase == 1:
                    if not self.smoke_test_settings_opened or not self.smoke_test_checkpoints_opened:
                        messagebox.showwarning("Incomplete", "Please open both Settings and Manage Checkpoints before continuing.")
                        return
                elif smoke_test_phase == 2:
                    if not self.smoke_test_lang_changed or not self.smoke_test_debug_toggled:
                        messagebox.showwarning("Incomplete", "Please test language changes and debug toggles before continuing.")
                        return
                elif smoke_test_phase == 3:
                    if not self.smoke_test_sim_completed:
                        messagebox.showwarning("Incomplete", "Please run the simulation to completion before continuing.")
                        return

                print(f"smoke test {smoke_test_phase} passed", flush=True)
                self.root.destroy()
                sys.exit(0)
                
            btn_continue = tk.Button(test_frame, text="TEST OK - CONTINUE", command=on_continue, bg="#27ae60", fg="white", font=("Segoe UI", 10, "bold"), relief="flat", padx=10)
            btn_continue.pack(side=tk.RIGHT, padx=10, pady=5)

        # Core State
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.is_running = False
        self.resp_timer_seconds = -1
        self.perf_history_new = []
        self.perf_history_retry = []
        self.last_batch_size = 0
        self.previous_batch_size = -1
        self.num_batches_processed = 0
        self.est_remaining = -1
        self.total_eta_seconds = -1
        self.last_finish_time_str = "--:--"
        self.perf_history_judge = []
        self.current_judge_chunk_size = 0
        self.current_is_retry = False
        self.speed_history = deque(maxlen=10) # Last 10 batches for sparkline
        self.active_phase = None # "main" or "judge"
        self._timer_after_id = None
        self.mlr_activated = False # Track if we've logged the MLR switch
        
        # Directories
        self.curr_dir = os.getcwd()
        self.english_subs_dir = os.path.join(self.curr_dir, "English subtitles")
        self.sysprm_dir = os.path.join(self.curr_dir, "sysprm files")
        # Output dir will be set dynamically in refresh_languages_ui / on_language_change
        self.output_dir = os.path.join(self.curr_dir, "Translated subtitles")
        self.checkpoint_dir = os.path.join(self.curr_dir, ".checkpoints")
        self.logs_dir = os.path.join(self.curr_dir, "logs")


        for d in [self.english_subs_dir, self.sysprm_dir, self.output_dir, self.logs_dir, self.checkpoint_dir]:
            os.makedirs(d, exist_ok=True)
            
        if "--smoke_test" in sys.argv:
            self.session_log_file = None
        else:
            self.session_log_file = os.path.join(self.logs_dir, f"session_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        self.available_checkpoints = []

        # Web GUI State (Moved UP so the engine can access it)
        self.shared_state = SharedState()
        self.web_server_started = False

        # UI & Engine Initialization
        self.ui_controller = UIController(self)
        self.open_settings = self.ui_controller.open_settings
        self.open_checkpoints_manager = self.ui_controller.open_checkpoints_manager
        self.open_orig_srt = self.ui_controller.open_orig_srt
        self.open_translated_srt = self.ui_controller.open_translated_srt
        self.open_prompt_generator = self.ui_controller.open_prompt_generator
        self.restart_app = self.ui_controller.restart_app

        self.refresh_languages_ui = self.ui_controller.refresh_languages_ui
        self.on_language_change = self.ui_controller.on_language_change
        self.on_model_change = self.ui_controller.on_model_change
        self.on_resume_selection = self.ui_controller.on_resume_selection
        self.toggle_debug_mode = self.ui_controller.toggle_debug_mode
        self.toggle_web_gui = self.ui_controller.toggle_web_gui
        self.toggle_bypass_intervention = self.ui_controller.toggle_bypass_intervention
        self.refresh_files = self.ui_controller.refresh_files
        self._toggle_ui_state = self.ui_controller._toggle_ui_state
        self.refresh_models_ui = self.ui_controller.refresh_models_ui


        self.ui = MainUILayout(self.root)
        self.ui.setup(self)


        # Multi-Language Bindings
        self.ui.widgets.source_combo.bind("<<ComboboxSelected>>", self.on_language_change)
        self.ui.widgets.target_combo.bind("<<ComboboxSelected>>", self.on_language_change)

        
        # Pass the shared_state object into the engine
        self.engine = TranslationEngine(self.log_queue, self.ui_queue, shared_state=self.shared_state)
        # Initial Actions
        self.refresh_files()
        self.refresh_models_ui()
        self.refresh_languages_ui()
        self.root.after(100, self.process_queues)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Simulation for Smoke Test 3
        if smoke_test_phase == 3:
            def fake_start_translation():
                log(self.log_queue, getattr(self, 'session_log_file', None), "🚀 [SMOKE TEST 3] Simulation started")
                self.ui_queue.put(("progress", (20, 100)))
                self.ui_queue.put(("eta", ("00:15", "10:30", 15)))
                self.ui_queue.put(("cost", (0.01, 0.005, 0)))
                self.is_running = True
                self._toggle_ui_state(tk.DISABLED)
                def stop_sim():
                    log(self.log_queue, getattr(self, 'session_log_file', None), "✅ [SMOKE TEST 3] Simulation completed")
                    self.smoke_test_sim_completed = True
                    self.is_running = False
                    self._toggle_ui_state(tk.NORMAL)
                self.root.after(2000, stop_sim)
                
            self.ui.widgets.btn_start.config(command=fake_start_translation)


    # --- UI Event Handlers ---

    def _reset_ui_for_new_session(self):
        self.ui.widgets.progress_var.set(0)
        self.ui.widgets.lbl_progress.config(text="Progress: 0/0 (0%)")
        self.ui.widgets.lbl_eta.config(text="ETA: --:--")
        self.ui.widgets.lbl_cost.config(text="Cost: $0.00")
        self.ui.widgets.btn_open_translated.config(state=tk.DISABLED)
        self.ui.widgets.btn_start.config(text="Start Translation")
        self.ui.widgets.srt_combo.config(state="readonly")
        self.ui.widgets.sysprm_combo.unbind("<<ComboboxSelected>>")
        
        # Reset Web GUI
        if self.ui.widgets.web_gui_var.get():
            self.shared_state.update_progress(0, 0)
            self.shared_state.update_eta("--:--", "--:--")
            self.shared_state.update_cost(0.0, 0.0, display_text="Cost: $0.00")

    def _update_ui_from_checkpoint(self, ckpt):
        processed, total = ckpt.get("processed", 0), ckpt.get("total_blocks", 0)
        pct = (processed / total * 100) if total else 0
        self.ui.widgets.progress_var.set(pct)
        self.ui.widgets.lbl_progress.config(text=f"Progress: {processed}/{total} ({pct:.1f}%)")
        self.ui.widgets.lbl_cost.config(text=format_cost_display(ckpt.get("total_main_cost", 0.0), ckpt.get("total_judge_cost", 0.0)))

        # ── Persistent Performance & ETA ──
        stats = ckpt.get("stats", {})
        self.perf_history_new = list(stats.get("llm_call_times_new", []))
        self.perf_history_retry = list(stats.get("llm_call_times_retry", []))
        
        # Calculate and show immediate ETA from checkpoint stats
        elapsed = stats.get("total_elapsed_seconds", 0.0)
        time_str, finish_str, eta_secs = get_eta_string(elapsed, processed, total)
        
        self.total_eta_seconds = eta_secs
        self.last_finish_time_str = finish_str

        if processed > 0:
            self.ui.widgets.lbl_eta.config(text=f"ETA: {time_str} | End: {finish_str}")
        else:
            self.ui.widgets.lbl_eta.config(text="ETA: --:--")

        # Sync with Web Dashboard
        if self.ui.widgets.web_gui_var.get():
            self.shared_state.update_progress(processed, total)
            self.shared_state.update_eta(time_str if processed > 0 else "--:--", finish_str if processed > 0 else "--:--")
            self.shared_state.update_cost(ckpt.get("total_main_cost", 0.0), ckpt.get("total_judge_cost", 0.0), 
                                         display_text=self.ui.widgets.lbl_cost.cget("text"))
        # ──────────────────────────────────
        
        # ── Language & Profile Restoration ──
        if "source_lang_code" in ckpt:
            self.ui.widgets.source_lang_var.set(ckpt["source_lang_code"])
        if "target_lang_code" in ckpt:
            self.ui.widgets.target_lang_var.set(ckpt["target_lang_code"])
        
        # Trigger directory/profile sync (calls refresh_files)
        self.on_language_change()
        
        self.ui.widgets.srt_var.set(ckpt.get("srt_file", ""))
        self.ui.widgets.sysprm_var.set(ckpt.get("sys_file", ""))
        self.ui.widgets.batch_size_var.set(str(ckpt.get("batch_size", "30")))
        self.ui.widgets.judge_batch_var.set(str(ckpt.get("judge_batch_size", "20")))
        
        # Select matching model strings in Comboboxes
        for var, key in [(self.ui.widgets.model_var, "model_choice"), (self.ui.widgets.judge_model_var, "judge_model_choice")]:
            target_idx = str(ckpt.get(key, "1"))
            for val in self.ui.widgets.model_combo['values']:
                if val.startswith(f"{target_idx} - "):
                    var.set(val)
                    break

        self.ui.widgets.btn_start.config(text="Resume Translation")
        self.ui.widgets.srt_combo.config(state="disabled")
        self.ui.widgets.btn_open_translated.config(state=tk.NORMAL if ckpt.get("output_file") else tk.DISABLED)

    # --- Actions ---

    def _update_web_port_label(self):
        """Called ~300ms after the web server thread starts to display the actual bound port."""
        port = self.shared_state.web_port
        if port:
            log(self.log_queue, self.session_log_file, f"🌐 Web Dashboard ready → http://localhost:{port}")
            self.ui.widgets.lbl_web_clients.config(text=f"(:{port})")
        else:
            # Server hasn't bound yet — retry once more after another 500ms
            self.root.after(500, self._update_web_port_label)

    def start_translation(self):
        if self.is_running: return
        
        resume_val = self.ui.widgets.resume_var.get()
        choice_idx = int(re.search(r'\[(\d+)\]', resume_val).group(1)) if resume_val else 0
        resume_mode = choice_idx > 0
        
        # Config gathering
        model_idx = self.ui.widgets.model_var.get().split(" - ")[0]
        judge_idx = self.ui.widgets.judge_model_var.get().split(" - ")[0]
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
        from core.llm_api import ping_model
        log(self.log_queue, getattr(self, 'session_log_file', None), f"🔌 Testing connectivity for {model_cfg.get('name', 'Main Model')}...")
        ok, msg = ping_model(model_cfg)
        if not ok:
            messagebox.showerror("Connectivity Error (Main Model)", msg, parent=self.root)
            log(self.log_queue, getattr(self, 'session_log_file', None), f"❌ Pre-flight check FAILED: {msg}")
            return
            
        # 2. Judge Model Ping (if different)
        if judge_idx != model_idx:
            log(self.log_queue, getattr(self, 'session_log_file', None), f"🔌 Testing connectivity for Judge ({judge_cfg.get('name', 'Judge')})...")
            ok, msg = ping_model(judge_cfg)
            if not ok:
                messagebox.showerror("Connectivity Error (Judge Model)", msg, parent=self.root)
                log(self.log_queue, getattr(self, 'session_log_file', None), f"❌ Pre-flight check (Judge) FAILED: {msg}")
                return
        
        log(self.log_queue, getattr(self, 'session_log_file', None), "✅ All models reached successfully. Initializing engine...")
        # --------------------------------------

        # 2. File Selection Validation

        srt_name = self.ui.widgets.srt_var.get()
        sys_name = self.ui.widgets.sysprm_var.get()
        if not resume_mode and (not srt_name or not sys_name):
            messagebox.showerror("Error", "Please select both an SRT file and a System Prompt for a new session.")
            return

        # --- Sysprm Language Sanity Check ---
        sys_path = os.path.join(self.sysprm_dir, sys_name)
        if os.path.exists(sys_path):
            try:
                with open(sys_path, 'r', encoding='utf-8-sig') as f:
                    sys_content = f.read()
                
                from utils.app_utils import detect_sysprm_language
                detected_lang_type = detect_sysprm_language(sys_content) # "English" or "Native"
                
                profile = SETTINGS.get_active_profile()
                # use_native is now read from the sysprm file itself, not the UI.
                # The engine will set profile.use_native_instructions from the sysprm JSON.
                # Here we just detect the content type for cross-checks.
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
                
                # 2. Filename Source/Target check (Modern format: ..._source_2_target...)
                if not mismatch and "_2_" in sys_name_lower:
                    try:
                        # Extract source and target from filename
                        # Expected format: show_season_source_2_target[_ni].sysprm
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
                    except Exception: pass # Fallback to keyword check if parsing fails
                
                # 3. Fallback Keyword check (Legacy or if parsing failed)
                if not mismatch:
                    target_expected = lang_variants.get(target_lang_name, [target_lang_name])
                    has_target_keyword = any(k in sys_name_lower for k in target_expected)
                    
                    if not has_target_keyword and ("_ni" in sys_name_lower or detected_lang_type == "Native"):
                        mismatch_reason = f"The selected SysPrm '{sys_name}' does not appear to be for {profile.target_lang}."
                        mismatch = True
                    
                if mismatch:
                    mismatch_msg = f"⚠️ Language Mismatch Warning:\n\n{mismatch_reason}\n\nThis will likely cause the AI to output the wrong language or hallucinate. Would you like to proceed anyway?"
                    ans = messagebox.askyesno("Language Mismatch Warning", mismatch_msg, parent=self.root)
                    if not ans:
                        log(self.log_queue, self.session_log_file, "🛑 Session aborted by user due to language mismatch.")
                        return
                
                log(self.log_queue, self.session_log_file, f"🔍 SysPrm Analysis: Detected {detected_lang_type} formatting.")
            except Exception as e:
                log(self.log_queue, self.session_log_file, f"⚠️ SysPrm sanity check failed: {e}")
        # ------------------------------------


        config = {
            "resume_mode": resume_mode,
            "debug_mode": self.ui.widgets.debug_var.get(),
            "model_cfg": model_cfg,
            "model_choice": model_idx,
            "api_key": api_key,
            "batch_size": int(self.ui.widgets.batch_size_var.get() or 30),
            "session_log_file": self.session_log_file,
            "srt_name": self.ui.widgets.srt_var.get(),
            "sys_name": self.ui.widgets.sysprm_var.get(),
            "judge_cfg": judge_cfg,
            "judge_api_key": SETTINGS.config["api_keys"].get(judge_cfg['provider']),
            "judge_model_choice": judge_idx,
            "judge_batch_size": self.ui.widgets.judge_batch_var.get(),
            "checkpoint_dir": self.checkpoint_dir,
            "sysprm_dir": self.sysprm_dir,
            "english_subs_dir": self.english_subs_dir,
            "output_dir": self.output_dir,
            "scratch_dir": os.path.join(self.curr_dir, "scratch"),
            "bypass_intervention": self.ui.widgets.bypass_intervention_var.get(),
            "logs_dir": self.logs_dir,
            "language_profile": SETTINGS.get_active_profile()
        }


        if resume_mode:
            ckpt = self.available_checkpoints[choice_idx - 1]
            config.update({"checkpoint_data": ckpt, "checkpoint_file_path": ckpt["file_path"]})

        # Launch Engine
        self.is_running = True
        self.engine.should_stop = False
        self.engine.bypass_intervention = self.ui.widgets.bypass_intervention_var.get()
        self._toggle_ui_state(tk.DISABLED)
        
        # In Hot Resume mode, don't wipe the terminal. Add a separator instead.
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if resume_mode:
            log(self.log_queue, self.session_log_file, f"\n{'='*30}\n🔄 [{timestamp}] SESSION RESUMED\n{'='*30}\n")
        else:
            self.ui.widgets.log_text.delete(1.0, tk.END)
            log(self.log_queue, self.session_log_file, f"🚀 [{timestamp}] NEW SESSION STARTED")
        
        # Self-healing: same-stride retry once before shrinking; then −max(3, current//6); effective stride = penultimate attempt after retries. ♪ strip etc. in TranslationEngine.
        self.shared_state.set_running(True)
        threading.Thread(target=self.engine.run_translation, args=(config,), daemon=True).start()

    def stop_translation(self):
        if self.is_running:
            self.engine.request_stop()
            log(self.log_queue, self.session_log_file, "🛑 Stop signal received. Finishing current batch...")
            self.ui.widgets.btn_stop.config(state=tk.DISABLED)

    def process_queues(self):
        while not self.log_queue.empty():
            text = self.log_queue.get()
            self._log_with_tags(text)
            if self.ui.widgets.web_gui_var.get():
                self.shared_state.append_log(text)
            
        while not self.ui_queue.empty():
            type, data = self.ui_queue.get()
            if type == "progress":
                p, t = data
                self.ui.widgets.progress_var.set((p/t*100) if t else 0)
                self.ui.widgets.lbl_progress.config(text=f"Progress: {p}/{t} ({(p/t*100) if t else 0:.1f}%)")
            elif type == "eta":
                time_str, finish_str, eta_secs = data
                self.total_eta_seconds = eta_secs
                self.last_finish_time_str = finish_str
                self.ui.widgets.lbl_eta.config(text=f"ETA: {time_str} | End: {finish_str}")
            elif type == "timer_start":
                # data is expected to be a dict: {"size": n, "load": chars, "is_retry": bool}
                # Handle legacy tuples just in case
                if isinstance(data, dict):
                    self.last_batch_size = data.get("size", 1)
                    self.last_batch_load = data.get("load", 1)
                    self.current_is_retry = data.get("is_retry", False)
                else:
                    self.last_batch_size = data[0] if isinstance(data, tuple) else data
                    self.last_batch_load = self.last_batch_size * 50
                    self.current_is_retry = False

                # Safety: Cancel any existing timer loop before starting a new one
                if hasattr(self, '_timer_after_id') and self._timer_after_id:
                    self.root.after_cancel(self._timer_after_id)
                    self._timer_after_id = None

                self.resp_timer_seconds = 0
                self.active_phase = "main"

                # Batch Size Change detection
                arrow = ""
                if self.num_batches_processed > 0 and self.previous_batch_size > 0:
                    if self.last_batch_size > self.previous_batch_size: arrow = " 🔼"
                    elif self.last_batch_size < self.previous_batch_size: arrow = " 🔽"
                
                self.ui.widgets.lbl_status.config(text=f"📦 Size: {self.last_batch_size}{arrow}")

                # Update Web Dashboard
                if self.ui.widgets.web_gui_var.get():
                    if self.current_is_retry:
                        self.shared_state.update_status("Translating (Retry)", "#f59e0b") # Amber
                    else:
                        self.shared_state.update_status("Translating", "#0ea5e9") # Sky Blue

                # Choose history based on retry status
                history = self.perf_history_new
                if self.current_is_retry:
                    if len(self.perf_history_retry) >= 2 or (len(self.perf_history_retry) == 1 and len(self.perf_history_new) == 0):
                        history = self.perf_history_retry
                    else:
                        history = self.perf_history_new

                # Calculate estimation
                self.est_remaining = self._calculate_estimation(history, self.last_batch_size, self.last_batch_load, min_val=5)
                
                est_str = f" / 📦 Est: {self._fmt_seconds(self.est_remaining)}" if self.est_remaining > 0 else ""
                tag = "🔄 RETRY " if self.current_is_retry else ""
                self.ui.widgets.lbl_timer.config(text=f"⏱️ {tag}{self._fmt_seconds(self.resp_timer_seconds)}{est_str}")
                self._tick_timer()
            elif type == "timer_stop":
                load = data if isinstance(data, (int, float)) else getattr(self, 'last_batch_load', self.last_batch_size * 50)
                if self.resp_timer_seconds > 0:
                    if getattr(self, 'current_is_retry', False):
                        self.perf_history_retry.append((self.resp_timer_seconds, load))
                    else:
                        self.perf_history_new.append((self.resp_timer_seconds, load))
                    
                    self.num_batches_processed += 1

                self.resp_timer_seconds = -1
                self.active_phase = None
                self.ui.widgets.lbl_timer.config(text="")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_timer("")
            elif type == "judge_timer_start":
                # Clear previous timer state
                if hasattr(self, '_timer_after_id') and self._timer_after_id:
                    self.root.after_cancel(self._timer_after_id)
                    self._timer_after_id = None

                if isinstance(data, dict):
                    self.current_judge_chunk_size = data.get("size", 1)
                    self.current_judge_chunk_load = data.get("load", 1)
                else:
                    self.current_judge_chunk_size = data
                    self.current_judge_chunk_load = data * 100 # Judge load is usually higher

                self.resp_timer_seconds = 0
                self.active_phase = "judge"

                # Calculate estimation for judge chunk
                self.est_remaining = self._calculate_estimation(self.perf_history_judge, self.current_judge_chunk_size, self.current_judge_chunk_load, min_val=2)

                est_str = f" / ⚖️ Est: {self._fmt_seconds(self.est_remaining)}" if self.est_remaining > 0 else ""
                self.ui.widgets.lbl_timer.config(text=f"⚖️ {self._fmt_seconds(self.resp_timer_seconds)}{est_str}")
                self._tick_timer()
            elif type == "judge_timer_stop":
                load = data if isinstance(data, (int, float)) else getattr(self, 'current_judge_chunk_load', self.current_judge_chunk_size * 100)
                if self.resp_timer_seconds > 0:
                    self.perf_history_judge.append((self.resp_timer_seconds, load))
                
                self.resp_timer_seconds = -1
                self.active_phase = None
                # Note: We don't clear the label here yet to keep it visible for a split second until judge_progress or judge_stop
            elif type == "judge_start":
                self.ui.widgets.lbl_status.config(text="⚖️ JUDGING...", fg="#9b59b6")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_status("⚖️ JUDGING...", "#9b59b6")
            elif type == "judge_progress":
                c, t = data
                self.ui.widgets.lbl_status.config(text=f"⚖️ JUDGING {c}/{t}...", fg="#9b59b6")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_status(f"⚖️ JUDGING {c}/{t}...", "#9b59b6")
            elif type == "judge_stop":
                self.ui.widgets.lbl_status.config(text="")
                self.ui.widgets.lbl_timer.config(text="")
                self.resp_timer_seconds = -1
                self.active_phase = None
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_status("Idle", "#7f8c8d")
                    self.shared_state.update_timer("")
            elif type == "batch_success": 
                self.ui.widgets.lbl_status.config(text="")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_status("Saving Batch...", "#10b981") # Emerald
            elif type == "cost":
                # Robust unpacking: handle 2-item (legacy) or 3-item (MLR) signals
                if len(data) == 3:
                    main_cost, judge_cost, tokens_per_sec = data
                else:
                    main_cost, judge_cost = data
                    tokens_per_sec = 0

                self.ui.widgets.lbl_cost.config(text=format_cost_display(main_cost, judge_cost))
            elif type == "pipeline_telemetry":
                # data is pipeline_velocity (ch/s for the entire successful batch)
                if data > 0:
                    self.speed_history.append(data)
                    speed_fmt = f"{data:.2f}" if data < 10 else f"{data:.1f}"
                    self.ui.widgets.lbl_speed.config(text=f"{speed_fmt} ch/s")
            elif type == "segment":
                if self.ui.widgets.web_gui_var.get():
                    idx, time_val, eng, heb = data
                    self.shared_state.add_segment(idx, time_val, eng, heb)
            elif type == "upcoming":
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.set_upcoming(data)
            elif type == "finished":
                self.is_running = False
                self.resp_timer_seconds = -1
                self.just_finished = True
                self._toggle_ui_state(tk.NORMAL)
                self.ui.widgets.resume_combo.current(0)
                self.ui.widgets.lbl_eta.config(text="Completed")
                if data:
                    p, t = data
                    self.ui.widgets.progress_var.set((p/t*100) if t else 0)
                    self.ui.widgets.lbl_progress.config(text=f"Progress: {p}/{t} ({(p/t*100) if t else 0:.1f}%)")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.set_running(False)
                    self.shared_state.update_timer("")
                    self.shared_state.update_eta("Completed", "")

            elif type == "refresh":
                self.refresh_files()
            elif type == "intervention_count":
                if data > 0:
                    self.ui.widgets.lbl_interventions.config(text=f"({data})")
                else:
                    self.ui.widgets.lbl_interventions.config(text="")
            elif type == "request_intervention":
                # Show a blocking Yes/No dialog
                ans = messagebox.askyesno("Manual Intervention Required", 
                    f"⚠️ Persistent failure in Batch {data}. \n\nWould you like to manually fix these lines in Notepad?\n(Selecting 'No' will terminate the translation)", 
                    parent=self.root)
                # Send the response back to the engine
                self.engine.intervention_choice_q.put(ans)

        # Update Web Dashboard Active Clients Label
        if self.ui.widgets.web_gui_var.get():
            count = self.shared_state.active_clients
            if count > 0:
                self.ui.widgets.lbl_web_clients.config(text=f"({count} Active)")
            else:
                self.ui.widgets.lbl_web_clients.config(text="")
        else:
            self.ui.widgets.lbl_web_clients.config(text="")

        self.root.after(100, self.process_queues)

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use('clam')  # Allows much better customization than 'vista'
        
        bg_color = "#f4f7f9"     # Clean, very light blue-gray
        frame_bg = "#ffffff"     # White "Card" background
        accent_color = "#3498db" # Nice modern blue
        header_fg = "#2c3e50"    # Deep Navy
        
        self.root.configure(bg=bg_color)
        
        # Configure Frame & LabelFrame
        style.configure("TFrame", background=bg_color)
        style.configure("TLabelframe", background=frame_bg, bordercolor="#d1d8e0", relief="flat", borderwidth=1)
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground=header_fg, background=frame_bg)
        
        # Configuration for Labels and Inputs
        style.configure("TLabel", background=bg_color, font=("Segoe UI", 10), foreground="#34495e")
        style.configure("Configuration.TLabel", background=frame_bg) # For labels inside white cards
        
        # Style for Buttons to make them look more modern
        style.configure("TButton", font=("Segoe UI", 10), padding=5)
        style.map("TButton",
                  background=[('active', '#e0e4e8'), ('!disabled', '#f8f9fa')],
                  relief=[('pressed', 'sunken'), ('!pressed', 'solid')])
        
        # Entry fields
        style.configure("TEntry", fieldbackground="white", padding=5)
        style.configure("TCombobox", fieldbackground="white", padding=5)

    def copy_logs_to_clipboard(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.ui.widgets.log_text.get("1.0", tk.END))
        self.root.update()
        messagebox.showinfo("Copied", "Terminal logs copied!")

    def on_closing(self):
        """Graceful shutdown handler with aggressive terminal error suppression."""
        if self.web_server_started and hasattr(self, 'shared_state'):
            try:
                # 1. Wake up all background listeners (WebSocket threads)
                self.shared_state.shutdown()
                
                # 2. Signal the uvicorn server to exit
                if hasattr(self.shared_state, '_web_server'):
                    self.shared_state._web_server.should_exit = True
                    log(self.log_queue, self.session_log_file, "🌐 Web Dashboard shutting down...")
                
                # 3. Redirect stdout/stderr to devnull BEFORE the interpreter starts finalizing
                # This prevents the "could not acquire lock for <stdout>" errors
                import os # Ensure os is imported
                f = open(os.devnull, 'w')
                sys.stdout = f
                sys.stderr = f
            except: pass
        
        # Stop the engine if it's running
        if self.is_running:
            self.engine.request_stop()
            
        # Schedule the actual destruction with a 300ms delay to allow final cleanup
        # The user will see the window disappear, but the process has a moment to wrap up
        self.root.after(300, self.root.destroy)


    def _fmt_seconds(self, s):
        if s < 0: return "?"
        m = s // 60
        sec = s % 60
        return f"{m}:{sec:02d}"

    def _fmt_eta_full(self, seconds):
        if seconds <= 0: return "0s"
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        parts = []
        if d: parts.append(f"{d}d")
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        parts.append(f"{s:02d}s")
        return " ".join(parts)

    def _calculate_estimation(self, history, current_size, current_load=0, min_val=5):
        """
        Calculates time estimation using Smart 2D Linear Regression (Time = a * Load + b).
        """
        data = list(history) # Each entry is (duration, load)
        n = len(data)
        if n == 0: return -1

        if n >= 2:
            sum_x = sum(d[1] for d in data)
            sum_y = sum(d[0] for d in data)
            sum_xy = sum(d[1] * d[0] for d in data)
            sum_x2 = sum(d[1]**2 for d in data)
            denominator = (n * sum_x2 - sum_x**2)
            if denominator != 0:
                a_coeff = (n * sum_xy - sum_x * sum_y) / denominator
                b_coeff = (sum_y - a_coeff * sum_x) / n
                a_coeff = max(0.005, a_coeff) # Cap: min seconds per character
                return int(max(min_val, b_coeff + a_coeff * current_load))
            else:
                return int(max(min_val, (sum_y / sum_x) * current_load)) if sum_x > 0 else -1
        elif n == 1:
            return int(max(min_val, (data[0][0] / data[0][1]) * current_load)) if data[0][1] > 0 else -1
        
        return -1

    def _tick_timer(self):
        if self.resp_timer_seconds >= 0:
            self.resp_timer_seconds += 1
            if self.est_remaining > 0:
                self.est_remaining -= 1
            
            # Dynamic ETA Countdown
            if getattr(self, 'active_phase', None) in ["main", "judge"]:
                if self.total_eta_seconds > 0:
                    self.total_eta_seconds -= 1
                    new_eta_str = self._fmt_eta_full(self.total_eta_seconds)
                    self.ui.widgets.lbl_eta.config(text=f"ETA: {new_eta_str} | End: {self.last_finish_time_str}")
                    if self.ui.widgets.web_gui_var.get():
                        self.shared_state.update_eta(new_eta_str, self.last_finish_time_str)

            if getattr(self, 'active_phase', None) == "judge":
                est_str = f" / ⚖️ Est: {self._fmt_seconds(self.est_remaining)}" if self.est_remaining >= 0 else ""
                timer_text = f"⚖️ {self._fmt_seconds(self.resp_timer_seconds)}{est_str}"
            else:
                tag = "🔄 RETRY " if getattr(self, 'current_is_retry', False) else ""
                est_str = f" / 📦 Est: {self._fmt_seconds(self.est_remaining)}" if self.est_remaining >= 0 else ""
                timer_text = f"⏱️ {tag}{self._fmt_seconds(self.resp_timer_seconds)}{est_str}"
            
            self.ui.widgets.lbl_timer.config(text=timer_text)
            if self.ui.widgets.web_gui_var.get():
                self.shared_state.update_timer(timer_text)
            self._timer_after_id = self.root.after(1000, self._tick_timer)
    def _log_with_tags(self, text):
        target = self.ui.widgets.log_text
        tag = None
        
        # Priority mapping from Web Console logic
        if "✅" in text or "Batch saved successfully" in text:
            tag = "success"
        elif "⚠️" in text or "Batch Failure" in text or "❌" in text:
            tag = "error"
        elif "🔍" in text or "Auditor Flag" in text or "🧹" in text or "Sanitizer" in text:
            tag = "warning"
        elif "💰" in text or "[Main Model]" in text or "⚖️" in text or "[Judge Model]" in text:
            tag = "info"
        elif "🔄" in text:
            tag = "retry"
        elif "🚀" in text or "SESSION RESUMED" in text:
            tag = "success" # Emerald
        elif "⌛" in text:
            tag = "system"
            
        # VIBRANT ICON LOGIC: 
        # Separate the leading emoji from the rest of the text so it maintains its original multi-color.
        if text and not text[0].isascii():
            parts = text.split(" ", 1)
            icon = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            
            target.insert(tk.END, icon + " ")  # Neutral (uses colorful system emoji font)
            target.insert(tk.END, rest + "\n", tag) # Themed (tints the text only)
        else:
            target.insert(tk.END, text + "\n", tag)
            
        target.see(tk.END)

if __name__ == "__main__":
    import sys
    root = tk.Tk()
    app = TranslatorApp(root)
    
    if "--smoke_test" in sys.argv and not any(arg in ["1", "2", "3"] for arg in sys.argv):
        print("Smoke test: Initializing integrity checks...")
        def run_smoke_test():
            try:
                # 1. Widget Integrity Check (Ensures no UI elements were lost during migration)
                required_widgets = [
                    'source_combo', 'target_combo', 'model_combo', 'srt_combo', 
                    'sysprm_combo', 'judge_model_combo', 'resume_combo',
                    'native_instr_var', 'debug_var', 'web_gui_var', 
                    'bypass_intervention_var', 'progress_bar', 'log_text'
                ]
                for attr in required_widgets:
                    if not hasattr(app.ui.widgets, attr):
                        raise AttributeError(f"UI Error: Widget '{attr}' is missing from layout.")
                
                # 2. Module Import Check (Ensures core packages are reachable)
                import core.translation_engine
                import core.llm_api
                import utils.app_utils
                import utils.settings
                import services.web_server
                
                print("smoke test passed")
                root.destroy()
                sys.exit(0)
            except Exception as e:
                print(f"SMOKE TEST FAILED: {e}")
                root.destroy()
                sys.exit(1)
        root.after(2000, run_smoke_test)
        
    root.mainloop()
