# 🛡️ Aegis Senior Editor Proofreading Guide

Welcome to the **Senior Editor Audit System**! This offline proofreading suite is designed for high-stakes localization, serving as your secondary safety net to ensure that subtitle translations meet elite broadcasting standards.

While the live Translation Engine handles layout, timing, and grammar, the **Senior Editor** analyzes your finished subtitle files using heavyweight LLMs to catch **missed cultural idioms, rare vocabulary nuances, and strict glossary term compliance**.

---

## 🧠 Key Architectural Philosophy

### 1. Decoupled Synergy (Non-Blocking)
The Senior Editor operates **offline**, meaning it runs *after* your primary translation is complete. 
- This prevents slowing down your live translation loop.
- It allows you to run your primary translation using an economical, high-speed model (e.g., DeepSeek-V3) and reserve premium flagship models (e.g., GPT-4o) for a hyper-focused secondary proofreading audit.

### 2. The "Hybrid Mastermind" Condenser
Instead of feeding thousands of lines of instructions into every API call, Aegis automatically extracts key Cast Genders and Terms from your project `.sysprm` files. 
- It distills this data into a structured **`.sneprf`** profile saved in the `editor_profiles/` folder.
- This persistent cache shrinks prompt size for all following batches by up to **80%**, drastically reducing costs and execution time.

---

## 🚀 Step-by-Step Operational Guide

### Step 1: Launch the Audit
1. Translate your subtitle file using the primary engine.
2. Select the Source File and the SysPrm profile in the Aegis dashboard.
3. Select the **Heavyweight Auditor Model** from the dropdown (e.g., `gpt-4o` or `deepseek-chat`).
4. Click the **`✨ Audit`** button next to the Stop button.
5. Aegis will automatically scan the output directory, locate your translated file, and launch the background proofreading daemon.

### Step 2: Interactive File Discovery
If you have translated the same file multiple times with different models, a **modal popup** will display. Simply double-click the exact version of the translation you want to proofread.

### Step 3: The Side-by-Side Review Board
Once the audit completes, the **Semantic Review Board** viewport will materialize:
- **Interactive Checkboxes**: Instantly select or deselect which individual corrections you want to apply.
- **Original Context**: View the English original next to the active Hebrew translation.
- **Highlight Mint Overlay**: The proposed replacement is beautifully highlighted for rapid scanning.
- **RTL Optimization**: Supports Right-to-Left text wrapping and alignment designed specifically for Hebrew script.

### Step 3.1: Understanding & Filtering by Confidence Level
Every potential improvement identified by the Senior Editor comes with an **AI Confidence Level** (ranging from `0.00` to `1.00`), signifying the model's level of certainty regarding a translation mismatch:
- **💎 High Confidence ($\ge 0.80$)**: Boldly highlighted in teal. Indicates unambiguous errors such as glossary violations, factual mistranslations, or gender agreement failures.
- **⚖️ Moderate/Low Confidence**: Rendered in slate grey. Typically indicates stylistic enhancements or contextual interpretations which merit manual user verification.

You can utilize the **Confidence Threshold Control Panel** in the toolbar for hyper-efficient reviews:
1. **Adjust the Cutoff**: Drag the **Confidence Threshold Slider** to your desired precision cutoff (e.g., `0.80` for standard broadcast quality).
2. **👁️ Hide Below Threshold**: Instantly hides rows falling below the cutoff from the grid to declutter your viewport. *(Use the **Show All** button to reset visual visibility)*.
3. **☑️ Select Above Threshold**: Bulk-checks all checkboxes that meet your minimum confidence standard while clearing the checkboxes for weaker suggestions, saving you dozens of manual clicks!

### Step 4: The State-Protection Save
Click **`💾 Apply Selected Fixes`**. Aegis protects your data with two crucial safety layers:
1. **The Backup Prompt**: If a backup clone already exists, Aegis asks if you'd like to Overwrite it (Yes), Preserve the original pristine backup intact while saving the new edits (No), or Cancel.
2. **RTL Punctuation Pass**: Aegis automatically re-adjusts raw Hebrew punctuation layouts back to the specific formats required for standard video media players!

---

## 💡 Best Practice & Model Strategies

For the ultimate balance between elite accuracy and operating costs, follow these strategies:

| Workflow Style | Primary Translator | Heavyweight Auditor | Purpose |
| :--- | :--- | :--- | :--- |
| **💰 The Economy Run** | `deepseek-chat` | `deepseek-chat` | High-speed, virtually free QA (< $0.01 per episode). |
| **🚀 The Hybrid Balance** | `deepseek-chat` | `gpt-4o` | Leverages DeepSeek's raw translation speeds, with GPT-4o's elite cultural reasoning for final proofreading. |
| **👑 The Flagship Elite** | `gpt-4o` | `gpt-4o` | Maximum possible precision for critical, high-stakes broadcast releases. |

---

## 📁 Auto-Generated Polish Reports
Alongside the visual GUI, the Senior Editor automatically archives a highly readable Markdown report inside the dedicated reports folder:
`Audit reports/[Filename]_SENIOR_EDITOR_REPORT.md`

This report contains:
- Detailed tables of all identified improvements.
- Explicit explanations from the LLM reasoning core detailing **why** a correction was suggested.
- Detailed financial and token telemetry, including input/output caching statistics.

Enjoy the surgical precision of automated, heavyweight semantic QA! 🏆
