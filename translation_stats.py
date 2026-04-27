"""
translation_stats.py
────────────────────
Stats helpers and report printer for the Aegis translation engine.

Extracted here to keep translation_engine.py focused on the core
batch-loop logic. Everything in this module is stateless / pure:
no dependencies on the TranslationEngine class.
"""

import os
import datetime

# ---------------------------------------------------------------------------
# Per-batch-size counter helper
# ---------------------------------------------------------------------------

def _inc_by_size(d, batch_size):
    """Increment the per-batch-size counter in dict d."""
    key = str(batch_size)
    d[key] = d.get(key, 0) + 1


# ---------------------------------------------------------------------------
# Empty stats template (used for new sessions and as setdefault fallback)
# ---------------------------------------------------------------------------

EMPTY_STATS = {
    "total_elapsed_seconds":         0.0,
    "total_batches_attempted":       0,
    "total_batches_succeeded":       0,
    "total_retries":                 0,
    "json_parse_errors":             {},
    "schema_recoveries":             0,
    "sanitizer_fixes":               0,
    "auditor_skip_judge":            {},
    "auditor_sent_to_judge":         {},
    "judge_invocations":             {},
    "judge_approvals":               {},
    "judge_rejections":              {},
    "judge_failed_errors":           {},
    "clean_passes_by_size":          {},
    "judge_approved_passes_by_size": {},
    "batch_shrink_events":           0,
    "batch_grow_events":             0,
    "llm_call_times_new":            [],
    "llm_call_times_retry":          [],
    "resume_count":                  0,
    "linguistics": {
        "source_chars": 0,
        "target_chars": 0,
        "source_words": 0,
        "target_words": 0,
        "source_punct": 0,
        "target_punct": 0,
        "music_symbols": 0,
        "empty_subs":   0,
        "multiline_subs": 0,
        "sdh_filtered":  0,
        "longest_source_chars": {"index": -1, "value": 0},
        "longest_source_words": {"index": -1, "value": 0},
        "longest_target_chars": {"index": -1, "value": 0},
        "longest_target_words": {"index": -1, "value": 0}
    },
    "auditor_false_positives": 0
}


def make_stats(resume_from=None):
    """
    Create a fresh stats dict, or load + backfill from a checkpoint dict.

    Args:
        resume_from: the ``stats`` sub-dict read from a checkpoint JSON,
                     or None to start fresh.
    Returns:
        A fully-populated stats dict ready for use.
    """
    import json
    if resume_from is None:
        # Deep-copy via JSON to ensure all nested structures are fresh but fully populated
        return json.loads(json.dumps(EMPTY_STATS))

    # Resume: backfill any missing keys or nested dict entries
    s = json.loads(json.dumps(resume_from))  # Deep-copy incoming stats
    for k, v in EMPTY_STATS.items():
        if k not in s:
            # Entirely missing top-level key
            s[k] = json.loads(json.dumps(v)) if isinstance(v, (dict, list)) else v
        elif isinstance(v, dict) and isinstance(s[k], dict):
            # Nested dictionary backfill
            for sub_k, sub_v in v.items():
                if sub_k not in s[k]:
                    s[k][sub_k] = sub_v

    s["resume_count"] = s.get("resume_count", 0) + 1
    return s


# ---------------------------------------------------------------------------
# Statistics report printer
# ---------------------------------------------------------------------------

