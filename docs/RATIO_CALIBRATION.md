# 📊 Aegis Ratio Calibration Guide
## Understanding and Tuning Translation Density

Aegis uses a "Heuristic Shield" to detect common LLM failures like **text omission** or **hallucinated verbosity**. This is done by comparing the length of the translation to the length of the source.

---

### 1. The Ratio System
The engine tracks two main types of ratios:
1.  **Block Ratio**: The length ratio of a single subtitle cue.
2.  **Batch Ratio**: The aggregate ratio of the entire batch (usually 20-30 cues).

#### How it works:
If you are translating English to Hebrew, a typical ratio is **0.75** (Hebrew uses fewer words to convey the same meaning). 
- If a block has a ratio of **3.0**, it means the translation is 3x longer than the source. This triggers a "High Expansion" warning or rejection.
- If a block has a ratio of **0.2**, it means the translation is 80% shorter than the source. This triggers an "Omission" warning.

---

### 2. Standard Language Pair Ratios
Aegis comes with built-in default ratios for common language pairs.

| Pair | Typical Ratio | Note |
|---|---|---|
| EN → HE | 0.75 | Semitic morphology compresses word count. |
| EN → ZH | 0.50 (chars) | Character-based (CJK) counting. |
| EN → FR | 1.15 | Romance languages are often more verbose. |
| EN → ES | 1.20 | Similar to French. |

---

### 3. Tuning for Your Project
Different genres have different densities. A fast-paced reality show (like *Survivor*) has higher density than a slow period drama.

You can override the global defaults in your `.sysprm` file:

```json
"language": {
  "min_block_ratio": 0.35,
  "max_block_ratio": 3.0,
  "batch_min_ratio": 0.40,
  "batch_max_ratio": 1.30
}
```

#### When to tune:
- **Too many "Omission" Interventions**: If the engine keeps stopping because the translation is "too short," but the text is actually correct, lower your `min_block_ratio` (e.g. from 0.35 to 0.30).
- **Too many "High Expansion" Interventions**: If the engine stops for naturally long translations, increase your `max_block_ratio` (e.g. from 3.0 to 3.5).

---

### 4. Telemetry
You can monitor live ratios in two places:
1.  **Session Logs**: Look for the `📊 Word Ratios` entry at the start of a session.
2.  **Web Dashboard**: The "Batch Metrics" panel shows the real-time density of the current batch.
