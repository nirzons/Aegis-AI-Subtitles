# Aegis Logging System Audit

This document provides a comprehensive overview of all log signatures currently implemented in the Aegis Translation Engine. Use this table to identify logs that should be modified, silenced, or moved between modes.

## Logging Categories

| Purpose / Event | Log Source | Visibility | Example / Snippet |
| :--- | :--- | :--- | :--- |
| **Session Tracking** | `translation_engine.py` | **Regular** | `✅ Resuming session: [SRT_FILE] from block [INDEX]` |
| **Checkpointing** | `translation_engine.py` | **Regular** | `📁 Using Checkpoint File: [FILE_PATH]` |
| **Init Status** | `translation_engine.py` | **Regular** | `✅ Loaded project-specific context from sysprm.` |
| **Mode Indicator** | `translation_engine.py` | **Regular** | `🚀 [Mode: Efficiency (Direct)] Starting translation with [MODEL]...` |
| **Forensic Scout (Summary)** | `translation_engine.py` | **Regular** | `🔍 Forensic Scout: Targets flagged at indices ['245', '248'].` |
| **Forensic Scout (Detail)** | `translation_engine.py` | **Debug** | `🔍 Forensic Scout: Detailed analysis for indices ['245'].`<br>`   ↳ אינדקס 245: חשד לתיאור צליל/SDH ([music]).` |
| **Italic Passthrough** | `translation_engine.py` | **Debug** | `✨ [Italic Passthrough] Stripped outer italics for indices: 248, 249` |
| **Italic Restoration** | `translation_engine.py` | **Debug** | `✨ [Italic Passthrough] Restored global italics for indices: 248` |
| **Batch Lifecycle** | `translation_engine.py` | **Regular** | `⏳ Sending Batch (Indices: 245-246 | Batch Size: 2)...` |
| **Cost & Token Tracking** | `translation_engine.py` | **Regular** | `💰 [Main Model] Batch: $0.00450 (In: 1,200 [Hit: 800 (66%)] / Out: 250) | Total: $1.25` |
| **LLM Transaction (Full)** | `translation_engine.py` | **Debug** | `--- DEBUG TRANSACTION ---`<br>`SYSTEM PROMPT: ...`<br>`USER PROMPT: ...`<br>`RAW LLM RESPONSE: { "translated_srt": { ... } }` |
| **Schema Recovery** | `translation_engine.py` | **Regular** | `   ↳ 💡 Recovered schema from hallucinated key: 'translation'` |
| **Sanitizer (Ghost Fix)** | `translation_engine.py` | **Regular** | `🧹 [Sanitizer] Removed English ghost fragments in indices: 246` |
| **Sanitizer (Format Fix)** | `translation_engine.py` | **Regular** | `🧹 [Sanitizer] Fixed escaped line breaks or formatting in indices: 250` |
| **Auditor Warning** | `translation_engine.py` | **Regular** | `⚠️ AUDITOR WARNING: The LLM responded with identical placeholder text!` |
| **Judge Process** | `llm_api.py` | **Regular** | `   ↳ ⏳ Judge Chunk 1/1 [245–246]: sending...` |
| **Judge Result (Pass)** | `llm_api.py` | **Regular** | `   ↳ ✅ Judge Chunk 1: PASSED (In: 1,150 | Out: 248)` |
| **Judge Result (Reject)** | `llm_api.py` | **Regular** | `   ↳ ❌ Judge Chunk 1: REJECTED (In: 1,150 | Out: 248)` |
| **Judge Result (Detail)** | `llm_api.py` | **Debug** | `   ↳ ❌ Judge Chunk 1: REJECTED (In: 1,150 | Out: 248) — 246: חוסר התאמה בתגיות...` |
| **Judge Stats** | `translation_engine.py` | **Regular** | `⚖️ [Judge Model] Batch: $0.00120 \| Total Judge: $0.45` |
| **Job Completion** | `translation_engine.py` | **Regular** | `✅ Job Completed in 14m 22s.` |

## Notes on Optimization

> [!TIP]
> **Silencing the Sanitizer**: If the "English Ghost" bug is rare, we could move those `🧹 [Sanitizer]` logs to Debug mode to keep the terminal focused on translation success.

> [!IMPORTANT]
> **Diagnostic File Logs**: Even in **Regular Mode**, some logs only appear in the physical `.txt` file on disk to prevent terminal clutter (e.g., the very long `--- JUDGE CHUNK SYSTEM PROMPT ---` blocks in `llm_api.py`).

---
*Last updated: 2026-04-22*
