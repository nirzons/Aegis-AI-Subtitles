import os
import sys
import datetime
import re
import json
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import messagebox, ttk

# Internal Modules
from settings import SETTINGS
from llm_api import is_process_alive
from gui_windows import LiveViewer, SettingsWindow, CheckpointsWindow
from app_utils import log, format_cost_display
from ui_layout import MainUILayout
from translation_engine import TranslationEngine

# Web GUI Modules
from shared_state import SharedState
from web_server import start_web_server


class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🛡️ Aegis AI Subtitles")
        self.root.geometry("900x750")

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
        self.current_is_retry = False
        self._timer_after_id = None
        
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

        # UI & Engine Initialization
        self.ui = MainUILayout(self.root)
        self.ui.setup(self)
        self.engine = TranslationEngine(self.log_queue, self.ui_queue)
        
        # Web GUI State
        self.shared_state = SharedState()
        self.web_server_started = False

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

    def _update_ui_from_checkpoint(self, ckpt):
        processed, total = ckpt.get("processed", 0), ckpt.get("total_blocks", 0)
        pct = (processed / total * 100) if total else 0
        self.ui.widgets.progress_var.set(pct)
        self.ui.widgets.lbl_progress.config(text=f"Progress: {processed}/{total} ({pct:.1f}%)")
        self.ui.widgets.lbl_cost.config(text=format_cost_display(ckpt.get("total_main_cost", 0.0), ckpt.get("total_judge_cost", 0.0)))
        
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
                threading.Thread(target=start_web_server, args=(self.shared_state, "0.0.0.0", 7860, self.log_queue), daemon=True).start()
                self.web_server_started = True
            else:
                log(self.log_queue, self.session_log_file, "🌐 Web Dashboard updates resumed.")
        else:
            log(self.log_queue, self.session_log_file, "🌐 Web Dashboard updates paused.")
                
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
            "output_dir": self.output_dir
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
            self.ui.widgets.log_text.insert(tk.END, text + "\n")
            self.ui.widgets.log_text.see(tk.END)
            if self.ui.widgets.web_gui_var.get():
                self.shared_state.append_log(text)
            
        while not self.ui_queue.empty():
            type, data = self.ui_queue.get()
            if type == "progress":
                p, t = data
                self.ui.widgets.progress_var.set((p/t*100) if t else 0)
                self.ui.widgets.lbl_progress.config(text=f"Progress: {p}/{t} ({(p/t*100) if t else 0:.1f}%)")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_progress(p, t)
            elif type == "eta":
                self.ui.widgets.lbl_eta.config(text=f"ETA: {data[0]} | End: {data[1]}")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_eta(data[0], data[1])
            elif type == "timer_start":
                # Safety: Cancel any existing timer loop before starting a new one
                if hasattr(self, '_timer_after_id') and self._timer_after_id:
                    self.root.after_cancel(self._timer_after_id)
                    self._timer_after_id = None

                self.last_batch_size, self.current_is_retry = data
                self.resp_timer_seconds = 0
                
                # Batch Size Change detection
                arrow = ""
                if self.num_batches_processed > 0 and self.previous_batch_size > 0:
                    if self.last_batch_size > self.previous_batch_size: arrow = " 🔼"
                    elif self.last_batch_size < self.previous_batch_size: arrow = " 🔽"
                
                self.ui.widgets.lbl_status.config(text=f"📦 Size: {self.last_batch_size}{arrow}")

                # Choose history based on retry status
                history = self.perf_history_new
                if self.current_is_retry:
                    if len(self.perf_history_retry) >= 2 or (len(self.perf_history_retry) == 1 and len(self.perf_history_new) == 0):
                        history = self.perf_history_retry
                    else:
                        history = self.perf_history_new

                # Calculate estimation
                self.est_remaining = -1
                n = len(history)
                if n >= 2:
                    sum_x = sum(h[1] for h in history)
                    sum_y = sum(h[0] for h in history)
                    sum_xy = sum(h[0] * h[1] for h in history)
                    sum_x2 = sum(h[1]**2 for h in history)
                    denominator = (n * sum_x2 - sum_x**2)
                    if denominator != 0:
                        a = (n * sum_xy - sum_x * sum_y) / denominator
                        b = (sum_y - a * sum_x) / n
                        a = max(0.1, a) 
                        self.est_remaining = int(max(5, b + a * self.last_batch_size))
                    else:
                        avg_sec = sum_y / sum_x
                        self.est_remaining = int(avg_sec * self.last_batch_size)
                elif n == 1:
                    avg_sec = history[0][0] / history[0][1]
                    self.est_remaining = int(avg_sec * self.last_batch_size)
                
                est_str = f" / 📦 Est: {self._fmt_seconds(self.est_remaining)}" if self.est_remaining > 0 else ""
                tag = "🔄 RETRY " if self.current_is_retry else ""
                self.ui.widgets.lbl_timer.config(text=f"⏱️ {tag}{self._fmt_seconds(self.resp_timer_seconds)}{est_str}")
                self._tick_timer()
            elif type == "timer_stop":
                if self.resp_timer_seconds > 0 and hasattr(self, 'last_batch_size'):
                    if getattr(self, 'current_is_retry', False):
                        self.perf_history_retry.append((self.resp_timer_seconds, self.last_batch_size))
                    else:
                        self.perf_history_new.append((self.resp_timer_seconds, self.last_batch_size))
                    
                    self.previous_batch_size = self.last_batch_size
                    self.num_batches_processed += 1

                self.resp_timer_seconds = -1
                self.ui.widgets.lbl_timer.config(text="")
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
                self.ui.widgets.lbl_status.config(text=f"📦 Size: {self.last_batch_size}", fg="#3498db")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_status(f"📦 Size: {self.last_batch_size}", "#3498db")
            elif type == "batch_success": # I should add this signal to engine
                self.ui.widgets.lbl_status.config(text="")
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_status("Processing...")
            elif type == "cost":
                self.ui.widgets.lbl_cost.config(text=format_cost_display(data[0], data[1]))
                if self.ui.widgets.web_gui_var.get():
                    self.shared_state.update_cost(data[0], data[1], display_text=self.ui.widgets.lbl_cost.cget("text"))
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
            elif type == "refresh":
                self.refresh_files()

        self.root.after(100, self.process_queues)

    def _toggle_ui_state(self, state):
        for w in [self.ui.widgets.model_combo, self.ui.widgets.batch_entry, self.ui.widgets.srt_combo, 
                  self.ui.widgets.sysprm_combo, self.ui.widgets.judge_model_combo, self.ui.widgets.judge_batch_entry,
                  self.ui.widgets.resume_combo, self.ui.widgets.btn_settings, self.ui.widgets.btn_manage_checkpoints,
                  self.ui.widgets.btn_refresh, self.ui.widgets.btn_start]:
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
        self.root.clipboard_append(self.ui.widgets.log_text.get(1.0, tk.END))
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

    def _tick_timer(self):
        if self.resp_timer_seconds >= 0:
            self.resp_timer_seconds += 1
            if self.est_remaining > 0:
                self.est_remaining -= 1
            
            tag = "🔄 RETRY " if getattr(self, 'current_is_retry', False) else ""
            est_str = f" / 📦 Est: {self._fmt_seconds(self.est_remaining)}" if self.est_remaining >= 0 else ""
            timer_text = f"⏱️ {tag}{self._fmt_seconds(self.resp_timer_seconds)}{est_str}"
            self.ui.widgets.lbl_timer.config(text=timer_text)
            if self.ui.widgets.web_gui_var.get():
                self.shared_state.update_timer(timer_text)
            self._timer_after_id = self.root.after(1000, self._tick_timer)
if __name__ == "__main__":
    root = tk.Tk()
    app = TranslatorApp(root)
    root.mainloop()
