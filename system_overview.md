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
-   **Resilience**: Detects when models hallucinate JSON keys or provide flat structures and automatically "salvages" the translation data.
-   **Continuity**: Maintains a rolling buffer of English/Hebrew history.

### 3. API & Communication (`llm_api.py`)
A unified abstraction layer for multiple providers:
-   **Google Gemini**: Specialized handling for Flash models.
-   **DeepSeek**: Optimized for DeepSeek-V3/R1 with caching support.
-   **OpenAI (GPT-5/o1)**: Implements the `developer` role to isolate instructions from subtitles, ensuring high cache hit ratios and stable reasoning.
-   **Local LLMs**: Standardized OpenAI-compatible interface for LM Studio.

### 4. Heuristic & AI Auditing (`text_processing.py`)
A two-tier validation system:
1.  **Heuristic Auditor**: Checks for strict length limits (9 words/14 words), English leakage, and illegal speaker names (e.g., `EMILY:`).
2.  **AI Judge**: A high-reasoning semantic auditor that checks for nuanced errors like omissions, gender-flips (when pronouns are present), and naturalness.

### 5. Settings & Config (`settings.py` & `constants.py`)
Manages persistent state across sessions. Supports dynamic model pricing and **Cache Discount** calculation, allowing the system to accurately track costs even as API providers change their pricing structures.

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
-   **System Prompts (`sysprm files/`)**: Project-specific knowledge bases. Supports seamless custom section sizes by utilizing a dynamic indexing engine (automatically scaling global workflow rules 1,2,3... exactly where your specific variables end) to maintain sequence structure for LLMs.

---

## 🚀 Optimized Workflow for Reasoning Models
Unlike standard translators, Aegis is optimized for the **GPT-5/o1 era**:
-   **Pre-repair JSON**: Automatically cleans common LLM output mistakes (markdown blocks, escaped newlines).
-   **Merged Prompt Context**: Ensures reasoning models see the "Full Story" in exactly the format they prefer for deep thinking.
-   **Cost-Aware Logging**: Specifically tracks "Cache Hits" to provide accurate daily quota monitoring (especially useful for programs like *Data for Credits*).
