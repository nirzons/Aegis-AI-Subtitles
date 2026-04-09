# 🛡️ Aegis AI Subtitles - System Overview

Advanced system for translating and synchronizing subtitle files (SRT) from English to Hebrew, combining Artificial Intelligence with deterministic control mechanisms to ensure maximum quality.

### Core System Components:
- **LLM Translator Controller**: Manages subtitle translation in context-aware batches (2 preceding and 2 succeeding blocks), along with dynamic state tracking for speaker gender and plot summaries.
- **Heuristic Auditor**: Fast local scanner (Regex-Based) implementing precise control constraints.
    - **Index-Resolved Tagging:** The Auditor tracks and tags specific reasons per index (e.g. `IDX:102|English Letters`).
    - **Extreme Omission/Summarization Check:** A new lower-ratio detection (ratio < 0.4) catches suspicious summarization in segments with 4+ words.
    - **Smart "Silent Skip" Filter:** Short connectors (1-2 words or <12 chars) are allowed to be merged/skipped silently, while longer segments trigger a failure.
    - **Multi-line Speaker Check:** An aggressive regex scan covering every line (including dialogue dashes) detects Hebrew or English speaker names (e.g., `ג'ף:`).
    - **Immediate Retry (Skip Judge):** Square brackets `[ ]`, overlong lines (>9 words per line), and extreme single-block **Verbosification (>2.0x target expansion)** immediately fail the batch for retry.
    - **Judge Flow:** Other rules, or moderate Verbosification (>1.5x expansion), are aggregated and passed dynamically to the Judge.
- **Chunked AI Judge (Structured Feedback)**: Context-Aware AI "Judge" that performs quality audits in chunks (e.g. 20 lines). Invoked when heuristics flag suspicion.
    - **Structured Error Mapping:** The Judge now outputs a JSON `error_map` (index -> reason). It audits the entire chunk to gather all errors rather than stopping at the first failure.
    - **Laser-Focus Instructions:** The Judge receives the specific Auditor tags (e.g., "Speaker name found in 103"), allowing it to focus on resolving exact flags.
- **Surgical Prompt Injection (Hebrew Feedback)**: When a batch fails (via Auditor or Judge), the retry prompt is dynamically injected with a Hebrew header: `### חובה לתקן את השגיאות הבאות לפי אינדקס (אל תחזור על טעויות אלו): ###`. This contains specific, block-level instructions for only the indices present in the current attempt, reducing collateral damage.
- **JSON Pre-Repair & Integrity Engine**: Real-time LLM output validator.
    - **Hebrew Escape "Shield":** Intercepts illegal Hebrew newline escape sequences (like `\נ`) and converts them to standard `\n` (via a double-backslash literal trick) to prevent JSON crashes.
- **Self-Healing Loop**: A **single** failure at a stride (above size 3) triggers a **retry at the same stride**. After a **second** consecutive failure at that stride, size is reduced and retried. After success, **effective batch size** for the rest of the job is the **penultimate stride** in that chunk’s attempt list.

### Infrastructure & Persistence:
- **Hot Resume Workflow**: Allows stopping a translation, tuning parameters (batch sizes, models) in the UI, and resuming from the same point without restarting.
    - **Automatic Session Latching:** UI automatically sorts checkpoints by modification time and auto-selects the latest match for the current SRT.
    - **Batch Override:** Manual UI batch size changes are detected during resume and override the checkpoint's "effective" memory.
- **Interactive Checkpoint Management**: Saves the full session state (models, costs, context, files) in JSON files. Includes a management interface for deleting, cleaning, or resuming work from the exact stopping point.
- **PID Protection**: Protection mechanism that monitors the Process ID of active sessions to prevent data overwrites by multiple translation windows.
- **RTL Punctuation Fixer**: Typographic correction of punctuation order for proper Hebrew display in video players.
- **Cost Optimization**: Precise tracking of costs and full utilization of Prompt Caching for dramatic cost reduction.
- **Intelligent Logging System**: Full diagnostic logging (Prompts and Raw Response) of the main model written to the log file exactly once upon failure.
    - **Persistent Terminal History:** The terminal window (GUI) is no longer wiped during a "Hot Resume"; instead, it inserts a timestamped `🔄 SESSION RESUMED` separator to maintain diagnostic context.

### User Interface (GUI Control Center):
- **Central Dashboard**: Management of the translation process, model selection (Translator and Judge), and real-time viewing of LLM logs.
- **Settings Window**: Multi-tab settings window for managing API keys and personal model configurations.
- **Live Translation Viewer**: Side-by-side view of the source text against the live translation for real-time audit.

### Architecture & Project Structure (Modular Structure):
The codebase splits the **Tkinter GUI**, **translation worker**, **provider APIs**, **prompt/config**, and **text utilities**. All Python modules:

