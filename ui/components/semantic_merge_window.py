import os
import tkinter as tk
from tkinter import ttk, messagebox

class SemanticMergeWindow:
    def __init__(self, parent, audit_data, profile=None, on_apply_callback=None):
        """
        Phase 2, Step 2.2: Semantic Side-by-Side Merge Window Prototype.
        Lists all Senior Editor suggestions with checkboxes, allowing the user
        to visually review, check/uncheck, and confirm corrections.
        
        Args:
            parent: The TKinter parent window.
            audit_data: The dict object returned by run_semantic_audit_pipeline.
            profile: The current LanguageProfile.
            on_apply_callback: Function that receives the list of approved suggestions.
        """
        self.parent = parent
        self.audit_data = audit_data or {}
        
        # Deduplicate and sort the LLM suggestions strictly by integer cue index
        raw_sugs = self.audit_data.get("suggestions", [])
        unique_sugs = {}
        for sug in raw_sugs:
            try:
                c_idx = int(sug.get("index", -1))
                if c_idx != -1:
                    unique_sugs[c_idx] = sug # Overwrites, securely keeping the latest instance
            except ValueError:
                pass
                
        self.suggestions = [unique_sugs[k] for k in sorted(unique_sugs.keys())]
        self.audit_data["suggestions"] = self.suggestions # Sync back to ensure merger applies exact match
        
        self.profile = profile
        self.on_apply = on_apply_callback
        
        # State store for checkboxes and dynamic filtering references
        self.check_vars = {} # Map cue_index (str) -> tk.BooleanVar
        self.row_references = {} # Map cue_index (str) -> dict containing row frame and confidence
        self.threshold_var = tk.DoubleVar(value=0.80)
        
        self.top = tk.Toplevel(parent)
        self.top.title("🛡️ Senior Editor - Semantic Review Board")
        self.top.geometry("1200x750")
        self.top.minsize(900, 500)
        
        # Ensure modern theme and custom frames
        self._setup_styles()
        
        self._build_ui()
        
    def _setup_styles(self):
        style = ttk.Style()
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), background="#2c3e50", foreground="white")
        style.configure("Banner.TFrame", background="#ffffff")
        style.configure("Scroll.TFrame", background="#f4f7f9")
        style.configure("RowEven.TFrame", background="#ffffff")
        style.configure("RowOdd.TFrame", background="#f8f9fa")

    def _build_ui(self):
        # 1. Top Info Banner
        banner_frame = ttk.Frame(self.top, padding=15, style="Banner.TFrame")
        banner_frame.pack(fill=tk.X)
        
        icon_lbl = tk.Label(banner_frame, text="🔍", font=("Segoe UI", 24), bg="white")
        icon_lbl.pack(side=tk.LEFT, padx=(0, 10))
        
        info_container = tk.Frame(banner_frame, bg="white")
        info_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        title_lbl = tk.Label(info_container, text="Senior Editor Audit Findings", font=("Segoe UI", 14, "bold"), fg="#2c3e50", bg="white")
        title_lbl.pack(anchor=tk.W)
        
        model_name = self.audit_data.get("model", "DeepSeek")
        stats_text = f"Auditor ({model_name}) generated {len(self.suggestions)} potential improvements. Check the boxes to approve changes."
        desc_lbl = tk.Label(info_container, text=stats_text, font=("Segoe UI", 10), fg="#7f8c8d", bg="white")
        desc_lbl.pack(anchor=tk.W, pady=2)

        # 2. Global Checkbox Toolbar & Dynamic Threshold Filtering
        toolbar = ttk.Frame(self.top, padding=(15, 5))
        toolbar.pack(fill=tk.X)
        
        ttk.Button(toolbar, text="Select All", command=self._select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Deselect All", command=self._deselect_all).pack(side=tk.LEFT, padx=5)
        
        # UI Separator for clear visual grouping
        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill='y', padx=15, pady=2)
        
        # Threshold Slider, Value & Comparative Multi-Counts
        tk.Label(toolbar, text="Confidence Threshold:", font=("Segoe UI", 9, "bold"), fg="#2c3e50").pack(side=tk.LEFT)
        
        self.lbl_thresh_val = tk.Label(toolbar, text="0.80", font=("Segoe UI", 9, "bold"), width=4, fg="#2980b9")
        self.lbl_thresh_stats = tk.Label(toolbar, text="(📈 0 | 📉 0)", font=("Segoe UI", 9, "italic", "bold"), fg="#7f8c8d")
        
        def _on_slider_move(val):
            f_val = float(val)
            self.lbl_thresh_val.config(text=f"{f_val:.2f}")
            self._update_confidence_stats(f_val)
            
        scale = ttk.Scale(toolbar, from_=0.0, to=1.0, variable=self.threshold_var, command=_on_slider_move, length=120)
        scale.pack(side=tk.LEFT, padx=5)
        self.lbl_thresh_val.pack(side=tk.LEFT, padx=(0, 2))
        self.lbl_thresh_stats.pack(side=tk.LEFT, padx=(0, 12))
        
        # Compact, Elegant Interaction Controls for Maximum Visual Flow
        ttk.Button(toolbar, text="👁️ Hide Below", command=self._hide_below_threshold).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="👁️ Hide Above", command=self._hide_above_threshold).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="☑️ Select Above", command=self._select_above_threshold).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Show All", command=self._show_all).pack(side=tk.LEFT, padx=2)
        
        # 3. The Scrollable Grid Container
        table_container = ttk.Frame(self.top)
        table_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        # A. Grid Header
        header_frame = tk.Frame(table_container, bg="#34495e")
        header_frame.pack(fill=tk.X)
        
        # Configure grid weights for columns
        # Col 0: Active (50), Col 1: Cue (50), Col 2: Source (300), Col 3: Current (300), Col 4: Replacement (300), Col 5: Reason (200)
        headers = ["Approve", "Cue", "English Source", "Current Translation", "Proposed Replacement", "Reason & Details"]
        weights = [0, 0, 3, 3, 3, 2]
        widths = [80, 60, 250, 250, 250, 200]
        
        for idx, text in enumerate(headers):
            lbl = tk.Label(header_frame, text=text, font=("Segoe UI", 10, "bold"), bg="#34495e", fg="white", padx=10, pady=8, anchor=tk.W if idx != 3 and idx != 4 else tk.E)
            lbl.grid(row=0, column=idx, sticky="nsew")
            header_frame.grid_columnconfigure(idx, weight=weights[idx], minsize=widths[idx])

        # B. Canvas for Scrolling
        canvas = tk.Canvas(table_container, borderwidth=0, background="#f4f7f9", highlightthickness=0)
        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas, bg="#f4f7f9")
        
        # Center frame updates the canvas width to match viewport dynamically
        self.scroll_window_id = canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        
        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            
        def _on_canvas_configure(event):
            # Keep row frame stretching to canvas width
            canvas.itemconfig(self.scroll_window_id, width=event.width)
            
        self.scroll_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Mouse wheel scrolling handlers
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 4. Populate Rows (High-Speed Progressive Streaming Engine to prevent UI Lockup)
        if not self.suggestions:
            empty_lbl = tk.Label(self.scroll_frame, text="🎉 No critical issues or suggestions found! Your subtitle file is immaculate.", font=("Segoe UI", 12, "italic"), bg="#f4f7f9", fg="#7f8c8d", pady=50)
            empty_lbl.pack(fill=tk.BOTH, expand=True)
        else:
            # Instantiating thousands of Tkinter widgets at once freezes Tcl. 
            # We stream them in fast async batches!
            self.loading_lbl = tk.Label(self.scroll_frame, text=f"⏳ Streaming {len(self.suggestions)} suggestions to Review Board... (0%)", font=("Segoe UI", 11, "bold"), bg="#f4f7f9", fg="#2980b9", pady=25)
            self.loading_lbl.pack(fill=tk.X)
            
            self._current_load_idx = 0
            self._load_batch_size = 20 # Highly responsive chunk limit
            
            def _load_chunk():
                try:
                    if not self.top.winfo_exists():
                        return
                except Exception:
                    return # Window closed during streaming
                    
                end_idx = min(self._current_load_idx + self._load_batch_size, len(self.suggestions))
                for i in range(self._current_load_idx, end_idx):
                    self._add_row(i, self.suggestions[i])
                    
                self._current_load_idx = end_idx
                pct = int((self._current_load_idx / len(self.suggestions)) * 100)
                
                try:
                    self.loading_lbl.config(text=f"⏳ Streaming suggestions into Review Board... {self._current_load_idx}/{len(self.suggestions)} ({pct}%)")
                    
                    if self._current_load_idx < len(self.suggestions):
                        # Schedule next fast chunk
                        self.top.after(1, _load_chunk)
                    else:
                        # Render complete! Remove placeholder and compute analytics.
                        self.loading_lbl.pack_forget()
                        self._update_confidence_stats()
                except Exception:
                    pass
                    
            # Kickoff asynchronous UI builder thread pump after a brief 50ms window boot!
            self.top.after(50, _load_chunk)
                
        # 5. Bottom Action Bar
        action_frame = ttk.Frame(self.top, padding=15)
        action_frame.pack(fill=tk.X)
        
        apply_btn = ttk.Button(action_frame, text="💾 Apply Selected Fixes", command=self._on_apply_click)
        apply_btn.pack(side=tk.RIGHT, padx=5)
        
        cancel_btn = ttk.Button(action_frame, text="Cancel", command=self.top.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=5)

    def _add_row(self, idx, item):
        row_bg = "#ffffff" if idx % 2 == 0 else "#f8f9fa"
        cue_idx = str(item.get("index", ""))
        
        # Create var and default to Checked (True)
        var = tk.BooleanVar(value=True)
        self.check_vars[cue_idx] = var
        
        row_frame = tk.Frame(self.scroll_frame, bg=row_bg, bd=1, relief=tk.RIDGE)
        row_frame.pack(fill=tk.X, pady=(0, 1))
        
        # Match column weights with header
        weights = [0, 0, 3, 3, 3, 2]
        widths = [80, 60, 250, 250, 250, 200]
        for i in range(6):
            row_frame.grid_columnconfigure(i, weight=weights[i], minsize=widths[i])
            
        # Col 0: Checkbox
        chk = tk.Checkbutton(row_frame, variable=var, bg=row_bg, activebackground=row_bg)
        chk.grid(row=0, column=0, padx=10, pady=15, sticky="n")
        
        # Col 1: Cue Index
        cue_lbl = tk.Label(row_frame, text=f"#{cue_idx}", font=("Consolas", 10, "bold"), bg=row_bg, fg="#34495e")
        cue_lbl.grid(row=0, column=1, padx=10, pady=15, sticky="n")
        
        # Fonts
        src_font = ("Segoe UI", 10)
        trg_font = ("Arial", 11) # Hebrew font
        details_font = ("Segoe UI", 9)
        
        # Text Alignment
        is_rtl = True # Direct RTL target for Hebrew
        align_target = tk.E if is_rtl else tk.W
        justify_target = "right" if is_rtl else "left"
        
        # Wrap length constraints (calculated roughly based on minsize)
        wl_source = 230
        wl_target = 230
        wl_reason = 180
        
        # Col 2: English Original
        en_text = item.get("en", "")
        en_lbl = tk.Label(row_frame, text=en_text, font=src_font, bg=row_bg, fg="#2c3e50", wraplength=wl_source, justify="left", anchor="nw")
        en_lbl.grid(row=0, column=2, padx=10, pady=15, sticky="nw")
        
        # Col 3: Current Hebrew
        cur_text = item.get("current_he", "")
        cur_lbl = tk.Label(row_frame, text=cur_text, font=trg_font, bg=row_bg, fg="#7f8c8d", wraplength=wl_target, justify=justify_target, anchor="ne" if is_rtl else "nw")
        cur_lbl.grid(row=0, column=3, padx=10, pady=15, sticky="ne" if is_rtl else "nw")
        
        # Col 4: Proposed Hebrew (Highlighted in light mint if approved!)
        prop_text = item.get("replacement_he", "")
        prop_frame = tk.Frame(row_frame, bg="#e8f8f5" if idx % 2 == 0 else "#d1f2eb", bd=0)
        prop_frame.grid(row=0, column=4, padx=5, pady=5, sticky="nsew")
        
        prop_lbl = tk.Label(prop_frame, text=prop_text, font=trg_font, bg=prop_frame["bg"], fg="#27ae60", wraplength=wl_target, justify=justify_target, anchor="ne" if is_rtl else "nw")
        # Apply bold style safely via config
        prop_lbl.config(font=(trg_font[0], trg_font[1], "bold"))
        prop_lbl.pack(fill=tk.BOTH, expand=True, padx=5, pady=10)
        
        # Col 5: Reason, Severity & AI Confidence
        reason = item.get("reason", "")
        severity = item.get("severity", "").upper()
        confidence = float(item.get("confidence", 1.0))
        
        sev_color = "#e74c3c" if "CRITICAL" in severity else "#f39c12"
        
        reason_container = tk.Frame(row_frame, bg=row_bg)
        reason_container.grid(row=0, column=5, padx=10, pady=15, sticky="nw")
        
        sev_lbl = tk.Label(reason_container, text=f"[{severity}]", font=("Segoe UI", 8, "bold"), fg=sev_color, bg=row_bg)
        sev_lbl.pack(anchor="w")
        
        reason_lbl = tk.Label(reason_container, text=reason, font=details_font, fg="#34495e", bg=row_bg, wraplength=wl_reason, justify="left", anchor="nw")
        reason_lbl.pack(anchor="w", pady=(2, 0))
        
        # Highlighted Confidence Display (Colors shifting beautifully for quick scanning)
        conf_color = "#16a085" if confidence >= 0.80 else "#7f8c8d"
        conf_lbl = tk.Label(reason_container, text=f"Confidence: {confidence:.2f}", font=("Segoe UI", 8, "italic", "bold"), fg=conf_color, bg=row_bg)
        conf_lbl.pack(anchor="w", pady=(6, 0))
        
        # Save references for active Toolbar dynamic operations
        self.row_references[cue_idx] = {
            "frame": row_frame,
            "confidence": confidence
        }

    def _select_all(self):
        for var in self.check_vars.values():
            var.set(True)
            
    def _deselect_all(self):
        for var in self.check_vars.values():
            var.set(False)

    def _on_apply_click(self):
        # Gather all cue indices that remain checked
        approved_indices = [idx for idx, var in self.check_vars.items() if var.get()]
        
        if not approved_indices:
            ans = messagebox.askyesno("No Items Selected", "You haven't checked any improvements. Are you sure you want to revert all changes to the original file?", parent=self.top)
            if not ans:
                return
            
        if self.on_apply:
            self.on_apply(approved_indices)
        
    def _hide_below_threshold(self):
        """
        Hides all visually rendered subtitle rows from the scroll frame 
        whose AI-assessed confidence level is strictly lower than the active threshold.
        """
        threshold = self.threshold_var.get()
        # Temporarily strip packing to reset visibility sequentially
        for ref in self.row_references.values():
            ref["frame"].pack_forget()
            
        # Repack elements satisfying condition in perfect numeric sequence
        for item in self.suggestions:
            cue_idx = str(item.get("index", ""))
            ref = self.row_references.get(cue_idx)
            if ref and ref["confidence"] >= threshold:
                ref["frame"].pack(fill=tk.X, pady=(0, 1))
                
    def _hide_above_threshold(self):
        """
        Hides all visually rendered subtitle rows from the scroll frame 
        whose AI-assessed confidence level is strictly greater than or equal to the active threshold.
        Allows operators to concentrate 100% on edge cases below the confidence floor.
        """
        threshold = self.threshold_var.get()
        for ref in self.row_references.values():
            ref["frame"].pack_forget()
            
        for item in self.suggestions:
            cue_idx = str(item.get("index", ""))
            ref = self.row_references.get(cue_idx)
            if ref and ref["confidence"] < threshold:
                ref["frame"].pack(fill=tk.X, pady=(0, 1))

    def _show_all(self):
        """
        Completely restores visual packing visibility to all subtitle rows in their original order.
        """
        for item in self.suggestions:
            cue_idx = str(item.get("index", ""))
            ref = self.row_references.get(cue_idx)
            if ref:
                ref["frame"].pack(fill=tk.X, pady=(0, 1))

    def _select_above_threshold(self):
        """
        Automatically ticks checkboxes for all rows meeting the threshold, 
        and unticks rows falling below it.
        """
        threshold = self.threshold_var.get()
        for cue_idx, ref in self.row_references.items():
            var = self.check_vars.get(cue_idx)
            if var:
                if ref["confidence"] >= threshold:
                    var.set(True)
                else:
                    var.set(False)

    def _update_confidence_stats(self, val=None):
        """
        Runs live iterative tracking across datasets to accurately display the exact
        number of items situated above and below the slider's current confidence cutoff.
        """
        try:
            threshold = float(val) if val is not None else self.threshold_var.get()
        except Exception:
            return
            
        above = 0
        below = 0
        
        # Utilize primary indexed row map if population complete
        if self.row_references:
            for ref in self.row_references.values():
                if ref["confidence"] >= threshold:
                    above += 1
                else:
                    below += 1
        else:
            # High-resiliency fallback to raw dictionaries if called prior to grid loading
            for item in self.suggestions:
                confidence = float(item.get("confidence", 1.0))
                if confidence >= threshold:
                    above += 1
                else:
                    below += 1
                    
        # Direct, safe UI push to standard readout labels
        if hasattr(self, 'lbl_thresh_stats'):
            self.lbl_thresh_stats.config(text=f"(📈 {above} | 📉 {below})")
