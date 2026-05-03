# Aegis Logging System Audit

This document provides a comprehensive overview of all log signatures currently implemented in the Aegis Translation Engine. Use this table to identify logs that should be modified, silenced, or moved between modes.

## Logging Categories

| Purpose / Event | Log Source | Visibility | Example / Snippet |
| :--- | :--- | :--- | :--- |
| **Session Tracking** | `pipeline.py` | **Regular** | `✅ Resuming session: [SRT_FILE] from block [INDEX]` |
| **Checkpointing** | `pipeline.py` | **Regular** | `📁 Using Checkpoint File: [FILE_PATH]` |
| **Init Status** | `context_resolver.py` | **Regular** | `✅ Loaded project-specific context from sysprm.` |
| **Mode Indicator** | `context_resolver.py` | **Regular** | `🚀 [Mode: Efficiency (Direct)] Starting translation with [MODEL]...` |
| **Forensic Scout (Summary)** | `pipeline.py` | **Regular** | `🔍 Forensic Scout: Targets flagged at indices ['245', '248'].` |
| **Forensic Scout (Detail)** | `pipeline.py` | **Debug** | `🔍 Forensic Scout: Detailed analysis for indices ['245'].`<br>`   ↳ אינדקס 245: חשד לתיאור צליל/SDH ([music]).` |
| **Italic Passthrough** | `response_processor.py` | **Debug** | `✨ [Italic Passthrough] Stripped outer italics for indices: 248, 249` |
| **Italic Restoration** | `response_processor.py` | **Debug** | `✨ [Italic Passthrough] Restored global italics for indices: 248` |
| **Batch Lifecycle** | `pipeline.py` | **Regular** | `⏳ Sending Batch (Indices: 245-246 | Batch Size: 2)...` |
| **Cost & Token Tracking** | `pipeline.py` | **Regular** | `💰 [Main Model] Batch: $0.00450 (In: 1,200 [Hit: 800 (66%)] / Out: 250) | Total: $1.25` |
| **LLM Transaction (Full)** | `pipeline.py` | **Debug** | `--- DEBUG TRANSACTION ---`<br>`SYSTEM PROMPT: ...`<br>`USER PROMPT: ...`<br>`RAW LLM RESPONSE: { "translated_srt": { ... } }` |
| **Schema Recovery** | `schema_recovery.py` | **Regular** | `   ↳ 💡 Recovered schema from hallucinated key: 'translation'` |
| **Sanitizer (Ghost Fix)** | `text_processing.py` | **Regular** | `🧹 [Sanitizer] Removed English ghost fragments in indices: 246` |
| **Sanitizer (Format Fix)** | `text_processing.py` | **Regular** | `🧹 [Sanitizer] Fixed escaped line breaks or formatting in indices: 250` |
| **Auditor Warning** | `response_processor.py` | **Regular** | `⚠️ AUDITOR WARNING: The LLM responded with identical placeholder text!` |
| **Judge Process** | `llm_api.py` | **Regular** | `   ↳ ⏳ Judge Chunk 1/1 [245–246]: sending...` |
| **Judge Result (Pass)** | `llm_api.py` | **Regular** | `   ↳ ✅ Judge Chunk 1: PASSED (In: 1,150 | Out: 248)` |
| **Judge Result (Reject)** | `llm_api.py` | **Regular** | `   ↳ ❌ Judge Chunk 1: REJECTED (In: 1,150 | Out: 248)` |
| **Judge Result (Detail)** | `llm_api.py` | **Debug** | `   ↳ ❌ Judge Chunk 1: REJECTED (In: 1,150 | Out: 248) — 246: חוסר התאמה בתגיות...` |
| **Judge Stats** | `pipeline.py` | **Regular** | `⚖️ [Judge Model] Batch: $0.00120 \| Total Judge: $0.45` |
| **Bypass Mode** | `pipeline.py` | **Regular** | `🚫 [BYPASS] Skipping manual intervention. Auto-cleaning 1 subtitle(s)...` |
| **Job Completion** | `pipeline.py` | **Regular** | `✅ Job Completed in 14m 22s.` |

## Notes on Optimization

> [!TIP]
> **Silencing the Sanitizer**: If the "English Ghost" bug is rare, we could move those `🧹 [Sanitizer]` logs to Debug mode to keep the terminal focused on translation success.

> [!IMPORTANT]
> **Diagnostic File Logs**: Even in **Regular Mode**, some logs only appear in the physical `.txt` file on disk to prevent terminal clutter (e.g., the very long `--- JUDGE CHUNK SYSTEM PROMPT ---` blocks in `llm_api.py`).

---
*Last updated: 2026-05-03*
