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
        self._reset_ui_for_new_session = self.ui_controller._reset_ui_for_new_session
        self._update_ui_from_checkpoint = self.ui_controller._update_ui_from_checkpoint
        self._update_web_port_label = self.ui_controller._update_web_port_label
        self.start_translation = self.ui_controller.start_translation
        self.stop_translation = self.ui_controller.stop_translation
        self.process_queues = self.ui_controller.process_queues
        self.run_semantic_polish = self.ui_controller.run_semantic_polish


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



    # --- Actions ---






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
                    'bypass_intervention_var', 'progress_bar', 'log_text', 'btn_polish'
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
