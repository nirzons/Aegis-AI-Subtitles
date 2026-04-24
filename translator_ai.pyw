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
from settings import SETTINGS
from llm_api import is_process_alive
from gui_windows import LiveViewer, SettingsWindow, CheckpointsWindow
from app_utils import log, format_cost_display, get_eta_string
from ui_layout import MainUILayout
from translation_engine import TranslationEngine

# Web GUI Modules
from shared_state import SharedState
from web_server import start_web_server


class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🛡️ Aegis AI Subtitles")
        self.root.geometry("698x750")

        self._apply_styles()

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
        self.output_dir = os.path.join(self.curr_dir, "Translated Hebrew subtitles")
        self.checkpoint_dir = os.path.join(self.curr_dir, ".checkpoints")
        self.logs_dir = os.path.join(self.curr_dir, "logs")

        for d in [self.english_subs_dir, self.sysprm_dir, self.output_dir, self.logs_dir, self.checkpoint_dir]:
            os.makedirs(d, exist_ok=True)
            
        self.session_log_file = os.path.join(self.logs_dir, f"session_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        self.available_checkpoints = []

        # Web GUI State (Moved UP so the engine can access it)
        self.shared_state = SharedState()
        self.web_server_started = False

        # UI & Engine Initialization
        self.ui = MainUILayout(self.root)
        self.ui.setup(self)
        
        # Pass the shared_state object into the engine
        self.engine = TranslationEngine(self.log_queue, self.ui_queue, shared_state=self.shared_state)
        # Initial Actions
        self.refresh_files()
        self.refresh_models_ui()
        self.root.after(100, self.process_queues)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --- UI Event Handlers ---

    def on_model_change(self, event=None):
        idx_str = self.ui.widgets.model_var.get().split(" - ")[0]
        if idx_str in SETTINGS.config["models"]:
            self.ui.widgets.batch_size_var.set(str(SETTINGS.config["models"][idx_str]['batch_size']))

    def on_resume_selection(self, event=None):
        resume_val = self.ui.widgets.resume_var.get()
        if not resume_val or resume_val.startswith("[0]"):
            self._reset_ui_for_new_session()
            return
        
        match = re.search(r'\[(\d+)\]', resume_val)
        if match:
            choice_idx = int(match.group(1))
            if 0 < choice_idx <= len(self.available_checkpoints):
                ckpt = self.available_checkpoints[choice_idx - 1]
                self._update_ui_from_checkpoint(ckpt)

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
        time_str, finish_str, eta_secs = get_eta_string(elapsed, processed, processed, total)
        
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

    def toggle_debug_mode(self):
        is_debug = self.ui.widgets.debug_var.get()
        if is_debug:
            ans = messagebox.askyesno("Enable Debug Mode", "Enabling Debug Mode will write massive Input/Output transactions to the log file for EVERY batch.\n\nThis can cause your .txt log files to become extremely large.\n\nAre you sure you want to enable this?", parent=self.root)
            if not ans:
                self.ui.widgets.debug_var.set(False)
                return
                
        state_str = "ENABLED" if is_debug else "DISABLED"
        if hasattr(self, 'engine'):
            self.engine.debug_mode = is_debug
        log(self.log_queue, getattr(self, 'session_log_file', None), f"\n🐞 Debug Mode {state_str}\n")
                
    def toggle_web_gui(self):
        is_enabled = self.ui.widgets.web_gui_var.get()
        if is_enabled:
            # First time enablement check
            if not self.web_server_started:
                log(self.log_queue, self.session_log_file, "🌐 Initiating Web Dashboard binding...")
                threading.Thread(target=start_web_server, args=(self.shared_state, "0.0.0.0", None, self.log_queue), daemon=True).start()
                self.web_server_started = True
                # Give the server thread ~300ms to bind and write web_port, then update the label
                self.root.after(300, self._update_web_port_label)
            else:
                port = self.shared_state.web_port or 7860
                log(self.log_queue, self.session_log_file, f"🌐 Web Dashboard updates resumed. (http://localhost:{port})")
        else:
            log(self.log_queue, self.session_log_file, "🌐 Web Dashboard updates paused.")
                
    def toggle_bypass_intervention(self):
        """Toggles bypass intervention mode. Enabling requires explicit user acknowledgement."""
        if self.ui.widgets.bypass_intervention_var.get():
            ans = messagebox.askyesno(
                "⚠️ Enable Bypass Intervention Mode",
                "By enabling 'Bypass Intervention', the engine will automatically use a "
                "cleaned-up version of a failed AI output instead of pausing for manual correction.\n\n"
                "⚠️ This WILL introduce translation errors into your output file.\n\n"
                "A dedicated bypass log will be created so you can review and fix affected "
                "segments after the session ends.\n\n"
                "Do you understand and wish to proceed?",
                parent=self.root
            )
            if not ans:
                self.ui.widgets.bypass_intervention_var.set(False)
                return
            log(self.log_queue, self.session_log_file, "🚫 [BYPASS] Bypass Intervention Mode ENABLED — errors will be auto-logged.")
        else:
            log(self.log_queue, self.session_log_file, "🚫 [BYPASS] Bypass Intervention Mode DISABLED.")

    def _update_web_port_label(self):
        """Called ~300ms after the web server thread starts to display the actual bound port."""
        port = self.shared_state.web_port
        if port:
            log(self.log_queue, self.session_log_file, f"🌐 Web Dashboard ready → http://localhost:{port}")
            self.ui.widgets.lbl_web_clients.config(text=f"(:{port})")
        else:
            # Server hasn't bound yet — retry once more after another 500ms
            self.root.after(500, self._update_web_port_label)

    def refresh_files(self):
        sysprm_files = sorted([f for f in os.listdir(self.sysprm_dir) if f.lower().endswith('.sysprm')])
        srt_files = sorted([f for f in os.listdir(self.english_subs_dir) if f.endswith('.srt')])
        self.ui.widgets.srt_combo['values'] = srt_files
        self.ui.widgets.sysprm_combo['values'] = sysprm_files

        # Scan for Checkpoints
        self.available_checkpoints = []
        current_srt = self.ui.widgets.srt_var.get()
        try:
            for f in os.listdir(self.checkpoint_dir):
                if re.match(r'^translator_checkpoint_\d+\.json$', f):
                    path = os.path.join(self.checkpoint_dir, f)
                    mtime = os.path.getmtime(path)
                    with open(path, 'r', encoding='utf-8') as cp:
                        data = json.load(cp)
                        if data.get("processed", 0) > 0 and (data.get("pid") == os.getpid() or not is_process_alive(data.get("pid"))):
                            data["file_path"] = path
                            data["mtime"] = mtime
                            self.available_checkpoints.append(data)
            
            # Sort: Newest first
            self.available_checkpoints.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        except Exception: pass

        resume_options = ["[0] Start a NEW session (Ignore checkpoints)"]
        auto_select_idx = 0
        
        for i, ckpt in enumerate(self.available_checkpoints):
            total_str = f"/{ckpt['total_blocks']}" if ckpt['total_blocks'] else ""
            display_name = f"[{i+1}] Resume: {os.path.basename(ckpt['srt_file'])} ({ckpt['processed']}{total_str} blocks)"
            resume_options.append(display_name)
            
            # Auto-latch logic: If we have a match for the current SRT and we haven't selected anything yet (or were in new session)
            if auto_select_idx == 0 and os.path.basename(ckpt['srt_file']) == current_srt:
                auto_select_idx = i + 1

        self.ui.widgets.resume_combo['values'] = resume_options
        
        # Decide what to select
        current_val = self.ui.widgets.resume_var.get()
        if not current_val or current_val.startswith("[0]"):
            if auto_select_idx > 0:
                self.ui.widgets.resume_combo.current(auto_select_idx)
                self.on_resume_selection()
            else:
                self.ui.widgets.resume_combo.current(0)
        
        log(self.log_queue, self.session_log_file, "✅ File lists refreshed.")

    def restart_app(self):
        """Cleanly restarts the entire application to reload code changes."""
        log(self.log_queue, self.session_log_file, "🔄 Restarting application to reload modules...")
        self.on_closing() # Trigger cleanup
        
        # Replace current process with a fresh one
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def start_translation(self):
        if self.is_running: return
        
        resume_val = self.ui.widgets.resume_var.get()
        choice_idx = int(re.search(r'\[(\d+)\]', resume_val).group(1)) if resume_val else 0
        resume_mode = choice_idx > 0
        
        # Config gathering
        model_idx = self.ui.widgets.model_var.get().split(" - ")[0]
        judge_idx = self.ui.widgets.judge_model_var.get().split(" - ")[0]
        model_cfg = SETTINGS.config["models"].get(model_idx)
        judge_cfg = SETTINGS.config["models"].get(judge_idx) or model_cfg
        
        # 1. API Key Validation
        api_key = SETTINGS.config["api_keys"].get(model_cfg['provider'])
        judge_api_key = SETTINGS.config["api_keys"].get(judge_cfg['provider'])
        
        if not api_key:
            messagebox.showerror("Key Missing", f"API Key for '{model_cfg['provider'].upper()}' is missing.\n\nPlease click the ⚙️ Settings button to enter your key.")
            return

        if not judge_api_key:
            messagebox.showerror("Key Missing", f"API Key for Judge Provider '{judge_cfg['provider'].upper()}' is missing.\n\nPlease click the ⚙️ Settings button to enter your key.")
            return

        # 2. File Selection Validation

        srt_name = self.ui.widgets.srt_var.get()
        sys_name = self.ui.widgets.sysprm_var.get()
        if not resume_mode and (not srt_name or not sys_name):
            messagebox.showerror("Error", "Please select both an SRT file and a System Prompt for a new session.")
            return

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
            "logs_dir": self.logs_dir
        }

        if resume_mode:
            ckpt = self.available_checkpoints[choice_idx - 1]
            config.update({"checkpoint_data": ckpt, "checkpoint_file_path": ckpt["file_path"]})

        # Launch Engine
        self.is_running = True
        self.engine.should_stop = False
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
                self._toggle_ui_state(tk.NORMAL)
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.set_running(False)
                    self.shared_state.update_timer("")
            elif type == "refresh":
                self.refresh_files()
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

    def _toggle_ui_state(self, state):
        for w in [self.ui.widgets.model_combo, self.ui.widgets.batch_entry, self.ui.widgets.srt_combo, 
                  self.ui.widgets.sysprm_combo, self.ui.widgets.judge_model_combo, self.ui.widgets.judge_batch_entry,
                  self.ui.widgets.resume_combo, self.ui.widgets.btn_settings, self.ui.widgets.btn_manage_checkpoints,
                  self.ui.widgets.btn_restart, self.ui.widgets.btn_start]:
            w.config(state=state)
        self.ui.widgets.btn_stop.config(state=tk.NORMAL if state == tk.DISABLED else tk.DISABLED)
        self.ui.widgets.btn_open_translated.config(state=tk.NORMAL)

    def refresh_models_ui(self):
        model_list = [f"{k} - {v['name']} ({v['provider']})" for k, v in SETTINGS.config["models"].items()]
        self.ui.widgets.model_combo['values'] = model_list
        self.ui.widgets.judge_model_combo['values'] = model_list
        self.on_model_change()

    # --- Secondary Windows / Helpers ---
    def open_settings(self): SettingsWindow(self.root, self)
    def open_checkpoints_manager(self): CheckpointsWindow(self.root, self)
    def open_orig_srt(self): 
        path = os.path.join(self.english_subs_dir, self.ui.widgets.srt_var.get())
        if os.path.exists(path): subprocess.Popen(['notepad.exe', path])
    def open_translated_srt(self):
        if hasattr(self.engine, 'current_output_file') and self.engine.current_output_file:
            path = os.path.join(self.english_subs_dir, self.ui.widgets.srt_var.get())
            self.ui.widgets.btn_open_translated.config(state=tk.DISABLED)
            
            def re_enable():
                self.ui.widgets.btn_open_translated.config(state=tk.NORMAL)
                
            LiveViewer(self.root, path, self.engine.current_output_file, on_close=re_enable)
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
    root = tk.Tk()
    app = TranslatorApp(root)
    root.mainloop()
