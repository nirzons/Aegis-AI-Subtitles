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
-   **Google Gemini**: Specialized handling for Flash/Pro models.
-   **DeepSeek**: Optimized for DeepSeek-V3/R1 with caching support.
-   **OpenAI (GPT-4o/o1)**: Implements the `developer` role to isolate instructions from subtitles, ensuring high cache hit ratios and stable reasoning.
- **Local LLMs**: Standardized OpenAI-compatible interface for LM Studio with **API-level Strict Mode** (JSON Schema enforcement).

### 4. Heuristic & AI Auditing (`text_processing.py` & `llm_api.py`)
A multi-tier validation system:
- **Heuristic Shield**: A pre-processing layer that identifies potential technical pitfalls (SDH descriptions, speaker names, mismatched tags). It dynamically switches between **word-density** (Latin) and **character-density** (CJK) auditing based on the active language profile.
- **Localized AI Judge**: A semantic auditor checking for nuanced errors like omissions and tags. It reasoning space is structurally decoupled from English anchors, using the target language's native logic to prevent language leakage.
- **Parser Safety (Italic Passthrough)**: A robust pre-processor that identifies subtitles entirely wrapped in italics, preserving formatting while allowing the LLM to focus on translation.

### 5. Settings & Config (`settings.py`, `language_profiles.py`, `constants.py`)
- **Language Profile Registry**: Centralized database of linguistic rules for every supported language.
- **Dynamic Pricing**: Manages persistent state across sessions with real-time token tracking and **Cache Discount** calculation.

### 6. Web Monitoring Architecture (`web_server.py`, `shared_state.py`, `web/`)
A high-fidelity, read-only monitoring layer built on **FastAPI** and **WebSockets**, with a **Tailwind CSS V3 Command Center** frontend.
- **Thread-Safe Reflection**: A `SharedState` singleton bridges the translation engine thread and the web server without blocking either. Changes increment a monotonic version counter; the WS server pushes a new snapshot only when the version changes.
- **V3 Telemetry Hooks**: The engine calls `update_telemetry()` (tokens/sec, cache hit %) and `update_audit()` (batch size, batch trend, cause label) at key pipeline moments, feeding the live topbar. The system has been hardened to use "Batch Size" exclusively, eliminating redundant "Stride/Windowing" terminology to improve diagnostic clarity.
- **Cause Labelling**: Every batch attempt updates the dashboard's "Cause" field — fresh batches show `✦ Fresh Batch`, while failures inject the specific reason (`Auditor: Failed & Retry`, `⚠️ Parse Error: Retry`, etc.) so the current retry is always self-explanatory.
- **Batch Size Arrow**: The JS frontend tracks actual batch size changes client-side (mirroring Tkinter's `lbl_status` arrow logic) and persists the ↑/↓ indicator until the next genuine size change.
- **Responsive Layout**: Desktop browsers show Terminal Logs and Live Intercept Feed side-by-side (`md:flex-row`); mobile stacks them vertically. All telemetry remains visible on both form factors.

### 7. Engine Performance & Resource Optimization
To support high-frequency, CPU-intensive substring matching across thousands of segments:
- **Pre-Compiled Regex Maps**: All deterministic patterns (e.g., RTL escape markers, SDH filters, string sanitation loops) are pre-compiled as module-level constants.
- **Micro-Delegation**: The monolithic `run_translation` mainloop delegates heavy processing (e.g., recursive JSON structure recovery during hallucinations, discount token computation) to private class helper methods (`_recover_schema`, `_calculate_costs`), dramatically reducing variable allocation overhead and improving trace readability.

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
The AI Judge broadcasts its internal chunking state. For large batches, the UI displays granular progress (e.g., `Judging 1/3...`) as the auditor traverses the batch, ensuring the user knows the application is active after the main model has returned. Detailed log signatures and their visibility modes (Regular vs. Debug) are documented in the **[Logging Audit](logging_audit.md)**.

---

## 💾 Data & Persistence
-   **Checkpoints (`.checkpoints/`)**: Every successful batch is saved to a JSON checkpoint, allowing the user to resume instantly.
-   **System Prompts (`sysprm files/`)**: Project-specific knowledge bases. Aegis now enforces a **Strict JSON Format** for all `.sysprm` files. See the **[Aegis SysPrm Guide](docs/SYSPRM_GUIDE.md)** for setup instructions.
-   **Mandatory Field**: All `.sysprm` files must contain a `language` block with the `use_native_instructions` flag to explicitly define the model's metalanguage.

---

## 🚀 Optimized Workflow for Reasoning Models
Unlike standard translators, Aegis is optimized for the **GPT-5/o1 era**:
-   **Pre-primed Context**: Injects a root-level `summary` immediately before the translation task to "warm up" the model's self-attention to the current plot.
-   **Structure-Aware Headers**: Dynamic prompt synchronization ensures instructions match the flattened root-level JSON keys perfectly.
-   **Cost-Aware Logging**: Specifically tracks "Cache Hits" to provide accurate daily quota monitoring (especially useful for programs like *Data for Credits*).
