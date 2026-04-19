# Aegis AI Subtitles: System Overview

## 🏗️ Architecture Summary
Aegis AI Subtitles is a modular Python-based translation platform that prioritizes **Determinism** and **Resilience**. It is designed to handle the "unpredictability" of LLM outputs through a strict validation pipeline.

---

## 🛠️ Component Breakdown

### 1. Main Dashboard (`translator_ai.pyw`)
The central hub of the application. It manages the threading between the GUI (Tkinter), the Translation Engine, and the Live Viewer. It features:
-   **Terminal Control**: Real-time logging with clipboard support.
-   **Session Orchestration**: Management of checkpoints and resumes.

### 2. Translation Engine (`translation_engine.py`)
The "Brain" of the operation. It manages the batching logic, state persistence (context), and the **Schema Recovery** layer. 
-   **Resilience**: Employs a **Flattened Sandwich Schema** (`Thought` -> `Summary` -> `Work` -> `Metadata`) that prioritizes core translation while keeping story context fresh in the KV cache.
-   **Continuity**: Maintains a rolling buffer of English/Hebrew history, bridging sentence breaks programmatically without burdening the model.

### 3. API & Communication (`llm_api.py`)
A unified abstraction layer for multiple providers:
-   **Google Gemini**: Specialized handling for Flash models.
-   **DeepSeek**: Optimized for DeepSeek-V3/R1 with caching support.
-   **OpenAI (GPT-5/o1)**: Implements the `developer` role to isolate instructions from subtitles, ensuring high cache hit ratios and stable reasoning.
- **Local LLMs**: Standardized OpenAI-compatible interface for LM Studio with **API-level Strict Mode** (response_format) enabled. The engine programmatically synchronizes the `properties` and `required` arrays, applying automatic deduplication (`list(dict.fromkeys())`) to ensure schema compliance and prevent `400 Bad Request` errors caused by overlapping keys.

### 4. Heuristic & AI Auditing (`text_processing.py`)
A two-tier validation system:
1.  **Heuristic Auditor**: Checks for strict length limits (9 words/14 words), English leakage, and illegal speaker names. It uses **Hyper-Specific Extraction** to identify exactly which words or labels caused the failure, injecting these specifics back into the retry prompt to break model stubbornness.
2.  **AI Judge**: A high-reasoning semantic auditor that checks for nuanced errors like omissions, gender-flips (when pronouns are present), and naturalness.

### 5. Settings & Config (`settings.py` & `constants.py`)
Manages persistent state across sessions. Supports dynamic model pricing and **Cache Discount** calculation, allowing the system to accurately track costs even as API providers change their pricing structures.

### 6. Web Monitoring Architecture (`web_server.py`, `shared_state.py`, `web/`)
A high-fidelity, read-only monitoring layer built on **FastAPI** and **WebSockets**, with a **Tailwind CSS V3 Command Center** frontend.
- **Thread-Safe Reflection**: A `SharedState` singleton bridges the translation engine thread and the web server without blocking either. Changes increment a monotonic version counter; the WS server pushes a new snapshot only when the version changes.
- **V3 Telemetry Hooks**: The engine calls `update_telemetry()` (tokens/sec, cache hit %) and `update_audit()` (batch size, batch trend, cause label) at key pipeline moments, feeding the live topbar.
- **Cause Labelling**: Every batch attempt updates the dashboard's "Cause" field — fresh batches show `✦ Fresh Batch`, while failures inject the specific reason (`Auditor: Failed & Retry`, `⚠️ Parse Error: Retry`, etc.) so the current retry is always self-explanatory.
- **Batch Size Arrow**: The JS frontend tracks actual batch size changes client-side (mirroring Tkinter's `lbl_status` arrow logic) and persists the ↑/↓ indicator until the next genuine size change.
- **Responsive Layout**: Desktop browsers show Terminal Logs and Live Intercept Feed side-by-side (`md:flex-row`); mobile stacks them vertically. All telemetry remains visible on both form factors.

---

## 🚀 Diagnostics & Flight Control
Aegis features a real-time dashboard that provides predictive insights into model behavior:

### 1. Linear Regression Estimation
The system utilizes a Least-Squares Regression model (`Time = b + a * size`) to predict batch end-times:
- **`b` (Fixed Overhead)**: Accounts for network latency, prompt processing, and KV cache warm-up.
- **`a` (Variable Rate)**: Calculates the exact seconds-per-line for the current model.
- **Dynamic Fallbacks**: Automatically reverts to simple averages if the batch size remains constant (preventing zero-denominator errors).

### 2. Dual-Track Analytics
Performance data is split into **New** and **Retry** datasets. Since retries involve complex error-correction logic and longer prompt feedback, they are modeled separately to ensure accurate countdowns during difficult segments.

### 3. Auditing Visibility
The AI Judge broadcasts its internal chunking state. For large batches, the UI displays granular progress (e.g., `Judging 1/3...`) as the auditor traverses the batch, ensuring the user knows the application is active after the main model has returned.

---

## 💾 Data & Persistence
-   **Checkpoints (`.checkpoints/`)**: Every successful batch is saved to a JSON checkpoint, allowing the user to resume an interrupted project instantly.
-   **Translations (`translated subtitles/`)**: Finalized `.srt` output files.
-   **System Prompts (`sysprm files/`)**: Project-specific knowledge bases. Supports seamless custom section sizes by utilizing a dynamic indexing engine to maintain sequence structure. This engine is now used to enforce **Strict Zero-English Policies** and "No-Z" rules by bridging global workflow instructions with project-specific variables.

---

## 🚀 Optimized Workflow for Reasoning Models
Unlike standard translators, Aegis is optimized for the **GPT-5/o1 era**:
-   **Pre-primed Context**: Injects a root-level `summary` immediately before the translation task to "warm up" the model's self-attention to the current plot.
-   **Structure-Aware Headers**: Dynamic prompt synchronization ensures instructions match the flattened root-level JSON keys perfectly.
-   **Cost-Aware Logging**: Specifically tracks "Cache Hits" to provide accurate daily quota monitoring (especially useful for programs like *Data for Credits*).
