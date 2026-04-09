import os
import json
import re
import tkinter as tk
from tkinter import ttk, messagebox

from settings import SETTINGS
from llm_api import is_process_alive


class LiveViewer:
    def __init__(self, parent, orig_file, trans_file):
        self.orig_file = orig_file
        self.trans_file = trans_file
        self.items_map = {}
        
        self.top = tk.Toplevel(parent)
        self.top.title("Live Translation Viewer")
        self.top.geometry("1100x600")
        
        frame = ttk.Frame(self.top)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.tree = ttk.Treeview(frame, columns=("Index", "Time", "English", "Hebrew"), show="headings", selectmode="extended")
        self.tree.heading("Index", text="#")
        self.tree.heading("Time", text="Timestamp")
        self.tree.heading("English", text="English Original")
        self.tree.heading("Hebrew", text="Hebrew Translated")
        
        self.tree.column("Index", width=50, stretch=tk.NO, anchor=tk.CENTER)
        self.tree.column("Time", width=220, stretch=tk.NO, anchor=tk.CENTER)
        self.tree.column("English", width=400, stretch=tk.YES, anchor=tk.W)
        self.tree.column("Hebrew", width=400, stretch=tk.YES, anchor=tk.E)
        
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("odd", background="#f0f0f0")
        
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.load_original()
        self.update_translations()
        
    def parse_blocks(self, file_path):
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read().replace('\r\n', '\n')
            blocks = [b.strip() for b in content.split('\n\n') if b.strip()]
            parsed = []
            for b in blocks:
                lines = b.split('\n')
                if len(lines) >= 3:
                    idx = lines[0].strip()
                    timestamp = lines[1].strip()
                    text = "\n".join([l.strip() for l in lines[2:]])
                    parsed.append({"index": idx, "time": timestamp, "text": text})
            return parsed
        except Exception:
            return []
            
    def load_original(self):
        blocks = self.parse_blocks(self.orig_file)
        for block_num, b in enumerate(blocks):
            lines = b["text"].split('\n')
            item_ids = []
            row_tag = "even" if block_num % 2 == 0 else "odd"
            for i, line in enumerate(lines):
                idx_val = b["index"] if i == 0 else ""
                time_val = b["time"] if i == 0 else ""
                item_id = self.tree.insert("", tk.END, values=(idx_val, time_val, line, ""), tags=(row_tag,))
                item_ids.append(item_id)
            
            self.items_map[b["index"]] = {
                "english_lines": lines,
                "hebrew_lines": [],
                "item_ids": item_ids,
                "tag": row_tag
            }
            
    def update_translations(self):
        if not self.top.winfo_exists():
            return
            
        trans_blocks = self.parse_blocks(self.trans_file)
        if trans_blocks:
            for b in trans_blocks:
                idx = b["index"]
                new_heb_lines = b["text"].split('\n')
                
                if idx in self.items_map:
                    data = self.items_map[idx]
                    eng_lines = data["english_lines"]
                    old_heb_lines = data["hebrew_lines"]
                    
                    if old_heb_lines != new_heb_lines:
                        item_ids = data["item_ids"]
                        max_lines = max(len(eng_lines), len(new_heb_lines))
                        
                        while len(item_ids) < max_lines:
                            insert_idx = self.tree.index(item_ids[-1]) + 1
                            new_id = self.tree.insert("", insert_idx, values=("", "", "", ""), tags=(data["tag"],))
                            item_ids.append(new_id)
                            
                        for i in range(max_lines):
                            e_line = eng_lines[i] if i < len(eng_lines) else ""
                            raw_h_line = new_heb_lines[i] if i < len(new_heb_lines) else ""
                            h_line = f" {raw_h_line}  " if raw_h_line else ""
                            
                            old_values = self.tree.item(item_ids[i], "values")
                            idx_val = old_values[0] if old_values and old_values[0] else ""
                            time_val = old_values[1] if old_values and len(old_values) > 1 and old_values[1] else ""
                            
                            self.tree.item(item_ids[i], values=(idx_val, time_val, e_line, h_line))
                            
                        data["hebrew_lines"] = new_heb_lines
                        
        self.top.after(3000, self.update_translations)


