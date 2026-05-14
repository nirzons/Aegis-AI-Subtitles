import os
import shutil
import tkinter as tk
from tkinter import ttk

class FileSelectionDialog(tk.Toplevel):
    def __init__(self, parent, title, prompt, items):
        """
        Modal dialog allowing the user to pick exactly which translation version 
        they want to Audit if multiple versions exist in the folder.
        """
        super().__init__(parent)
        self.title(title)
        self.geometry("500x300")
        self.transient(parent)
        self.grab_set()
        
        self.result = None
        
        lbl = tk.Label(self, text=prompt, wraplength=460, justify="left", font=("Segoe UI", 10), padx=15, pady=15)
        lbl.pack(anchor="w")
        
        frame = ttk.Frame(self, padding=(15, 0, 15, 10))
        frame.pack(fill=tk.BOTH, expand=True)
        
        self.listbox = tk.Listbox(frame, font=("Segoe UI", 10), bg="#ffffff", selectbackground="#3498db", selectmode=tk.SINGLE)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        
        for item in items:
            self.listbox.insert(tk.END, item)
            
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Pre-select first entry
        self.listbox.select_set(0)
        self.listbox.bind("<Double-Button-1>", lambda e: self._on_confirm())
        
        btn_frame = ttk.Frame(self, padding=15)
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="Select", command=self._on_confirm).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        
        parent.wait_window(self)
        
    def _on_confirm(self):
        sel = self.listbox.curselection()
        if sel:
            self.result = self.listbox.get(sel[0])
        self.destroy()
