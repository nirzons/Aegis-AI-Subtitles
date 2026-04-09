import os
import datetime
import json

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
    if judge_cost > 0:
        return f"M: {main_str} | J: {format_single(judge_cost)}"
    return f"Cost: {main_str}"

def get_eta_string(elapsed_time, session_processed, processed, total_blocks):
    """Calculates and formats the ETA string."""
    avg_time = elapsed_time / session_processed if session_processed > 0 else 0
    eta_seconds = avg_time * (total_blocks - processed)

    days = int(eta_seconds // 86400)
    hours = int((eta_seconds % 86400) // 3600)
    minutes = int((eta_seconds % 3600) // 60)
    seconds = int(eta_seconds % 60)

    time_str = f"{minutes}m {seconds}s"
    if hours > 0 or days > 0:
        time_str = f"{hours}h " + time_str
    if days > 0:
        time_str = f"{days}d " + time_str

    finish_time = datetime.datetime.now() + datetime.timedelta(seconds=eta_seconds)
    finish_str = finish_time.strftime("%H:%M")
    
    return time_str, finish_str

def strip_srt(blocks_list):
    """Strips SRT indices and timestamps, returning only the text content."""
    stripped_texts = []
    for blk in blocks_list:
        blk_lines = blk.split('\n')
        if len(blk_lines) >= 3:
            stripped_texts.append("\n".join([l.strip() for l in blk_lines[2:]]).strip())
    return "\n".join(stripped_texts)


def load_srt_index_to_text(path):
    """Parse an SRT file into {index_string: subtitle text body}. Missing/empty file → {}."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            content = f.read().replace('\r\n', '\n')
    except Exception:
        return {}
    out = {}
    for block in content.strip().split('\n\n'):
        lines = block.split('\n')
        if len(lines) >= 3:
            idx = lines[0].strip()
            text = '\n'.join(l.strip() for l in lines[2:])
            out[idx] = text
    return out
