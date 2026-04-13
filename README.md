# 🛡️ Aegis AI Subtitles
### The Guardian of Subtitle Translation Quality

![Aegis Dashboard](screenshots/dashboard.png)

**Aegis AI Subtitles** is a professional-grade translation engine designed to bridge the gap between English and Hebrew with surgical precision. Unlike standard translators, Aegis employs a multi-layered "Shield" architecture featuring automated auditing and AI-driven quality assurance to ensure every line is natural, accurate, and perfectly formatted.

### 🔍 Interactive Monitoring
With the built-in **Live Viewer**, you can audit the translation process in real-time, comparing the English source directly against the Hebrew output.

![Aegis Live Viewer](screenshots/LiveViwer.png)

---

## 🚀 Key Features

- **🧠 Context-Aware Translation**: Processes subtitles in overlapping batches to maintain narrative continuity and tonal consistency.
- **⚖️ AI Judge System**: A dedicated "Judge" model semantically verifies suspicious translations, detecting hallucinations, omissions, and cultural nuances.
- **🛡️ Forensic Auditor**: A high-speed heuristic scanner that enforces strict SDH removal, RTL formatting, and dynamic speaker name deletion via `.sysprm` config.
- **🩹 Self-Healing & Resilience**: Path-breaking schema inference that recovers translations from hallucinated JSON keys—optimized specifically for high-reasoning models like GPT-5/o1.
- **💰 Cost-Optimized**: Native support for prompt caching (GPT-5, DeepSeek 90% discount) with real-time token tracking and hit-ratio logs.
- **🔄 Hot Resume**: Seamlessly stop, tune parameters (batch sizes, models), and resume without losing session history.
- **🚀 Flight Control Dashboard**: Real-time diagnostic header featuring:
  - **⏱️ Live Response Timers**: Precise `M:SS` tracking for model deliberation.
  - **📈 Linear Regression Estimation**: A "Clever Countdown" that learns from history to predict completion times.
  - **🔄 Dual-Track Analytics**: Separate performance modeling for "New" vs "Retry" batches.
  - **⚖️ Audit Progress**: Live chunk-tracking (e.g., `Judging 1/3...`) during the QA phase.
  - **🔼 Adaptive Scaling**: Visual indicators for automatic batch-size growth or shrinking.
- **📋 Clipboard Integration**: Instantly copy terminal output logs with a single button click in the main dashboard.
- **🖥️ Local Model Support**: "Local" mode optimization for LM Studio and local LLMs, hiding internal magic cost values for a cleaner interface.

---

## 📦 Dependencies

Aegis relies on the following external Python libraries for AI model connectivity:

- **Google Generative AI SDK**: `google-generativeai`
- **OpenAI SDK**: `openai` (used for OpenAI, DeepSeek, and local LM Studio instances)

You can install all dependencies with a single command:
```bash
pip install -r requirements.txt
```

---

## 🛠️ Installation & Usage

### Prerequisites
- Python 3.10+
- A valid API key for OpenAI, DeepSeek, or Google Gemini.

### Quick Start
1. Clone the repository.
2. **Setup Directories**:
   - `English subtitles/`: Place your source `.srt` files here.
   - `sysprm files/`: Place your project instructions here (e.g., `survivor_45_hebrew.sysprm`).
3. **Run Application**:
   ```bash
   python translator_ai.pyw
   ```
4. **Configuration**: Click the **⚙️ Settings** button to enter API keys and manage model parameters directly in the UI.

---

## 📖 Under the Hood

### 1. The Context Layer
Aegis doesn't translate in a vacuum. It maintains a rolling history of the "Story So Far," including character bios, current setting, and immediate preceding dialogue to prevent gender-flips and continuity errors. Furthermore, it employs a **Dynamic Prompt Architecture** that automatically synchronizes project-specific custom `.sysprm` dictionaries with global rules, creating a seamlessly numbered instruction set that maximizes LLM adherence.

### 2. The Heuristic Shield
A deterministic auditor that runs before any AI check. It instantly catches "leaks" (like speaker names `JEFF:`) or lines that are physically too long for subtitle screens, triggering an immediate retry before wasting tokens on an AI Judge.

### 3. Reasoner Optimization
Specialized handling for "Reasoning" models (GPT-5/o1). Aegis utilizes the `developer` role to isolate instructions from content, ensuring **90%+ cache hit ratios** and preventing "Schema Collapse" even when the model goes off-script.