**Application entry & translation pipeline**
- **translator_ai.pyw**: Application entry point. Builds the main window, owns shared queues (`log_queue`, `ui_queue`), wires controls to `MainUILayout`, and runs `TranslationEngine` in a background thread (start/stop, model and file selection, checkpoint resume, cost display updates).
- **translation_engine.py**: Core batch loop: assembles context windows, calls the main LLM, runs `pre_repair_json`, `check_heuristics`, optional `call_llm_judge`. Implements **Surgical Prompt Injection** by parsing index-resolved error maps (Auditor tags or Judge JSON) into targeted retry instructions. Updates checkpoints (including `effective_batch_size`) and `context_state`.

**Main-window UI vs. secondary windows**
- **ui_layout.py**: `MainUILayout` — lays out the primary dashboard (model/batch/SRT controls, start/stop, log area, cost line) and binds widgets to the app instance.
- **gui_windows.py**: Toplevel dialogs — `LiveViewer` (side-by-side English/Hebrew tree), `SettingsWindow` (API keys and model catalog), `CheckpointsWindow` (session JSON management, PID checks via `is_process_alive`).

**Configuration & prompts**
- **settings.py**: `SettingsManager` loads/saves `translator_settings.json` (API keys, per-model options such as provider, batch size, temperature, pricing); exposes module-level `SETTINGS` for the rest of the app.
- **constants.py**: Global translator instructions (`GLOBAL_SYSTEM_INSTRUCTIONS`, `GLOBAL_TECHNICAL_RULES`) and the expected JSON shape (`JSON_SCHEMA_TEMPLATE` / schema text) consumed when building LLM system prompts.

**APIs & shared helpers**
- **llm_api.py**: Provider abstraction — `call_llm` and `call_llm_judge` for Google (Gemini), OpenAI-compatible (OpenAI, DeepSeek), and local (LM Studio); `call_llm_judge` injects per-chunk EN/HE overlap and expanded audit rules; token/cached-token reporting for cost; `is_process_alive` for cross-platform PID checks.
- **app_utils.py**: Cross-cutting helpers — `log` / `file_log` (GUI queue + session file), `format_cost_display` (main vs. judge), `get_eta_string`, `strip_srt` (context text without indices/timestamps), `load_srt_index_to_text` (reload translated cues on resume for judge overlap).

**Text processing**
- **text_processing.py**: `fix_rtl` (Hebrew subtitle punctuation/layout), `pre_repair_json` (markdown fences, trailing commas, control chars before parse), and `check_heuristics` (local auditor + `skip_judge` signals for the engine).

### Project Configuration - The .sysprm Format
The `.sysprm` file is the brain of your translation project. It allows you to define character genders, glossaries, and narrative context. The file follows a strict "Dual-Block" architecture:

#### 1. Comments (`//`)
Any line starting with `//` is ignored by the engine. Use this for notes or disabling rules temporarily.

#### 2. The JSON Header (Initial State)
The top of the file (before the `===` separator) is a JSON block that initializes the translation's memory.
```json
{
  "summary": "Plot summary of the previous episode.",
  "last_speaker": "Jeff (M)",
  "speakers_gender": {"Dee": "F", "Austin": "M"}
}
```
*Note: If you don't need an initial state, you can start the file directly with `===`.*

#### 3. The Separator (`===`)
A mandatory line consisting of three equals signs separates the initial state from the project instructions.

#### 4. The Instruction Block (Markdown)
The rest of the file is standard Markdown. This is where you define:
- **Gender Rules**: Instructions on which characters are male/female to ensure correct Hebrew conjugation.
- **Glossary**: Specific terms (e.g., "Immunity Idol" -> "פסלון חסינות").
- **Stylistic Rules**: Tone of voice, character quirks, or show-specific jargon.

---

### Workflow:
1. Loading the SRT file and project instructions (`SysPrm`).
2. Sending a batch for translation (LLM) along with relevant Context.
3. Repairing and cleaning the raw output (`Pre-Repair JSON`), including shielding against illegal escape sequences.
4. Forensic Scanning (**Heuristic Auditor**) to identify specific index-mapped errors.
5. **Conflict Resolution**:
    - **Immediate Retry**: If the issue is a hard-rule violation (SDH tags, over-long lines, or extreme verbosity).
    - **Chunked Judge**: If the issue requires semantic evaluation, the Judge is called and returns a structured JSON error map.
6. **Surgical Feedback Loop**: Valid translations are saved, while failing indices are sent for retry with **Targeted Hebrew Instructions** injected into the prompt.
7. Writing the final result after `RTL` correction and updating the local Checkpoint.

**Technologies:** Python 3.x, Tkinter GUI, Regular Expressions, REST APIs, JSON State Management.
