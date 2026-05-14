"""
Historical Audit Loader Engine
Provides infrastructure to list, select, parse, and load past Markdown Senior Editor reports
directly back into the Visual Merge Board, with automatic target SRT resolution.
"""
import os
import re
import sys
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

def clean_md_code(text):
    """Cleans markdown formatting markers and raw HTML entities from cells."""
    text = text.strip()
    while text.startswith("**") and text.endswith("**"):
        text = text[2:-2].strip()
    while text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    return text.replace("<br>", "\n").replace("\\|", "|")

def parse_md_report(md_path):
    """High-performance parser that reconstructs raw dictionaries from report tables,
    featuring split-row resiliency against physical newlines."""
    suggestions = []
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    lines = content.split('\n')
    
    table_started = False
    raw_rows = []
    target_srt = None
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        # Parse metadata to extract original target SRT filename
        if not target_srt and "**Project Target File:**" in stripped:
            m = re.search(r'\*\*Project Target File:\*\*\s*`(.*?)`', stripped)
            if m:
                target_srt = m.group(1)
                
        if stripped.startswith("| Cue | Original (EN) |"):
            table_started = True
            continue
        if table_started and stripped.startswith("| :--- |"):
            continue
            
        # Break early on next major section
        if table_started and (stripped.startswith("#") or stripped.startswith("---")):
            if len(raw_rows) > 5:
                break
                
        if table_started:
            if stripped.startswith("|"):
                parts = [p.strip() for p in stripped.split("|")]
                # Standard row begins with Numeric cue index
                if len(parts) > 1 and parts[1].strip().isdigit():
                    raw_rows.append(stripped)
                else:
                    if raw_rows:
                        raw_rows[-1] += " " + stripped
            else:
                # Physical newline wrap append
                if raw_rows:
                    raw_rows[-1] += " " + stripped
                    
    for row in raw_rows:
        parts = [p.strip() for p in row.split("|")]
        if len(parts) < 6:
            continue
            
        cue_idx = parts[1].strip()
        en_text = parts[2].strip().replace("<br>", "\n").replace("\\|", "|")
        curr_he = clean_md_code(parts[3])
        repl_he = clean_md_code(parts[4])
        
        reason_col = parts[5].strip()
        
        # Parse severity and confidence metadata
        severity = "CRITICAL"
        sev_match = re.search(r'\*\*\[(.*?)\]\*\*', reason_col)
        if sev_match:
            severity = sev_match.group(1)
            
        confidence = 1.0
        conf_match = re.search(r'\(Conf:\s*([0-9.]+)\)', reason_col)
        if conf_match:
            confidence = float(conf_match.group(1))
            
        reason_body = reason_col
        reason_body = re.sub(r'\*\*\[.*?\]\*\*', '', reason_body)
        reason_body = re.sub(r'\*\(Conf:.*?\)\*', '', reason_body)
        reason_body = reason_body.replace("<br>", "\n").replace("\\|", "|").strip()
        
        suggestions.append({
            "index": cue_idx,
            "en": en_text,
            "current_he": curr_he,
            "replacement_he": repl_he,
            "reason": reason_body,
            "severity": severity,
            "confidence": confidence
        })
        
    return suggestions, target_srt

