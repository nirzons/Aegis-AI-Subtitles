import tkinter as tk
from tkinter import messagebox

class QueueDispatcher:
    def __init__(self, app, controller):
        self.app = app
        self.controller = controller

    def process_queues(self):
        while not self.app.log_queue.empty():
            text = self.app.log_queue.get()
            self.app._log_with_tags(text)
            if self.app.ui.widgets.web_gui_var.get():
                self.app.shared_state.append_log(text)
            
        while not self.app.ui_queue.empty():
            type, data = self.app.ui_queue.get()
            if type == "progress":
                p, t = data
                self.app.ui.widgets.progress_var.set((p/t*100) if t else 0)
                self.app.ui.widgets.lbl_progress.config(text=f"Progress: {p}/{t} ({(p/t*100) if t else 0:.1f}%)")
            elif type == "eta":
                time_str, finish_str, eta_secs = data
                self.app.total_eta_seconds = eta_secs
                self.app.last_finish_time_str = finish_str
                self.app.ui.widgets.lbl_eta.config(text=f"ETA: {time_str} | End: {finish_str}")
            elif type == "timer_start":
                # data is expected to be a dict
                if isinstance(data, dict):
                    self.app.last_batch_size = data.get("size", 1)
                    self.app.last_batch_load = data.get("load", 1)
                    self.app.current_is_retry = data.get("is_retry", False)
                else:
                    self.app.last_batch_size = data[0] if isinstance(data, tuple) else data
                    self.app.last_batch_load = self.app.last_batch_size * 50
                    self.app.current_is_retry = False

                # Safety: Cancel any existing timer loop before starting a new one
                if hasattr(self.app, '_timer_after_id') and self.app._timer_after_id:
                    self.app.root.after_cancel(self.app._timer_after_id)
                    self.app._timer_after_id = None

                self.app.resp_timer_seconds = 0
                self.app.active_phase = "main"

                # Batch Size Change detection
                arrow = ""
                if self.app.num_batches_processed > 0 and self.app.previous_batch_size > 0:
                    if self.app.last_batch_size > self.app.previous_batch_size: arrow = " 🔼"
                    elif self.app.last_batch_size < self.app.previous_batch_size: arrow = " 🔽"
                
                self.app.ui.widgets.lbl_status.config(text=f"📦 Size: {self.app.last_batch_size}{arrow}")

                # Update Web Dashboard
                if self.app.ui.widgets.web_gui_var.get():
                    if self.app.current_is_retry:
                        self.app.shared_state.update_status("Translating (Retry)", "#f59e0b")
                    else:
                        self.app.shared_state.update_status("Translating", "#0ea5e9")

                # Choose history based on retry status
                history = self.app.perf_history_new
                if self.app.current_is_retry:
                    if len(self.app.perf_history_retry) >= 2 or (len(self.app.perf_history_retry) == 1 and len(self.app.perf_history_new) == 0):
                        history = self.app.perf_history_retry
                    else:
                        history = self.app.perf_history_new

                # Calculate estimation
                self.app.est_remaining = self.app._calculate_estimation(history, self.app.last_batch_size, self.app.last_batch_load, min_val=5)
                
                est_str = f" / 📦 Est: {self.app._fmt_seconds(self.app.est_remaining)}" if self.app.est_remaining > 0 else ""
                tag = "🔄 RETRY " if self.app.current_is_retry else ""
                self.app.ui.widgets.lbl_timer.config(text=f"⏱️ {tag}{self.app._fmt_seconds(self.app.resp_timer_seconds)}{est_str}")
                self.app._tick_timer()
            elif type == "timer_stop":
                load = data if isinstance(data, (int, float)) else getattr(self.app, 'last_batch_load', self.app.last_batch_size * 50)
                if self.app.resp_timer_seconds > 0:
                    if getattr(self.app, 'current_is_retry', False):
                        self.app.perf_history_retry.append((self.app.resp_timer_seconds, load))
                    else:
                        self.app.perf_history_new.append((self.app.resp_timer_seconds, load))
                    
                    self.app.num_batches_processed += 1

                self.app.resp_timer_seconds = -1
                self.app.active_phase = None
                self.app.ui.widgets.lbl_timer.config(text="")
                if self.app.ui.widgets.web_gui_var.get():
                    self.app.shared_state.update_timer("")
            elif type == "judge_timer_start":
                # Clear previous timer state
                if hasattr(self.app, '_timer_after_id') and self.app._timer_after_id:
                    self.app.root.after_cancel(self.app._timer_after_id)
                    self.app._timer_after_id = None

                if isinstance(data, dict):
                    self.app.current_judge_chunk_size = data.get("size", 1)
                    self.app.current_judge_chunk_load = data.get("load", 1)
                else:
                    self.app.current_judge_chunk_size = data
                    self.app.current_judge_chunk_load = data * 100

                self.app.resp_timer_seconds = 0
                self.app.active_phase = "judge"

                # Calculate estimation for judge chunk
                self.app.est_remaining = self.app._calculate_estimation(self.app.perf_history_judge, self.app.current_judge_chunk_size, self.app.current_judge_chunk_load, min_val=2)

                est_str = f" / ⚖️ Est: {self.app._fmt_seconds(self.app.est_remaining)}" if self.app.est_remaining > 0 else ""
                self.app.ui.widgets.lbl_timer.config(text=f"⚖️ {self.app._fmt_seconds(self.app.resp_timer_seconds)}{est_str}")
                self.app._tick_timer()
            elif type == "judge_timer_stop":
                load = data if isinstance(data, (int, float)) else getattr(self.app, 'current_judge_chunk_load', self.app.current_judge_chunk_size * 100)
                if self.app.resp_timer_seconds > 0:
                    self.app.perf_history_judge.append((self.app.resp_timer_seconds, load))
                
                self.app.resp_timer_seconds = -1
                self.app.active_phase = None
            elif type == "judge_start":
                self.app.ui.widgets.lbl_status.config(text="⚖️ JUDGING...", fg="#9b59b6")
                if self.app.ui.widgets.web_gui_var.get():
                    self.app.shared_state.update_status("⚖️ JUDGING...", "#9b59b6")
            elif type == "judge_progress":
                c, t = data
                self.app.ui.widgets.lbl_status.config(text=f"⚖️ JUDGING {c}/{t}...", fg="#9b59b6")
                if self.app.ui.widgets.web_gui_var.get():
                    self.app.shared_state.update_status(f"⚖️ JUDGING {c}/{t}...", "#9b59b6")
            elif type == "judge_stop":
                self.app.ui.widgets.lbl_status.config(text="")
                self.app.ui.widgets.lbl_timer.config(text="")
                self.app.resp_timer_seconds = -1
                self.app.active_phase = None
                if self.app.ui.widgets.web_gui_var.get():
                    self.app.shared_state.update_status("Idle", "#7f8c8d")
                    self.app.shared_state.update_timer("")
            elif type == "batch_success": 
                self.app.ui.widgets.lbl_status.config(text="")
                if self.app.ui.widgets.web_gui_var.get():
                    self.app.shared_state.update_status("Saving Batch...", "#10b981")
            elif type == "cost":
                from utils.app_utils import format_cost_display
                if len(data) == 3:
                    main_cost, judge_cost, tokens_per_sec = data
                else:
                    main_cost, judge_cost = data
                    tokens_per_sec = 0

                self.app.ui.widgets.lbl_cost.config(text=format_cost_display(main_cost, judge_cost))
            elif type == "pipeline_telemetry":
                if data > 0:
                    self.app.speed_history.append(data)
                    speed_fmt = f"{data:.2f}" if data < 10 else f"{data:.1f}"
                    self.app.ui.widgets.lbl_speed.config(text=f"{speed_fmt} ch/s")
            elif type == "segment":
                if self.app.ui.widgets.web_gui_var.get():
                    idx, time_val, eng, heb = data
                    self.app.shared_state.add_segment(idx, time_val, eng, heb)
            elif type == "upcoming":
                if self.app.ui.widgets.web_gui_var.get():
                    self.app.shared_state.set_upcoming(data)
            elif type == "finished":
                self.app.is_running = False
                self.app.resp_timer_seconds = -1
                self.app.just_finished = True
                self.controller._toggle_ui_state(tk.NORMAL)
                self.app.ui.widgets.resume_combo.current(0)
                self.app.ui.widgets.lbl_eta.config(text="Completed")
                if data:
                    p, t = data
                    self.app.ui.widgets.progress_var.set((p/t*100) if t else 0)
                    self.app.ui.widgets.lbl_progress.config(text=f"Progress: {p}/{t} ({(p/t*100) if t else 0:.1f}%)")
                if self.app.ui.widgets.web_gui_var.get():
                    self.app.shared_state.set_running(False)
                    self.app.shared_state.update_timer("")
                    self.app.shared_state.update_eta("Completed", "")

            elif type == "refresh":
                self.controller.refresh_files()
            elif type == "intervention_count":
                if data > 0:
                    self.app.ui.widgets.lbl_interventions.config(text=f"({data})")
                else:
                    self.app.ui.widgets.lbl_interventions.config(text="")
            elif type == "request_intervention":
                ans = messagebox.askyesno("Manual Intervention Required", 
                    f"⚠️ Persistent failure in Batch {data}. \n\nWould you like to manually fix these lines in Notepad?\n(Selecting 'No' will terminate the translation)", 
                    parent=self.app.root)
                self.app.engine.intervention_choice_q.put(ans)

        # Update Web Dashboard Active Clients Label
        if self.app.ui.widgets.web_gui_var.get():
            count = self.app.shared_state.active_clients
            if count > 0:
                self.app.ui.widgets.lbl_web_clients.config(text=f"({count} Active)")
            else:
                self.app.ui.widgets.lbl_web_clients.config(text="")
        else:
            self.app.ui.widgets.lbl_web_clients.config(text="")
