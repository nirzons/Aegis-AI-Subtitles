import os
import json
import time
from datetime import datetime

from core.semantic_polish.batch_builder import build_semantic_polish_batches
from core.semantic_polish.polish_manager import get_or_create_editor_profile, audit_batch_with_editor
from core.semantic_polish.heuristic_verifier import verify_semantic_replacement

def run_semantic_polish_pipeline(
    source_srt: str,
    translated_srt: str,
    sysprm_path: str,
    model_cfg: dict,
    api_key: str,
    batch_size: int = 40,
    context_size: int = 2,
    log_func = None,
    file_log_func = None,
    progress_func = None,
    check_stop_func = None,
    debug_mode: bool = False
) -> dict:
    """
    Executes the complete, sequential Senior Editor semantic audit pipeline over
    an entire subtitle project. Aggregates suggestions and writes a unified
    Markdown/JSON report.
    """
    pipeline_start = time.time()
    
    def notify(msg):
        if log_func:
            log_func(msg)
            
    notify("🚀 [Senior Editor] Initializing Semantic Polish Pipeline...")
    
    # 1. Load/Compile Distilled .sneprf Profile (Hybrid Mastermind Check)
    try:
        sneprf_content = get_or_create_editor_profile(
            sysprm_path=sysprm_path,
            model_cfg=model_cfg,
            api_key=api_key,
            log_func=log_func,
            debug_mode=debug_mode
        )
    except Exception as e:
        notify(f"❌ Pipeline Aborted: Failed to resolve .sneprf profile. Details: {e}")
        raise e
        
    # 2. Build Full Sequenced Batches
    notify("📦 Segmenting subtitle pairs into overlapping batches...")
    batches = build_semantic_polish_batches(
        source_srt_path=source_srt,
        translated_srt_path=translated_srt,
        batch_size=batch_size,
        context_size=context_size,
        is_rtl_target=True # Assume RTL for Hebrew translations
    )
    total_batches = len(batches)
    notify(f"📋 Batch Builder created {total_batches} total batches.")
    
    # 3. Pre-build Cue-to-English lookup table for layout validation & report enrichment
    en_lookup = {}
    for batch in batches:
        active = batch["payload"].get("active_chunk", {})
        for cue_id, data in active.items():
            en_lookup[str(cue_id)] = data.get("en", "")

    # 4. Initialize Sequential Audit Loop trackers
    all_suggestions = []
    telemetry = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0
    }
    
    # OpenAI Strict schema check
    is_openai = "gpt" in model_cfg.get("name", "").lower() or "o1" in model_cfg.get("name", "").lower()
    
    # 4. Run Sequential Processing Loop
    for idx, batch in enumerate(batches):
        # Hot-Path Cancellation Safeguard
        if check_stop_func and check_stop_func():
            notify("🛑 Audit execution halted by Stop signal. Gracefully exiting...")
            raise InterruptedError("Process aborted by user")

        batch_num = idx + 1
        active_chunk = batch["payload"].get("active_chunk", {})
        if not active_chunk:
            continue
            
        start_cue = list(active_chunk.keys())[0]
        end_cue = list(active_chunk.keys())[-1]
        
        notify(f"⏳ Auditing Batch {batch_num}/{total_batches} (Cues {start_cue}-{end_cue})...")
        
        try:
            batch_res = audit_batch_with_editor(
                model_cfg=model_cfg,
                api_key=api_key,
                batch_payload=batch["payload"],
                sysprm_data=None,               # Bypass raw sysprm
                editor_profile_text=sneprf_content, # Inject distilled profile
                supports_structured=is_openai,  # Natively enforce for OpenAI
                log_func=log_func,
                file_log_func=file_log_func,
                debug_mode=debug_mode
            )
            
            # Accumulate metrics
            batch_telemetry = batch_res.get("_telemetry", {})
            telemetry["input_tokens"] += batch_telemetry.get("input_tokens", 0)
            telemetry["output_tokens"] += batch_telemetry.get("output_tokens", 0)
            telemetry["cached_tokens"] += batch_telemetry.get("cached_tokens", 0)
            telemetry["reasoning_tokens"] += batch_telemetry.get("reasoning_tokens", 0)
            
            # Collect validated suggestions
            suggestions = batch_res.get("suggestions", [])
            
            # Filter step A: Strip zero-confidence suppressions
            valid_suggestions = [s for s in suggestions if float(s.get("confidence", 1.0)) > 0.0]
            
            # Filter step B: Phase 1, Step 1.4 - The Heuristic Gatekeeper Audit
            filtered_suggestions = []
            for sug in valid_suggestions:
                cue_idx = str(sug.get("index", ""))
                en_text = en_lookup.get(cue_idx, "")
                rep_text = sug.get("replacement_he", "")
                
                # Discard immediately if layout, line length or SDH constraints are broken
                if verify_semantic_replacement(en_text, rep_text):
                    filtered_suggestions.append(sug)
                else:
                    notify(f"🛡️ [Gatekeeper] Discarded invalid edit for Cue {cue_idx} (Broke layout/length constraints).")
                    
            all_suggestions.extend(filtered_suggestions)
            
            if filtered_suggestions:
                notify(f"✨ Found {len(filtered_suggestions)} safe improvements in batch {batch_num}.")
                
        except Exception as e:
            notify(f"⚠️ Warning: Batch {batch_num} failed! Skipping to maintain pipeline integrity. Error: {e}")
            
        # Live Real-Time Progress Callback
        if progress_func:
            in_rate = model_cfg.get("input_price", 0.0)
            out_rate = model_cfg.get("output_price", 0.0)
            billable_in = max(0, telemetry["input_tokens"] - telemetry["cached_tokens"])
            live_cost = ((billable_in / 1_000_000.0) * in_rate) + ((telemetry["output_tokens"] / 1_000_000.0) * out_rate)
            try:
                progress_func(batch_num, total_batches, live_cost)
            except Exception:
                pass

        # Tiny cool-down to prevent flood triggers
        time.sleep(0.1)
        
    # 5. Generate Execution Metrics & Cost Estimates
    duration = time.time() - pipeline_start
    
    # 6. Calculate simple estimated cost if rates exist in config
    in_rate = model_cfg.get("input_price", 0.0)
    out_rate = model_cfg.get("output_price", 0.0)
    billable_in = max(0, telemetry["input_tokens"] - telemetry["cached_tokens"])
    est_cost = ((billable_in / 1_000_000.0) * in_rate) + ((telemetry["output_tokens"] / 1_000_000.0) * out_rate)
    
    notify(f"🏁 Pipeline finished processing in {duration:.2f}s.")
    
    # 6. Write Consolidated Markdown Audit Report
    base_name = os.path.splitext(os.path.basename(translated_srt))[0]
    audit_dir = "Audit reports"
    if not os.path.exists(audit_dir):
        os.makedirs(audit_dir)
    report_path = os.path.join(audit_dir, f"{base_name}_SENIOR_EDITOR_REPORT.md")
    
    md_report = generate_markdown_report(
        translated_basename=base_name,
        model_name=model_cfg.get("name", "Heavyweight LLM"),
        duration=duration,
        suggestions=all_suggestions,
        telemetry=telemetry,
        estimated_cost=est_cost,
        en_lookup=en_lookup # Pass dynamic map!
    )
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_report)
        
    notify(f"📁 A complete Polish Report written successfully to: {report_path}")
    
    # Enrich all suggestions with resolved English original text for API consumers
    for sug in all_suggestions:
        cue_idx = str(sug.get("index", ""))
        sug["en"] = en_lookup.get(cue_idx, "")
        
    # Return summary artifact for orchestration
    return {
        "report_file": report_path,
        "suggestions_count": len(all_suggestions),
        "suggestions": all_suggestions, # Hand over to visual board!
        "telemetry": telemetry,
        "duration_seconds": duration,
        "estimated_cost_usd": est_cost
    }