class SettingsWindow:
    def __init__(self, parent, app_instance):
        self.top = tk.Toplevel(parent)
        self.top.title("Settings & Configurations")
        self.top.geometry("600x500")
        self.app = app_instance
        
        self.notebook = ttk.Notebook(self.top)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.api_frame = ttk.Frame(self.notebook)
        self.models_frame = ttk.Frame(self.notebook)
        
        self.notebook.add(self.api_frame, text="API Keys")
        self.notebook.add(self.models_frame, text="Models")
        
        self.setup_api_keys()
        self.setup_models()
        
    def setup_api_keys(self):
        self.api_vars = {}
        row = 0
        for provider in ["google", "openai", "deepseek", "lmstudio"]:
            ttk.Label(self.api_frame, text=f"{provider.capitalize()} API Key:").grid(row=row, column=0, padx=10, pady=10, sticky=tk.W)
            var = tk.StringVar(value=SETTINGS.config["api_keys"].get(provider, ""))
            self.api_vars[provider] = var
            ttk.Entry(self.api_frame, textvariable=var, width=50).grid(row=row, column=1, padx=10, pady=10)
            row += 1
            
        ttk.Button(self.api_frame, text="Save API Keys", command=self.save_api_keys).grid(row=row, column=0, columnspan=2, pady=20)
        
    def save_api_keys(self):
        for provider, var in self.api_vars.items():
            SETTINGS.config["api_keys"][provider] = var.get()
        SETTINGS.save_settings()
        messagebox.showinfo("Saved", "API Keys saved successfully!", parent=self.top)
        
    def setup_models(self):
        frame_list = ttk.Frame(self.models_frame)
        frame_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.tree = ttk.Treeview(frame_list, columns=("ID", "Name", "Provider", "Batch"), show="headings", height=8)
        self.tree.heading("ID", text="ID")
        self.tree.heading("Name", text="Model Name")
        self.tree.heading("Provider", text="Provider")
        self.tree.heading("Batch", text="Batch Size")
        self.tree.column("ID", width=30, anchor=tk.CENTER)
        self.tree.column("Name", width=150)
        self.tree.column("Provider", width=100)
        self.tree.column("Batch", width=70, anchor=tk.CENTER)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_model_select)
        
        btn_frame = ttk.Frame(self.models_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(btn_frame, text="New Model", command=self.new_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Delete Selected", command=self.delete_model).pack(side=tk.LEFT, padx=5)
        
        form_frame = ttk.LabelFrame(self.models_frame, text="Edit Model")
        form_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.edit_vars = {
            "id": tk.StringVar(),
            "name": tk.StringVar(),
            "provider": tk.StringVar(),
            "batch_size": tk.StringVar(),
            "temperature": tk.StringVar(),
            "input_price": tk.StringVar(),
            "output_price": tk.StringVar()
        }
        
        ttk.Label(form_frame, text="ID:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Entry(form_frame, textvariable=self.edit_vars["id"], width=10).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(form_frame, text="Name:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        ttk.Entry(form_frame, textvariable=self.edit_vars["name"], width=25).grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
        
        ttk.Label(form_frame, text="Provider:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Combobox(form_frame, textvariable=self.edit_vars["provider"], values=["google", "openai", "deepseek", "lmstudio"], state="readonly", width=15).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(form_frame, text="Batch Size:").grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        ttk.Entry(form_frame, textvariable=self.edit_vars["batch_size"], width=10).grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)
        
        ttk.Label(form_frame, text="Temp:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Entry(form_frame, textvariable=self.edit_vars["temperature"], width=10).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(form_frame, text="Prices (In/Out):").grid(row=2, column=2, sticky=tk.W, padx=5, pady=2)
        price_frame = ttk.Frame(form_frame)
        price_frame.grid(row=2, column=3, sticky=tk.W, padx=5, pady=2)
        ttk.Entry(price_frame, textvariable=self.edit_vars["input_price"], width=8).pack(side=tk.LEFT)
        ttk.Entry(price_frame, textvariable=self.edit_vars["output_price"], width=8).pack(side=tk.LEFT, padx=5)

        ttk.Button(form_frame, text="Save Model Configuration", command=self.save_model).grid(row=3, column=0, columnspan=4, pady=10)
        
        self.refresh_model_list()
        
    def refresh_model_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for k, v in SETTINGS.config["models"].items():
            self.tree.insert("", tk.END, iid=k, values=(k, v.get("name",""), v.get("provider",""), v.get("batch_size","")))
            
    def on_model_select(self, event):
        selected = self.tree.selection()
        if not selected: return
        model_id = selected[0]
        cfg = SETTINGS.config["models"].get(model_id, {})
        self.edit_vars["id"].set(model_id)
        self.edit_vars["name"].set(cfg.get("name", ""))
        self.edit_vars["provider"].set(cfg.get("provider", "openai"))
        self.edit_vars["batch_size"].set(str(cfg.get("batch_size", "20")))
        self.edit_vars["temperature"].set(str(cfg.get("temperature", "0.0")))
        self.edit_vars["input_price"].set(str(cfg.get("input_price", "0.0")))
        self.edit_vars["output_price"].set(str(cfg.get("output_price", "0.0")))
        
    def new_model(self):
        existing_ids = [int(k) for k in SETTINGS.config["models"].keys() if k.isdigit()]
        new_id = str(max(existing_ids) + 1) if existing_ids else "1"
        self.edit_vars["id"].set(new_id)
        self.edit_vars["name"].set("new-model")
        self.edit_vars["provider"].set("openai")
        self.edit_vars["batch_size"].set("20")
        self.edit_vars["temperature"].set("0.0")
        self.edit_vars["input_price"].set("0.0")
        self.edit_vars["output_price"].set("0.0")
        
    def delete_model(self):
        selected = self.tree.selection()
        if not selected: return
        model_id = selected[0]
        if messagebox.askyesno("Delete", f"Are you sure you want to delete model ID {model_id}?", parent=self.top):
            if model_id in SETTINGS.config["models"]:
                del SETTINGS.config["models"][model_id]
                SETTINGS.save_settings()
                self.refresh_model_list()
                self.app.refresh_models_ui()
                
    def save_model(self):
        model_id = self.edit_vars["id"].get().strip()
        if not model_id:
            messagebox.showerror("Error", "Model ID cannot be empty", parent=self.top)
            return
            
        try:
            batch = int(self.edit_vars["batch_size"].get())
            temp = float(self.edit_vars["temperature"].get())
            iprice = float(self.edit_vars["input_price"].get())
            oprice = float(self.edit_vars["output_price"].get())
        except ValueError:
            messagebox.showerror("Error", "Numeric fields must be valid numbers", parent=self.top)
            return
            
        SETTINGS.config["models"][model_id] = {
            "name": self.edit_vars["name"].get().strip(),
            "provider": self.edit_vars["provider"].get().strip(),
            "batch_size": batch,
            "temperature": temp,
            "input_price": iprice,
            "output_price": oprice
        }
        SETTINGS.save_settings()
        messagebox.showinfo("Saved", "Model saved successfully!", parent=self.top)
        self.refresh_model_list()
        self.app.refresh_models_ui()


class CheckpointsWindow:
    def __init__(self, parent, app_instance):
        self.top = tk.Toplevel(parent)
        self.top.title("Manage Saved Sessions (Checkpoints)")
        self.top.geometry("650x400")
        self.app = app_instance
        
        frame = ttk.Frame(self.top)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(frame, text="Select a session to delete, or clear all saved sessions.", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        self.tree = ttk.Treeview(frame, columns=("File", "SRT", "Model", "Progress"), show="headings", height=12)
        self.tree.heading("File", text="Checkpoint File")
        self.tree.heading("SRT", text="SRT Target")
        self.tree.heading("Model", text="Model Name")
        self.tree.heading("Progress", text="Progress")
        
        self.tree.column("File", width=180, anchor=tk.W)
        self.tree.column("SRT", width=200, anchor=tk.W)
        self.tree.column("Model", width=130, anchor=tk.CENTER)
        self.tree.column("Progress", width=120, anchor=tk.CENTER)
        
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="Delete Selected", command=self.delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Delete ALL Sessions", command=self.delete_all).pack(side=tk.RIGHT, padx=5)
        
        self.refresh_list()
        
    def refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        checkpoints_dir = self.app.checkpoint_dir
        if not os.path.exists(checkpoints_dir): return
        
        for f in os.listdir(checkpoints_dir):
            if f.endswith('.json') and f.startswith("translator_checkpoint_"):
                ckpt_path = os.path.join(checkpoints_dir, f)
                try:
                    with open(ckpt_path, 'r', encoding='utf-8') as file:
                        data = json.load(file)
                    
                    pid = data.get("pid")
                    is_active = False
                    if pid and is_process_alive(pid):
                        is_active = True
                        
                    srt_name = os.path.basename(data.get("srt_file", "Unknown"))
                    model_id = str(data.get("model_choice", "?"))
                    model = SETTINGS.config["models"].get(model_id, {}).get("name", model_id)
                    proc = data.get("processed", 0)
                    tot = data.get("total_blocks", 0)
                    prog_str = f"{proc}/{tot}" if tot else str(proc)
                    
                    if is_active:
                        prog_str += " (ACTIVE)"
                        
                    self.tree.insert("", tk.END, iid=ckpt_path, values=(f, srt_name, model, prog_str))
                except Exception:
                    self.tree.insert("", tk.END, iid=ckpt_path, values=(f, "Corrupted/Invalid", "", ""))
                    
    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a session to delete.", parent=self.top)
            return
            
        file_path = selected[0]
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete this session checkpoint?\nThis cannot be undone.", parent=self.top):
            try:
                os.remove(file_path)
                self.refresh_list()
                self.app.refresh_files()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete:\n{e}", parent=self.top)
                
    def delete_all(self):
        if messagebox.askyesno("Confirm Delete ALL", "Are you sure you want to completely wipe ALL saved sessions?\nActive sessions in other windows might crash.\nThis cannot be undone.", parent=self.top):
            for item in self.tree.get_children():
                try:
                    os.remove(item)
                except Exception:
                    pass
            self.refresh_list()
            self.app.refresh_files()
            messagebox.showinfo("Success", "All session checkpoints deleted.", parent=self.top)
