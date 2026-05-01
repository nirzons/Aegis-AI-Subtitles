import os
import sys
import subprocess
import tkinter as tk
from tkinter import messagebox

# Internal Modules
from utils.settings import SETTINGS
from ui.gui_windows import SettingsWindow, CheckpointsWindow, LiveViewer
from utils.app_utils import log

class UIController:
    def __init__(self, app):
        self.app = app

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
