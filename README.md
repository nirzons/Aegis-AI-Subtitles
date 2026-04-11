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
- **🩹 Self-Healing Engine**: Automatically detects batch failures and dynamically adjusts its stride (batch size) to recover and provide the best result.
- **🔄 Hot Resume**: Seamlessly stop, tune parameters (batch sizes, models), and resume without losing session history.
- **📋 Clipboard Integration**: Instantly copy terminal output logs with a single button click in the main dashboard.
- **💰 Cost-Optimized**: Fully utilizes prompt caching and token tracking for maximum efficiency.

---

## 📦 Dependencies

Aegis relies on the following external Python libraries for AI model connectivity:

- **Google Generative AI SDK**: `google-generativeai`
- **OpenAI SDK**: `openai` (used for OpenAI, DeepSeek, and local LM Studio instances)

You can install all dependencies with a single command:
```bash
pip install -r requirements.txt
```

*Note: All other modules used (os, tkinter, json, etc.) are part of the Python Standard Library, making Aegis highly portable and lightweight.*

---

## 🛠️ Installation & Usage

### Prerequisites
- Python 3.10+
- A valid API key for OpenAI, DeepSeek, or Google Gemini (configured via the UI).

### Quick Start
1. Clone the repository.
2. **Setup Directories**: Ensure you have the following folders in the root (most are created automatically on launch):
   - `English subtitles/`: Place your source `.srt` files here.
   - `sysprm files/`: Place your project instructions here (an example `survivor_45_hebrew.sysprm` is provided).
3. **Run Application**:
   ```bash
   python translator_ai.pyw
   ```
4. **Configuration (First Launch)**: 
   - You don't need to set up Environment Variables! 
   - Click the **⚙️ Settings** button in the dashboard to enter your API keys for OpenAI, DeepSeek, or Google Gemini directly in the UI.
5. **Translate**: Select your `.srt` and `.sysprm` profile from the dashboard and hit **Start Translation**.

---

## 📖 Documentation
For a deep dive into the technical architecture, heuristic rules, and the multi-layer validation loop, see the [System Overview](system_overview.md).

## 📄 License
MIT License - Created with precision for the subtitle translation community.
