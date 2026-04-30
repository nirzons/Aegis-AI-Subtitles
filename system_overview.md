1: # Aegis AI Subtitles: System Overview
2: 
3: ## 🏗️ Architecture Summary
4: Aegis AI Subtitles is a modular Python-based translation platform that prioritizes **Determinism** and **Resilience**. It is designed to handle the "unpredictability" of LLM outputs through a strict validation pipeline. Following a major modular refactor, the codebase is organized into functional domains to ensure scalability and maintainability.
5: 
6: ---
7: 
8: ## 🛠️ Component Breakdown
9: 
10: ### 1. Application Entry Point (`translator_ai.pyw`)
11: The central hub and GUI entry point. It initializes the `TranslatorApp`, which orchestrates the life cycle of the application, including:
12: - **GUI Management**: Links the Tkinter interface to the underlying engine.
13: - **Process Queuing**: Bridges asynchronous engine logs and UI updates.
14: - **Web Server Binding**: Optionally launches the V3 Command Center.
15: 
16: ### 2. Core Logic (`core/`)
17: The engine room of Aegis, containing the primary translation and auditing logic.
18: - **`translation_engine.py`**: Manages the main translation loop, batching, and schema recovery logic. It employs a **Flattened Sandwich Schema** (`Thought` -> `Summary` -> `Work` -> `Metadata`) for optimal KV cache usage.
19: - **`audit_manager.py`**: Orchestrates the multi-tier validation pipeline, including heuristic checks and coordination with the AI Judge.
20: - **`llm_api.py`**: A unified abstraction layer for multiple providers (Gemini, OpenAI, DeepSeek, and local LM Studio) with support for structured outputs and reasoning tokens.
21: - **`text_processing.py`**: Handles low-level text manipulations, RTL fixes, JSON pre-repair, and heuristic "Shield" checks.
22: - **`language_profiles.py`**: A centralized registry of linguistic rules, Unicode ranges, and ratio calibrations for every supported language.
23: - **`session_manager.py`**: Manages checkpoint serialization, path resolution, and state restoration during resumes.
24: - **`translation_stats.py`**: Tracks telemetry, token counts, costs, and performance metrics across sessions.
25: - **`constants.py`**: Holds system-wide constants, prompt templates, and technical rule definitions.
26: 
27: ### 3. User Interface (`ui/`)
28: Decoupled GUI components for a cleaner application structure.
29: - **`ui_layout.py`**: Defines the main dashboard's visual structure and widget organization.
30: - **`gui_windows.py`**: Contains secondary windows like the **Live Viewer**, **Settings**, and **Checkpoint Manager**.
31: 
32: ### 4. Infrastructure & Utilities (`utils/`)
33: Shared services used across the platform.
34: - **`shared_state.py`**: A thread-safe singleton that mirrors the engine's state for the Web Dashboard.
35: - **`settings.py`**: Handles persistent application configuration and API key management.
36: - **`srt_manager.py`**: Specialized logic for parsing, stripping, and validating SRT files.
37: - **`app_utils.py`**: General purpose helpers for logging, formatting, and time estimation.
38: 
39: ### 5. Services & Web (`services/`, `web/`)
40: Powers the remote monitoring capabilities.
41: - **`services/web_server.py`**: A FastAPI/Uvicorn server providing the WebSocket API for real-time telemetry.
42: - **`web/`**: Contains the **V3 Command Center** frontend (Tailwind CSS, JavaScript), delivering high-fidelity performance tracking to any device on the network.
43: 
44: ---
45: 
46: ## 🛡️ The Validation Pipeline
47: Aegis features a "Shield" architecture designed to catch hallucinations before they reach the final output:
48: 1. **Heuristic Shield**: A deterministic scanner in `core/text_processing.py` that checks for line lengths, technical tags, and source-language leakage.
49: 2. **Parser Safety**: Pre-processes subtitles to identify complex formatting (like italics) and wraps them safely to prevent model corruption.
50: 3. **AI Judge**: A second, independent LLM call (orchestrated by `core/audit_manager.py`) that semantically verifies the translation against the source, checking for omissions or tonal shifts.
51: 4. **Schema Recovery**: An automated layer that identifies and fixes common LLM JSON formatting errors (hallucinated keys, flat-root outputs).
52: 
53: ---
54: 
55: ## 🚀 Diagnostics & Flight Control
56: ### 1. Predictive Estimation
57: The system utilizes a Least-Squares Regression model (`Time = b + a * size`) tracked in `core/translation_stats.py` to predict batch end-times:
58: - **`b` (Fixed Overhead)**: Accounts for network latency and prompt processing.
59: - **`a` (Variable Rate)**: Calculates the seconds-per-line for the current model.
60: 
61: ### 2. Dual-Track Analytics
62: Performance data is split into **New** and **Retry** datasets. Since retries involve complex error-correction logic, they are modeled separately to ensure accurate ETA countdowns during difficult segments.
63: 
64: ### 3. Cause Labelling
65: Every batch attempt updates the dashboard's "Cause" field (via `utils/shared_state.py`). Fresh batches show `✦ Fresh Batch`, while failures inject the specific reason (`Auditor: Failed & Retry`, `⚠️ Parse Error`, etc.) so the current retry is always self-explanatory.
66: 
67: ---
68: 
69: ## 💾 Data & Persistence
70: - **Checkpoints (`.checkpoints/`)**: Every successful batch is saved to a JSON checkpoint by `core/session_manager.py`.
71: - **System Prompts (`sysprm files/`)**: Project-specific knowledge bases in strict JSON format.
72: - **Logs (`logs/`)**: Session-specific logs and bypass reports for post-session review.
73: 
74: ---
75: 
76: ## 🚀 Optimized for Reasoning Models
77: Aegis is built for the **GPT-5/o1 era**:
78: - **Pre-primed Context**: Injects a root-level `summary` to "warm up" the model's self-attention.
79: - **Structure-Aware Headers**: Prompt instructions are dynamically synced to match the JSON keys perfectly.
80: - **Cost-Aware Logging**: Specifically tracks "Cache Hits" and "Reasoning Tokens" for accurate quota monitoring.

