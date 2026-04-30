import os
import datetime
import json
from core.text_processing import fix_rtl

def log(log_queue, log_file, text):
    """Logs message to the provided queue (for UI) and the session log file."""
    timestamp = datetime.datetime.now().strftime("[%H:%M:%S]")
    msg = f"{timestamp} {text}"
    if log_queue:
        log_queue.put(text)
    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(msg + "\n")
        except Exception:
            pass

def file_log(log_file, text):
    """Logs message directly to the session log file only."""
    if not log_file:
        return
    timestamp = datetime.datetime.now().strftime("[%H:%M:%S]")
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} {text}\n")
    except Exception:
        pass

def format_cost_display(main_cost, judge_cost):
    """Formats the cost/token display for the UI."""
    def format_single(val):
        if val > 100:
            return f"{int(val):,}"
        return f"${val:.4f}"
    
    main_str = format_single(main_cost)
    label = "Tokens" if main_cost > 100 else "Cost"
    if judge_cost > 0:
        total_str = format_single(main_cost + judge_cost)
        return f"{label}: {total_str} (M: {main_str} | J: {format_single(judge_cost)})"
    return f"{label}: {main_str}"

def get_eta_string(elapsed_time, processed, total_blocks):
    """
    Calculates and formats the ETA string using the formula:
      ETA = (N - l) * (t / l)
    where N=total_blocks, l=processed (all sessions), t=elapsed_time (all sessions).
    This is accurate across suspend/resume because both l and t span all sessions.
    """
    avg_time = elapsed_time / processed if processed > 0 else 0
    eta_seconds = avg_time * (total_blocks - processed)

    days = int(eta_seconds // 86400)
    hours = int((eta_seconds % 86400) // 3600)
    minutes = int((eta_seconds % 3600) // 60)
    seconds = int(eta_seconds % 60)

    time_str = f"{minutes}m {seconds:02d}s"
    if hours > 0 or days > 0:
        time_str = f"{hours}h " + time_str
    if days > 0:
        time_str = f"{days}d " + time_str

    finish_time = datetime.datetime.now() + datetime.timedelta(seconds=eta_seconds)
    finish_str = finish_time.strftime("%H:%M")
    
    return time_str, finish_str, int(eta_seconds)

from utils.srt_manager import strip_srt, load_srt_index_to_text, load_srt_full_history, validate_srt_file

def pretty_json(obj):
    """Attempts to parse and return a pretty-printed JSON string. If fails, returns original."""
    if not obj: return ""
    if isinstance(obj, str):
        try:
            # If it's a string, try to parse it first
            parsed = json.loads(obj)
            return json.dumps(parsed, indent=4, ensure_ascii=False)
        except Exception:
            return obj
    try:
        return json.dumps(obj, indent=4, ensure_ascii=False)
    except Exception:
        return str(obj)



def detect_sysprm_language(content):
    """
    Scans a SysPrm file content for the 'use_native_instructions' flag.
    Returns "Native" if true, "English" if false, or "English" (default) if not found/invalid.
    """
    try:
        data = json.loads(content)
        if data.get("language", {}).get("use_native_instructions"):
            return "Native"
    except Exception:
        pass
    return "English"