def generate_markdown_report(translated_basename, model_name, duration, suggestions, telemetry, estimated_cost, en_lookup) -> str:
    """
    Generates a beautiful, visually readable, and high-stakes Markdown 
    report summarizing all semantic findings.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Table builder
    if not suggestions:
        table_rows = ["| | | | | |\n|---|---|---|---|---|\n| *No critical semantic errors found* | | | | |"]
    else:
        table_rows = ["| Cue | Original (EN) | Current (HE) | Proposed Replacement | Reason & Severity |\n| :--- | :--- | :--- | :--- | :--- |"]
        for sug in suggestions:
            # Resolve original english source using our master lookup table
            cue_idx = str(sug.get("index", ""))
            en_text = en_lookup.get(cue_idx, sug.get("en", "*Missing source*"))
            
            # Safe-escape markdown pipes if present inside text to prevent breaking table rows
            safe_curr = str(sug.get("current_he", "")).replace("|", "\\|").replace("\n", "<br>")
            safe_repl = str(sug.get("replacement_he", "")).replace("|", "\\|").replace("\n", "<br>")
            safe_reason = str(sug.get("reason", "")).replace("|", "\\|")
            safe_en = str(en_text).replace("|", "\\|").replace("\n", "<br>")
            
            severity = sug.get("severity", "CRITICAL")
            conf = sug.get("confidence", 1.0)
            sev_label = f"**[{severity}]**" if "CRITICAL" in severity else f"[{severity}]"
            
            table_rows.append(
                f"| {sug.get('index')} | {safe_en} | `{safe_curr}` | **`{safe_repl}`** | {sev_label}<br>{safe_reason}<br>*(Conf: {conf})* |"
            )
            
    table_block = "\n".join(table_rows)
    
    md = f"""# 🔍 Senior Editor Post-Polish Report

*   **Project Target File:** `{translated_basename}.srt`
*   **Timestamp Executed:** `{timestamp}`
*   **Auditor Intelligence:** `{model_name}`
*   **Total Execution Time:** `{duration:.2f} seconds`
*   **Actionable Suggestions Found:** `{len(suggestions)} improvements`

---

## 📜 The Proposed Improvements
Review the table below. You can choose to approve or discard individual improvements inside the Aegis Merge Tool.

{table_block}

---

## 📊 Telemetry & Financial Metrics
Here are the detailed token usages accumulated across the entire episode:

*   **Total Input Tokens:** `{telemetry['input_tokens']:,}`
*   **Cached Input Tokens:** `{telemetry['cached_tokens']:,}` *(Prompt Cache Efficiency: {(telemetry['cached_tokens']/telemetry['input_tokens']*100 if telemetry['input_tokens'] > 0 else 0):.1f}%)*
*   **Total Output Tokens:** `{telemetry['output_tokens']:,}`
*   **Total Reasoning Tokens:** `{telemetry['reasoning_tokens']:,}`
*   **Estimated Total API Cost:** `${estimated_cost:.5f} USD`
"""
    return md
