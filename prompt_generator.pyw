import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

# Internal Modules
from language_profiles import BUILT_IN_PROFILES

class PromptGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🪄 Aegis SysPrm Prompt Generator")
        self.root.geometry("600x700")
        self._apply_styles()

        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        ttk.Label(main_frame, text="SysPrm AI Prompt Builder", font=("Segoe UI", 16, "bold")).pack(pady=(0, 20))

        # Show Name
        ttk.Label(main_frame, text="Show / Movie Name:").pack(anchor=tk.W)
        self.show_name_var = tk.StringVar(value="Survivor Season 46")
        ttk.Entry(main_frame, textvariable=self.show_name_var, width=50).pack(fill=tk.X, pady=(0, 15))

        # Languages
        lang_frame = ttk.Frame(main_frame)
        lang_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(lang_frame, text="Source Lang:").grid(row=0, column=0, sticky=tk.W)
        self.source_lang_var = tk.StringVar(value="en")
        self.source_combo = ttk.Combobox(lang_frame, textvariable=self.source_lang_var, values=sorted(BUILT_IN_PROFILES.keys()), width=10)
        self.source_combo.grid(row=1, column=0, padx=(0, 20), sticky=tk.W)

        ttk.Label(lang_frame, text="Target Lang:").grid(row=0, column=1, sticky=tk.W)
        self.target_lang_var = tk.StringVar(value="he")
        self.target_combo = ttk.Combobox(lang_frame, textvariable=self.target_lang_var, values=sorted(BUILT_IN_PROFILES.keys()), width=10)
        self.target_combo.grid(row=1, column=1, sticky=tk.W)

        # Instruction Mode
        self.native_instr_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="Use Native Instructions (Target Language)", variable=self.native_instr_var).pack(anchor=tk.W, pady=(0, 15))

        # Remarks / Specific Rules
        ttk.Label(main_frame, text="Special Remarks / Rules (e.g. 'Use formal tone', 'Slang guide'):").pack(anchor=tk.W)
        self.remarks_text = tk.Text(main_frame, height=8, font=("Segoe UI", 10))
        self.remarks_text.pack(fill=tk.BOTH, expand=True, pady=(0, 20))
        self.remarks_text.insert(tk.END, "provide a natural, dramatic, and accurate translation.")

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="📋 Copy Prompt to Clipboard", command=self.generate_and_copy).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💾 Save Prompt to File", command=self.generate_and_save).pack(side=tk.LEFT, padx=5)

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=5)

    def get_prompt_text(self):
        show = self.show_name_var.get()
        source = self.source_lang_var.get()
        target = self.target_lang_var.get()
        mode = "Native" if self.native_instr_var.get() else "English"
        remarks = self.remarks_text.get("1.0", tk.END).strip()

        prompt = f"""I am setting up a high-precision translation project in Aegis AI Subtitles. I need a master `.sysprm` configuration file for the show: **{show}**.

**PROJECT PARAMETERS:**
- Source Language ISO: {source}
- Target Language ISO: {target}
- Instruction Mode: {mode} (Target: {target})

**USER REQUIREMENTS & VOCABULARY:**
{remarks}

**INSTRUCTIONS FOR THE LLM:**
You are an expert subtitle localization engineer. Research the show **{show}** thoroughly and generate a comprehensive JSON configuration. 

> [!IMPORTANT]
> - If you do NOT recognize this show/movie, do NOT hallucinate. Stop and ask for details.
> - If the title is **ambiguous** or refers to a **large franchise** with many installments (e.g., "Star Wars", "James Bond", "Survivor"), do NOT provide a general overview. Instead, ask the user which specific installment, season, or year they are working on so you can provide precise character and plot data.

The JSON must include:

1. `language`: {{
    "source": "{source}",
    "target": "{target}",
    "use_native_instructions": {str(self.native_instr_var.get()).lower()},
    "max_words_per_line": 8
   }}

2. `series_context`: An array of strings organized with Markdown headers (###). It must include:
    - **Characters & Gender**: A list of all main characters with their gender and target-language transliteration.
    - **Dictionary**: A comprehensive list of show-specific terminology using the exact format: `- "Source Term" -> "Target Term" (Optional: Brief parenthetical explanation of the term's meaning in the show)`.
    - **Technical Rules**: Specific rules for handling labels, speaker tags (e.g. "PROBST:"), and tone.

3. `initial_context`: {{
    "last_speaker": "Unknown",
    "summary": "A brief opening summary of the show's current state.",
    "illegal_labels": [
        "Include a comprehensive list of ALL character names (source and target) and common speaker labels to be purged. IMPORTANT: Do NOT include the colon (:) character in these labels."
    ],
    "prompt_prefix": "A professional persona description (e.g. 'You are an expert translator specializing in...') tailored to {show}."
   }}

**CRITICAL FORMATTING RULES:**
- If Instruction Mode is "Native", all content inside `series_context` and `initial_context` MUST be written in {target}.
- Use the `- "Source" -> "Target" (Context)` format for dictionary entries where helpful.
- Research characters to ensure correct gender tracking (Crucial for languages like Hebrew/Arabic).
- Ensure `illegal_labels` contains raw names ONLY (e.g. "JEFF" instead of "JEFF:").
- Output ONLY the clean JSON code block.
"""
        return prompt

    def generate_and_copy(self):
        prompt = self.get_prompt_text()
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.root.update()
        messagebox.showinfo("Success", "LLM Prompt copied to clipboard!")

    def generate_and_save(self):
        prompt = self.get_prompt_text()
        filename = f"prompt_{self.show_name_var.get().replace(' ', '_').lower()}.txt"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(prompt)
            messagebox.showinfo("Success", f"Prompt saved to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = PromptGeneratorApp(root)
    root.mainloop()
