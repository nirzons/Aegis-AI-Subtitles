import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from utils.app_utils import log, file_log
from core.text_processing import cleanup_failed_translation

@dataclass(frozen=True)
class InterventionResult:
    should_stop: bool
    batch_success: bool
    # Maps specific nested sub-states/dicts to keyword updates
    state_updates: Dict[str, Any] = field(default_factory=dict)

def execute_manual_intervention_or_bypass(
    pipeline: Any,
    state: Any,
    indices: Any,
    expected_count: int,
    original_metadata: Any,
    eng_by_index: Any,
    native_audit_reason: str,
    e: Exception,
    received_dict: Any,
    bypass_count: int,
    bypass_log_file: Any,
    context_state: Any,
    translated_target_by_index: Any,
    stats: Dict[str, Any],
    session_log_file: str,
    f_out: Any,
    pipeline_load: int,
    pipeline_start_time: float,
    profile: Any,
    config: Any,
    log_queue: Any,
    ui_queue: Any,
    session_start_time: float
) -> InterventionResult:
    """
    Executes automated bypass or manual intervention on minimal batch failure streak.
    """
    if state.min_batch_failures >= 3:
        log(log_queue, session_log_file, "❌ Persistent failure at minimal batch size. Triggering intervention...")
        stats["total_interventions"] = stats.get("total_interventions", 0) + 1
        if ui_queue:
            ui_queue.put(("intervention_count", stats["total_interventions"]))

        eng_src_for_intervention = []
        for idx in indices:
            eng_src_for_intervention.append({
                "index": idx,
                "timestamp": next(m['timestamp'] for m in original_metadata if m['index'] == idx),
                "text": eng_by_index[idx]
            })

        reason_for_human = native_audit_reason if native_audit_reason else "System Error (AI succeeded but Engine crashed)"
        if "pipeline_velocity" in str(e):
            reason_for_human += " [Internal Bug: 'pipeline_velocity' missing]"
        else:
            reason_for_human += f" [System Error: {str(e)}]"

        if getattr(pipeline, 'bypass_intervention', False):
            log(log_queue, session_log_file, f"🚫 [BYPASS] Skipping manual intervention. Auto-cleaning {len(indices)} subtitle(s)...")

            bypass_dict = {}
            last_received = received_dict if received_dict is not None else {}
            for m in eng_src_for_intervention:
                raw_target = str(last_received.get(m['index'], ""))
                cleaned = cleanup_failed_translation(raw_target, m['text'], reason_for_human, profile=profile)
                bypass_dict[m['index']] = cleaned
                log(log_queue, session_log_file, f"   🚫 IDX {m['index']}: {repr(raw_target)[:60]} → {repr(cleaned)[:60]}")

            if bypass_log_file is None:
                bypass_log_file = pipeline._create_bypass_log(session_log_file)
            pipeline._write_bypass_entry(bypass_log_file, eng_src_for_intervention, bypass_dict, reason_for_human)
            bypass_count += 1

            received_dict = bypass_dict
            res_json = {
                "translated_srt": bypass_dict,
                "summary": context_state.get('summary'),
                "last_speaker_info": context_state.get('last_speaker_info'),
                "continuity_note": context_state.get('continuity_note')
            }

            log(log_queue, session_log_file, f"🚫 [BYPASS] Auto-cleanup complete. Resuming...")

            pipeline._finalize_batch_success(
                original_metadata, received_dict, f_out,
                translated_target_by_index, res_json, context_state,
                stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
            )

            state.min_batch_failures = 0
            state.failures_at_current_size = 0
            state.batch_success = True

            return InterventionResult(
                should_stop=False,
                batch_success=True,
                state_updates={
                    "bypass_log_file": bypass_log_file,
                    "bypass_count": bypass_count,
                    "received_dict": received_dict,
                    "session_start_time": session_start_time
                }
            )

        intervention_start_t = time.time()
        manual_fix_dict = pipeline._perform_manual_intervention(
            indices,
            eng_src_for_intervention,
            received_dict if received_dict is not None else {},
            reason_for_human,
            config.get("scratch_dir", "scratch"),
            profile=profile
        )
        intervention_duration = time.time() - intervention_start_t
        session_start_time += intervention_duration

        if manual_fix_dict:
            received_dict = manual_fix_dict
            res_json = {
                "translated_srt": manual_fix_dict,
                "summary": context_state.get('summary'),
                "last_speaker_info": context_state.get('last_speaker_info'),
                "continuity_note": context_state.get('continuity_note')
            }

            log(log_queue, session_log_file, "✅ Manual Intervention successful. Resuming automated flow...")
            file_log(session_log_file, f"--- MANUAL INTERVENTION AUDIT (Batch {indices[0]}-{indices[-1]}) ---")
            for m in eng_src_for_intervention:
                idx = m['index']
                file_log(session_log_file, f"IDX {idx} | EN: {m['text']}")
                file_log(session_log_file, f"IDX {idx} | HE (HUMAN): {manual_fix_dict.get(idx, 'MISSING')}")
            file_log(session_log_file, "--------------------------------------------------------")

            pipeline._finalize_batch_success(
                original_metadata, received_dict, f_out,
                translated_target_by_index, res_json, context_state,
                stats, indices, expected_count, pipeline_load, pipeline_start_time, target_is_rtl=profile.target_is_rtl
            )

            state.min_batch_failures = 0
            state.failures_at_current_size = 0
            state.batch_success = True

            return InterventionResult(
                should_stop=False,
                batch_success=True,
                state_updates={
                    "received_dict": received_dict,
                    "session_start_time": session_start_time
                }
            )
        else:
            log(log_queue, session_log_file, "❌ Manual Intervention cancelled or failed. Stopping.")
            return InterventionResult(
                should_stop=True,
                batch_success=False
            )

    return InterventionResult(
        should_stop=False,
        batch_success=False
    )