def print_stats(stats, total_blocks, total_main_cost, total_judge_cost,
                srt_file, sys_file, output_file,
                model_cfg, judge_cfg,
                batch_size, final_eff_batch_size, judge_batch_size,
                log_fn):
    """Format and emit the full statistics report via log_fn."""

    W = 60  # report line width

    def div(title=""):
        if not title:
            return "─" * W
        pad = W - len(title) - 2
        left = pad // 2
        right = pad - left
        return f"{'─' * left} {title} {'─' * right}"

    def fmt_time(seconds):
        seconds = int(seconds)
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        parts = []
        if d: parts.append(f"{d}d")
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        parts.append(f"{s}s")
        return " ".join(parts)

    def fmt_by_size(d):
        """Indented per-size lines, sorted by count descending."""
        if not d:
            return "    (none)"
        return "\n".join(
            f"    size={k}:  {v}"
            for k, v in sorted(d.items(), key=lambda x: -x[1])
        )

    def total_and_inline(d):
        """Return (total_count, inline per-size string)."""
        total = sum(d.values()) if d else 0
        if not d:
            return total, ""
        inline = "  (" + ", ".join(
            f"size={k}: {v}"
            for k, v in sorted(d.items(), key=lambda x: int(x[0]))
        ) + ")"
        return total, inline

    def fmt_cost(v):
        return f"${v:.4f}" if v < 100 else f"{int(v):,} tokens"

    # ── Derived values ────────────────────────────────────────────────────
    total_secs  = stats.get("total_elapsed_seconds", 0.0)
    new_times   = stats.get("llm_call_times_new", [])
    retry_times = stats.get("llm_call_times_retry", [])
    avg_block   = (total_secs / total_blocks) if total_blocks > 0 else 0
    avg_new     = (sum(t[0] for t in new_times)   / len(new_times))   if new_times   else 0
    avg_retry   = (sum(t[0] for t in retry_times) / len(retry_times)) if retry_times else 0

    total_chars = sum(t[1] for t in new_times)
    global_avg_speed = (total_chars / total_secs) if total_secs > 0 else 0

    total_attempted = stats.get("total_batches_attempted", 0)
    total_succeeded = stats.get("total_batches_succeeded", 0)
    total_retries   = stats.get("total_retries", 0)
    total_new_calls = total_attempted - total_retries

    clean_passes      = stats.get("clean_passes_by_size", {})
    judge_appr_passes = stats.get("judge_approved_passes_by_size", {})

    json_errors = stats.get("json_parse_errors", {})
    json_total  = sum(json_errors.values()) if json_errors else 0
    json_inline = ("  (" + ", ".join(
                      f"size={k}: {v}"
                      for k, v in sorted(json_errors.items(), key=lambda x: int(x[0]))
                  ) + ")") if json_errors else ""

    skip_total, skip_by = total_and_inline(stats.get("auditor_skip_judge", {}))
    sent_total, sent_by = total_and_inline(stats.get("auditor_sent_to_judge", {}))

    inv_total,  inv_by  = total_and_inline(stats.get("judge_invocations", {}))
    app_total,  app_by  = total_and_inline(stats.get("judge_approvals", {}))
    rej_total,  rej_by  = total_and_inline(stats.get("judge_rejections", {}))
    fail_total          = sum(stats.get("judge_failed_errors", {}).values())

    total_cost    = total_main_cost + total_judge_cost
    completed_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Build output lines ────────────────────────────────────────────────
    out = [
        "",
        f"╔{'═' * (W - 2)}╗",
        f"║{'📊 TRANSLATION STATISTICS REPORT':^{W - 3}}║",
        f"╚{'═' * (W - 2)}╝",
        f"📅 Completed: {completed_str}",
        "",
        div("⏱️  Time"),
        f"  Total Wall Time:         {fmt_time(total_secs)}",
        f"  Total Source (English):  {stats['linguistics']['source_chars']:,} chars",
        f"  Total Target (Hebrew):   {stats['linguistics']['target_chars']:,} chars",
        f"  Global Speed Average:    {global_avg_speed:.1f} ch/s",
        f"  Total Blocks:            {total_blocks}",
        f"  Avg Time / Block:        {avg_block:.1f} sec",
        f"  Avg Time / New Batch:    {avg_new:.1f} sec  ({len(new_times)} batches)",
        f"  Avg Time / Retry Batch:  {avg_retry:.1f} sec  ({len(retry_times)} batches)",
        "",
        div("📦 Batch Activity"),
        f"  Total LLM Calls:         {total_attempted}  ({total_new_calls} new + {total_retries} retries)",
        f"  Successful Batches:      {total_succeeded}",
        f"  Batch Shrink Events:     {stats.get('batch_shrink_events', 0)}",
        f"  Batch Grow Events:       {stats.get('batch_grow_events', 0)}",
        "",
        "  Clean Passes by Batch Size (no retries, no auditor):",
        fmt_by_size(clean_passes),
        "",
        "  Judge-Approved Passes by Batch Size (escalated → approved):",
        fmt_by_size(judge_appr_passes),
        "",
        div("🔁 Parse & Recovery"),
        f"  JSON Parse Errors:       {json_total}{json_inline}",
        f"  Schema Auto-Recoveries:  {stats.get('schema_recoveries', 0)}",
        f"  Sanitizer Fixes:         {stats.get('sanitizer_fixes', 0)}",
        "",
        div("🔍 Auditor Activity"),
        f"  Immediate Retries (skip judge):  {skip_total}{skip_by}",
        f"  Escalated to Judge:              {sent_total}{sent_by}",
        "",
        div("⚖️  Judge Activity"),
        f"  Judge Invocations:   {inv_total}{inv_by}",
        f"  Judge Approvals:     {app_total}{app_by}",
        f"  Judge Rejections:    {rej_total}{rej_by if rej_total > 0 else ''}",
        f"  Judge FAILED Errors: {fail_total}",
        "",
        div("🔄 Session Continuity"),
        f"  Stop/Resume Occurrences:  {stats.get('resume_count', 0)}",
        "",
        div("💰 Cost"),
        f"  Main Model:  {fmt_cost(total_main_cost)}",
        f"  Judge Model: {fmt_cost(total_judge_cost)}",
        f"  Total:       {fmt_cost(total_cost)}",
        "",
        div("📝 LINGUISTIC BALANCE"),
        f"  Character Ratio:     {(stats['linguistics']['target_chars']/stats['linguistics']['source_chars'] if stats['linguistics']['source_chars'] > 0 else 0):.2f}x",
        f"  Word Ratio:          {(stats['linguistics']['target_words']/stats['linguistics']['source_words'] if stats['linguistics']['source_words'] > 0 else 0):.2f}x",
        f"  Words (Eng):         {stats['linguistics']['source_words']:,}",
        f"  Words (Heb):         {stats['linguistics']['target_words']:,}  (Avg { (stats['linguistics']['target_words']/total_blocks if total_blocks > 0 else 0):.1f} words/sub)",
        f"  Punctuation Flux:    Eng: {stats['linguistics']['source_punct']:,} / Heb: {stats['linguistics']['target_punct']:,}",
        "",
        div("🎵 AESTHETIC & FORENSIC METRICS"),
        f"  Music Passthrough:   {stats['linguistics']['music_symbols']:,} symbols",
        f"  Multi-line Subs:     {stats['linguistics']['multiline_subs']:,}  ({(stats['linguistics']['multiline_subs']/total_blocks*100 if total_blocks > 0 else 0):.1f}%)",
        f"  Empty/Omitted Subs:  {stats['linguistics']['empty_subs']:,}  (SDH filtered: {stats['linguistics']['sdh_filtered']})",
        f"  Longest Eng (Chars): Idx {stats['linguistics']['longest_source_chars']['index']} ({stats['linguistics']['longest_source_chars']['value']} chars)",
        f"  Longest Eng (Words): Idx {stats['linguistics']['longest_source_words']['index']} ({stats['linguistics']['longest_source_words']['value']} words)",
        f"  Longest Heb (Chars): Idx {stats['linguistics']['longest_target_chars']['index']} ({stats['linguistics']['longest_target_chars']['value']} chars)",
        f"  Longest Heb (Words): Idx {stats['linguistics']['longest_target_words']['index']} ({stats['linguistics']['longest_target_words']['value']} words)",
        "",
        div("🤖 ENGINE REASONING & TRUST"),
        f"  Auditor False Positives: {stats.get('auditor_false_positives', 0)}  (Flagged but Judge Approved)",
        f"  Trust Score:             {(100 - (stats.get('auditor_false_positives', 0) / stats.get('total_batches_succeeded', 1) * 100)):.1f}%",
        "",
        div("🗂️  Session Parameters"),
        f"  SRT File:           {os.path.basename(srt_file)}",
        f"  Sysprm File:        {os.path.basename(sys_file)}",
        f"  Output File:        {os.path.basename(output_file)}",
        f"  Translator Model:   {model_cfg.get('name', '?')}  ({model_cfg.get('provider', '?')})",
        f"  Judge Model:        {judge_cfg.get('name', '?')}  ({judge_cfg.get('provider', '?')})",
        f"  Initial Batch Size: {batch_size}",
        f"  Final Eff. Batch:   {final_eff_batch_size}",
        f"  Judge Batch Size:   {judge_batch_size}",
        "",
        "═" * W,
    ]

    for line in out:
        log_fn(line)