class HistoricalAuditSelectionDialog:
    """Premium selection popup for listing and choosing existing markdown reports."""
    def __init__(self, parent, audit_reports):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("📜 Load Historical Audit Report")
        self.top.geometry("780x480")
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()
        
        # Force active focus
        self.top.focus_set()
        
        # Center UI perfectly over main Aegis container
        self.top.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw // 2) - (780 // 2)
        y = py + (ph // 2) - (480 // 2)
        self.top.geometry(f"+{x}+{y}")
        
        # Header Frame
        hdr = tk.Frame(self.top, bg="#2c3e50", height=75)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        
        lbl_t = tk.Label(hdr, text="🔍 Historical Audit Retrieval Console", font=("Segoe UI", 13, "bold"), fg="#ecf0f1", bg="#2c3e50")
        lbl_t.pack(pady=(14, 0), padx=22, anchor=tk.W)
        
        lbl_s = tk.Label(hdr, text="No subtitle is active. Please select a past Senior Editor report below to launch Visual Merge.", font=("Segoe UI", 9), fg="#bdc3c7", bg="#2c3e50")
        lbl_s.pack(padx=22, anchor=tk.W)
        
        # Body
        body = ttk.Frame(self.top, padding=18)
        body.pack(fill=tk.BOTH, expand=True)
        
        cols = ("name", "modified", "size")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Report Filename")
        self.tree.heading("modified", text="Audit Executed On")
        self.tree.heading("size", text="Dimensions")
        
        self.tree.column("name", width=420, anchor=tk.W)
        self.tree.column("modified", width=180, anchor=tk.CENTER)
        self.tree.column("size", width=110, anchor=tk.CENTER)
        
        sb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Event binds
        self.tree.bind("<Double-1>", lambda e: self._on_submit())
        
        # Populate entries
        for item in sorted(audit_reports, key=lambda x: x["mtime"], reverse=True):
            d_str = datetime.datetime.fromtimestamp(item["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
            sz_str = f"{item['size']/1024:.1f} KB"
            self.tree.insert("", tk.END, iid=item["path"], values=(item["name"], d_str, sz_str))
            
        # Bottom Action Grid
        bot = ttk.Frame(self.top, padding=(18, 15))
        bot.pack(fill=tk.X, side=tk.BOTTOM)
        
        btn_submit = ttk.Button(bot, text="🚀 Launch Visual Review Board", command=self._on_submit)
        btn_submit.pack(side=tk.RIGHT, padx=5)
        
        btn_close = ttk.Button(bot, text="Cancel / Go Back", command=self.top.destroy)
        btn_close.pack(side=tk.RIGHT, padx=5)
        
    def _on_submit(self):
        sel = self.tree.selection()
        if sel:
            self.result = sel[0] # The selected physical path
        self.top.destroy()

def execute_historical_rescue_flow(parent_root, workspace_root, app_ref):
    """Orchestrates the entire GUI popup, parsing, SRT path resolution, and UI spawning."""
    from ui.components.semantic_merge_window import SemanticMergeWindow
    from core.semantic_audit.merger import merge_approved_suggestions
    
    audit_dir = os.path.join(workspace_root, "Audit reports")
    if not os.path.exists(audit_dir):
        messagebox.showinfo("No Audits Found", "No historical 'Audit reports' folder detected in your project directory.", parent=parent_root)
        return
        
    # 1. Gather report files
    reports = []
    for filename in os.listdir(audit_dir):
        if filename.endswith(".md") and "SENIOR_EDITOR_REPORT" in filename:
            f_path = os.path.join(audit_dir, filename)
            stat = os.stat(f_path)
            reports.append({
                "path": f_path,
                "name": filename,
                "mtime": stat.st_mtime,
                "size": stat.st_size
            })
            
    if not reports:
        messagebox.showinfo("No Audits Found", "No Senior Editor audit reports (*.md) were found in the 'Audit reports' directory.", parent=parent_root)
        return
        
    # 2. Show beautiful selection dialog
    dialog = HistoricalAuditSelectionDialog(parent_root, reports)
    parent_root.wait_window(dialog.top)
    
    selected_path = dialog.result
    if not selected_path:
        return # User cancelled or closed popup
        
    # 3. Parse findings
    try:
        parsed_suggs, target_srt_name = parse_md_report(selected_path)
    except Exception as parse_err:
        messagebox.showerror("Parse Failure", f"Could not successfully read past report file:\n{parse_err}", parent=parent_root)
        return
        
    if not parsed_suggs or not target_srt_name:
        messagebox.showerror("Reconstruction Error", "Parsed report is corrupt or missing the target SRT project reference.", parent=parent_root)
        return
        
    # 4. Robustly resolve the Physical SRT Path across all workspace subfolders recursively!
    resolved_srt_path = None
    for r, d, files in os.walk(workspace_root):
        if target_srt_name in files:
            resolved_srt_path = os.path.join(r, target_srt_name)
            break
            
    if not resolved_srt_path:
        # Prompt user manually if recursive auto-discovery fails!
        from tkinter import filedialog
        messagebox.showwarning("SRT Not Found Automatically", 
            f"Successfully parsed {len(parsed_suggs)} corrections!\n\n"
            f"However, the target file '{target_srt_name}' was not found in your project.\n"
            f"Please browse manually to locate this translated SRT file.", parent=parent_root)
        chosen = filedialog.askopenfilename(
            title=f"Locate: {target_srt_name}",
            filetypes=[("SubRip Subtitles", "*.srt")],
            initialdir=workspace_root,
            parent=parent_root
        )
        if not chosen:
            return # User bailed on manual search
        resolved_srt_path = chosen

    # 5. Rebuild mock payload for window launch
    audit_data = {
        "report_file": selected_path,
        "suggestions": parsed_suggs,
        "suggestions_count": len(parsed_suggs),
        "duration_seconds": 0.0,
        "estimated_cost_usd": 0.0,
        "model": "deepseek-chat" # Fallback aesthetic label
    }
    
    # Bridge complete callback to call standard merge execution
    def on_apply_completed(approved_indices):
        try:
            merge_approved_suggestions(app_ref, approved_indices, audit_data, resolved_srt_path)
        except Exception as merge_err:
            messagebox.showerror("Merge Execution Failed", f"Crash during physical file rewrite:\n{merge_err}", parent=parent_root)

    # 6. Fire optimized Async Merge Board!
    from utils.settings import SETTINGS
    profile = SETTINGS.get_active_profile()
    
    try:
        window = SemanticMergeWindow(
            parent_root,
            audit_data,
            profile=profile,
            on_apply_callback=on_apply_completed
        )
        window.top.title(f"🚨 Aegis Historical Merge Board — {target_srt_name}")
    except Exception as w_err:
        messagebox.showerror("Window Instantiation Error", f"Failed to boot Merge window:\n{w_err}", parent=parent_root)
