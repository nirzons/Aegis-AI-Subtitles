import tkinter as tk
from tkinter import ttk, scrolledtext
from types import SimpleNamespace

class MainUILayout:
    def __init__(self, root):
        self.root = root
        self.widgets = SimpleNamespace()
        
        # Define styles for consistent look
        style = ttk.Style()
        style.configure("Configuration.TLabel", font=("Segoe UI", 9, "bold"), background="#ffffff")
        self.root.configure(bg="#ffffff")

    def setup(self, app):
        """Builds the visual structure and binds to the app instance."""
        
        # 0. Header
        header_label = tk.Label(self.root, text="🛡️ Aegis AI Subtitles", font=("Segoe UI", 14, "bold"), fg="#2c3e50", bg="#f4f7f9")
        header_label.pack(pady=15, fill=tk.X)

        # 1. Configuration Frame
        top_frame = ttk.LabelFrame(self.root, text=" ⚙️ CONFIGURATION ")
        top_frame.pack(fill=tk.X, padx=15, pady=5)

        def create_label(parent, text):
            return ttk.Label(parent, text=text, style="Configuration.TLabel")

        create_label(top_frame, "Model:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.widgets.model_var = tk.StringVar()
        self.widgets.model_combo = ttk.Combobox(top_frame, textvariable=self.widgets.model_var, state="readonly", width=35)
        self.widgets.model_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        create_label(top_frame, "Batch Size:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.widgets.batch_size_var = tk.StringVar()
        self.widgets.batch_entry = ttk.Entry(top_frame, textvariable=self.widgets.batch_size_var, width=10)
        self.widgets.batch_entry.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)

        self.widgets.model_combo.bind("<<ComboboxSelected>>", app.on_model_change)

        create_label(top_frame, "SRT File:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.widgets.srt_var = tk.StringVar()
        self.widgets.srt_combo = ttk.Combobox(top_frame, textvariable=self.widgets.srt_var, state="readonly", width=45)
        self.widgets.srt_combo.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky=tk.W)
        self.widgets.btn_open_srt = ttk.Button(top_frame, text="Open Original", command=app.open_orig_srt)
        self.widgets.btn_open_srt.grid(row=1, column=3, padx=5, pady=5)

        create_label(top_frame, "System Prompt:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.widgets.sysprm_var = tk.StringVar()
        self.widgets.sysprm_combo = ttk.Combobox(top_frame, textvariable=self.widgets.sysprm_var, state="readonly", width=60)
        self.widgets.sysprm_combo.grid(row=2, column=1, columnspan=3, padx=5, pady=5, sticky=tk.W)

        create_label(top_frame, "Judge Model:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        self.widgets.judge_model_var = tk.StringVar()
        self.widgets.judge_model_combo = ttk.Combobox(top_frame, textvariable=self.widgets.judge_model_var, state="readonly", width=35)
        self.widgets.judge_model_combo.grid(row=3, column=1, padx=5, pady=5, sticky=tk.W)

        create_label(top_frame, "Judge Batch:").grid(row=3, column=2, padx=5, pady=5, sticky=tk.W)
        self.widgets.judge_batch_var = tk.StringVar(value="4")
        self.widgets.judge_batch_entry = ttk.Entry(top_frame, textvariable=self.widgets.judge_batch_var, width=10)
        self.widgets.judge_batch_entry.grid(row=3, column=3, padx=5, pady=5, sticky=tk.W)

        create_label(top_frame, "Resume Session:").grid(row=4, column=0, padx=5, pady=5, sticky=tk.W)
        resume_frame = tk.Frame(top_frame, bg="white") # Native Frame for white background consistency
        resume_frame.grid(row=4, column=1, columnspan=3, sticky=tk.W, padx=5, pady=5)
        
        self.widgets.resume_var = tk.StringVar()
        self.widgets.resume_combo = ttk.Combobox(resume_frame, textvariable=self.widgets.resume_var, state="readonly", width=60)
        self.widgets.resume_combo.pack(side=tk.LEFT)
        
        self.widgets.btn_manage_checkpoints = ttk.Button(resume_frame, text="🗑️", width=3, command=app.open_checkpoints_manager)
        self.widgets.btn_manage_checkpoints.pack(side=tk.LEFT, padx=5)
        
        self.widgets.resume_combo.bind("<<ComboboxSelected>>", app.on_resume_selection)

        # 2. Control Buttons Frame
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill=tk.X, padx=15, pady=10)

        self.widgets.btn_refresh = ttk.Button(ctrl_frame, text="🔄 Refresh", command=app.refresh_files)
        self.widgets.btn_refresh.pack(side=tk.LEFT, padx=5)

        self.widgets.btn_settings = ttk.Button(ctrl_frame, text="⚙️ Settings", command=app.open_settings)
        self.widgets.btn_settings.pack(side=tk.LEFT, padx=5)

        self.widgets.btn_start = ttk.Button(ctrl_frame, text="🚀 Start", command=app.start_translation)
        self.widgets.btn_start.pack(side=tk.LEFT, padx=5)

        self.widgets.btn_stop = ttk.Button(ctrl_frame, text="🛑 Stop", command=app.stop_translation, state=tk.DISABLED)
        self.widgets.btn_stop.pack(side=tk.LEFT, padx=5)

        self.widgets.btn_open_translated = ttk.Button(ctrl_frame, text="📂 View Output", command=app.open_translated_srt, state=tk.DISABLED)
        self.widgets.btn_open_translated.pack(side=tk.LEFT, padx=5)

        self.widgets.debug_var = tk.BooleanVar(value=False)
        self.widgets.chk_debug = ttk.Checkbutton(ctrl_frame, text="🐞 Debug mode", variable=self.widgets.debug_var, command=app.toggle_debug_mode)
        self.widgets.chk_debug.pack(side=tk.LEFT, padx=15)

        # 3. Status & Progress Frame
        progress_header = tk.Frame(self.root, bg=self.root["bg"])
        tk.Label(progress_header, text=" 📊 STATUS & PROGRESS ", font=("Segoe UI", 10, "bold"), foreground="#2c3e50", background=self.root["bg"]).pack(side=tk.LEFT)
        
        self.widgets.web_gui_var = tk.BooleanVar(value=False)
        self.widgets.chk_web_gui = ttk.Checkbutton(progress_header, text="🌐 Web Dashboard", variable=self.widgets.web_gui_var, command=app.toggle_web_gui)
        self.widgets.chk_web_gui.pack(side=tk.LEFT, padx=20)
        
        self.widgets.lbl_web_clients = tk.Label(progress_header, text="", font=("Segoe UI", 8, "italic"), fg="#3498db", bg=self.root["bg"])
        self.widgets.lbl_web_clients.pack(side=tk.LEFT, padx=5)

        progress_frame = ttk.LabelFrame(self.root, labelwidget=progress_header)
        progress_frame.pack(fill=tk.X, padx=15, pady=5)

        self.widgets.progress_var = tk.DoubleVar()
        self.widgets.progress_bar = ttk.Progressbar(progress_frame, variable=self.widgets.progress_var, maximum=100)
        self.widgets.progress_bar.pack(fill=tk.X, padx=10, pady=10)

        lbl_container = tk.Frame(progress_frame, bg="white")
        lbl_container.pack(fill=tk.X, padx=10, pady=5)

        self.widgets.lbl_progress = tk.Label(lbl_container, text="Progress: 0/0 (0%)", bg="white", font=("Segoe UI", 9))
        self.widgets.lbl_progress.pack(side=tk.LEFT, padx=5)

        self.widgets.lbl_eta = tk.Label(lbl_container, text="ETA: --:--", bg="white", font=("Segoe UI", 9))
        self.widgets.lbl_eta.pack(side=tk.LEFT, padx=15)

        self.widgets.lbl_speed = tk.Label(lbl_container, text="", bg="white", font=("Segoe UI", 9), fg="#9b59b6")
        self.widgets.lbl_speed.pack(side=tk.LEFT, padx=5)

        self.widgets.lbl_sparkline = tk.Label(lbl_container, text="", bg="white", font=("Consolas", 10), fg="#8e44ad")
        self.widgets.lbl_sparkline.pack(side=tk.LEFT, padx=2)

        self.widgets.lbl_cost = tk.Label(lbl_container, text="Cost: $0.00", bg="white", font=("Segoe UI", 9, "bold"), fg="#27ae60")
        self.widgets.lbl_cost.pack(side=tk.RIGHT, padx=15)

        # 4. Terminal Output Frame
        term_header = tk.Frame(self.root, bg=self.root["bg"])
        tk.Label(term_header, text=" 💻 TERMINAL OUTPUT ", font=("Segoe UI", 10, "bold"), fg="#2c3e50", bg=self.root["bg"]).pack(side=tk.LEFT)
        self.widgets.btn_copy = ttk.Button(term_header, text="📋 Copy Logs", width=15, command=app.copy_logs_to_clipboard)
        self.widgets.btn_copy.pack(side=tk.LEFT, padx=10)
        
        self.widgets.lbl_timer = tk.Label(term_header, text="", font=("Segoe UI", 10, "bold"), fg="#e67e22", bg=self.root["bg"])
        self.widgets.lbl_timer.pack(side=tk.RIGHT, padx=15)
        
        self.widgets.lbl_status = tk.Label(term_header, text="", font=("Segoe UI", 10, "bold"), fg="#3498db", bg=self.root["bg"])
        self.widgets.lbl_status.pack(side=tk.RIGHT, padx=5)

        term_frame = ttk.LabelFrame(self.root, labelwidget=term_header)
        term_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        self.widgets.log_text = scrolledtext.ScrolledText(term_frame, wrap=tk.WORD, font=("Consolas", 10), bg="#1e272e", fg="#d1d8e0", insertbackground="white")
        self.widgets.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
