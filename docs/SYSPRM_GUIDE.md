# 🛠️ Aegis SysPrm Guide
## AI-Assisted Project Configuration

A `.sysprm` file is the "brain" of an Aegis translation project. It provides the LLM with the context, vocabulary, and rules needed to produce high-quality subtitles for a specific show or movie.

---

### 1. Using the Prompt Generator Utility (Recommended)
Instead of writing complex prompts by hand, use the built-in **Prompt Generator** tool:

1.  **Launch**: Click the **🪄** button next to the SysPrm dropdown in the main Aegis window (or run `prompt_generator.pyw` directly).
![Prompt Generator](screenshots/prompt_generator.png)
2.  **Metadata**: Fill in the **Show / Movie Name**. 
    > [!TIP]
    > **Accuracy is critical.** Include the full name, the specific **Season**, and the **Year of Release** (e.g., *"Survivor Season 46 (2024)"* or *"The Hotel New Hampshire (1984 film)"*). This helps the AI research the correct cast and plot.
3.  **Configure**: Select your **Source/Target languages** and decide if you want **Native Instructions**.
4.  **Remarks**: Add any specific names, slang, or style rules.
5.  **Generate**: Click **"Copy Prompt to Clipboard"**.
6.  **AI Query**: Paste the result into any high-reasoning LLM (Gemini 1.5 Pro, GPT-4o, Claude 3.5).
7.  **Drafting**: Click **"📝 Draft .sysprm in Notepad"** in the generator. This creates the correctly named file in the `sysprm files/` folder and opens it for you.
8.  **Save**: Paste the JSON from the AI into the open Notepad window, **save (Ctrl+S)**, and close it.
9.  **Edit**: If required, fine-tune the file manually. Refer to high-quality examples like *survivor_46* for the professional standard.

---

### 2. Implementation in Aegis
Once you have created your `.sysprm` file:

1.  **Move to Folder**: Place the file in the `sysprm files/` directory within the Aegis project folder.
2.  **Launch Aegis**: Open `translator_ai.pyw`.
3.  **Select Languages**: Choose the Source and Target languages matching your project.
4.  **Pick Profile**: Click the **"SysPrm Profile"** dropdown menu and select your new file.
5.  **Start**: Click **🚀 Start Translation**.

---

### 3. Manual Editing & Fine-Tuning
You can open any `.sysprm` file in a text editor (Notepad, VS Code) to make manual adjustments:

*   **Adding Characters**: Add new names to the `illegal_labels` array to ensure the auditor strips them from the subtitles.
*   **Updating Dictionary**: Find the `series_context` section and add new terms using the `- "Source" -> "Target"` format.
*   **Changing Genders**: If a character was incorrectly identified by the AI, update their gender note in the `series_context` to ensure the LLM conjugates verbs correctly.

---

### 4. Troubleshooting (The "Anti-Hallucination" Logic)
If you provide an obscure or private show name, the AI is instructed **not to guess**. 

**If the AI responds with questions instead of a JSON file:**
Don't worry! This is a safety feature. Simply answer the AI's questions by providing a brief plot summary and a list of characters/genders. The AI will then use your provided facts to build a perfect configuration file in its next response.

---

### 5. File Requirements (Technical)
- **Format**: Strictly JSON.
- **Extension**: `.sysprm`
- **Location**: `sysprm files/`
- **Mandatory**: Must contain a `language` block with `source`, `target`, and `use_native_instructions`.

---

### 6. Examples
Refer to these files in your `sysprm files/` folder for live templates:
- `survivor_46_english_2_hebrew_ni.sysprm` (Native Instruction example)
- `survivor_46_english_2_hebrew.sysprm` (English Instruction example)
- `the_amazing_race_38_english_2_hebrew_ni.sysprm` (Large franchise example)
