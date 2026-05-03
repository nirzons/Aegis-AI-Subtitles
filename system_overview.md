# Aegis AI Subtitles: System Overview

## 🏗️ Architecture Summary
Aegis AI Subtitles is a high-performance, modular Python-based translation platform that prioritizes **Determinism** and **Resilience**. It is designed to handle the "unpredictability" of LLM outputs through a strict validation pipeline. Following recent modular refactoring, the codebase is organized into clean functional domains for scalability and maximum maintainability.

---

## 🛠️ Component Breakdown

### 1. Application Entry Point (`translator_ai.pyw`)
The central hub and GUI entry point. It initializes the `TranslatorApp`, which orchestrates the life cycle of the application, including:
- **Style Management**: Applies high-contrast modern themes to the UI.
- **Process Queuing**: Bridges asynchronous engine logs and UI updates.
- **Web Server Binding**: Optionally launches the Web Dashboard (V3 Command Center).

### 2. User Interface Controller (`ui/ui_controller.py`)
Decoupled event controller extracting menu handlers, single-callback events, and the background translation loop.
- **Menu Actions**: Manages the life cycle of external Tkinter windows (e.g. Checkpoints, Settings).
- **Callback Routing**: Attaches event callbacks (combobox selections, debug modes, start/stop logic) cleanly.
- **State Restoration**: Restores UI fields accurately upon resuming checkpoint files.

### 3. Core Logic (`core/`)
The engine room of Aegis, containing the primary translation and auditing logic.
- **`translation_engine.py`**: A clean facade forwarding execution directly to the extracted pipeline.
- **`core/translation/` package**: Isolated single-responsibility submodules containing core execution stages:
  - **`pipeline.py`**: Manages the main translation orchestration loop, batching, and async threads.
  - **`context_resolver.py`**: Handles preliminary file extraction, SysPrm overrides, word-ratio calculations, and initial context resolution.
  - **`response_processor.py`**: Normalizes model outputs via JSON pre-repairs, schema recovery fallbacks, and italic/line-alignment tags passthrough.
  - **`cost_calculator.py`**: Calculates token financial costs and model caching percentages.
  - **`schema_recovery.py`**: Reconstructs outputs when LLMs hallucinate JSON keys.
  - **`prompt_builder.py`**: Aggregates metadata, character context, and past dialogues into prompts.
  - **`text_cleaner.py`**: Preprocesses inputs, stripping inline italic formats and screen alignment tags.
- **`audit_manager.py`**: Orchestrates the multi-tier validation pipeline, including heuristic checks and coordination with the AI Judge.
- **`llm_api.py`**: A unified abstraction layer for multiple providers (Gemini, OpenAI, DeepSeek, and local LM Studio) with support for structured outputs and reasoning tokens.
- **`text_processing.py`**: Handles low-level text manipulations, RTL fixes, JSON pre-repair, and heuristic "Shield" checks.
- **`language_profiles.py`**: A registry of linguistic rules, Unicode ranges, and ratio calibrations for every supported language.
- **`session_manager.py`**: Manages checkpoint serialization, path resolution, and state restoration during resumes.
- **`translation_stats.py`**: Tracks telemetry, token counts, costs, and performance metrics across sessions.
- **`constants.py`**: Holds system-wide constants, prompt templates, and technical rule definitions.

### 4. User Interface (`ui/`)
- **`ui_layout.py`**: Defines the main dashboard's visual structure and widget organization.
- **`gui_windows.py`**: Contains secondary windows like the **Live Viewer**, **Settings**, and **Checkpoint Manager**.

### 5. Infrastructure & Utilities (`utils/`)
Shared services used across the platform.
- **`shared_state.py`**: A thread-safe singleton that mirrors the engine's state for the Web Dashboard.
- **`settings.py`**: Handles persistent application configuration and API key management.
- **`srt_manager.py`**: Specialized logic for parsing, stripping, and validating SRT files.
- **`app_utils.py`**: General purpose helpers for logging, formatting, and time estimation.

### 6. Services & Web (`services/`, `web/`)
Powers the remote monitoring capabilities.
- **`services/web_server.py`**: A FastAPI/Uvicorn server providing the WebSocket API for real-time telemetry.
- **`web/`**: Contains the **V3 Command Center** frontend (Tailwind CSS, JavaScript), delivering high-fidelity performance tracking to any device on the network.

---

## 🛡️ The Validation Pipeline
Aegis features a "Shield" architecture designed to catch hallucinations before they reach the final output:
1. **Heuristic Shield**: A deterministic scanner in `core/text_processing.py` that checks for line lengths, technical tags, and source-language leakage.
2. **Parser Safety**: Pre-processes subtitles to identify complex formatting (like italics) and wraps them safely to prevent model corruption.
3. **AI Judge**: A second, independent LLM call (orchestrated by `core/audit_manager.py`) that semantically verifies the translation against the source, checking for omissions or tonal shifts.
4. **Schema Recovery**: An automated layer that identifies and fixes common LLM JSON formatting errors (hallucinated keys, flat-root outputs).

---

## 💾 Data & Persistence
- **Checkpoints (`.checkpoints/`)**: Every successful batch is saved to a JSON checkpoint by `core/session_manager.py`.
- **System Prompts (`sysprm files/`)**: Project-specific knowledge bases in strict JSON format.
- **Logs (`logs/`)**: Session-specific logs and bypass reports for post-session review.
