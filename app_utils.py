import os
import datetime
import json
from text_processing import fix_rtl

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

def load_srt_full_history(path):
    """Parse an SRT file into {index: {time: ..., text: ...}}. Missing/empty file → {}."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            content = f.read().replace('\r\n', '\n')
    except Exception:
        return {}
    
    from text_processing import unfix_rtl
    out = {}
    for block in content.strip().split('\n\n'):
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) >= 3:
            idx = lines[0]
            timestamp = lines[1]
            text = '\n'.join(lines[2:])
            # Restore logical RTL for the web browser
            out[idx] = {"time": timestamp, "text": unfix_rtl(text)}
    return out

def validate_srt_file(path):
    """
    Performs sanity checks on a source SRT file.
    Returns (True, []) if OK, or (False, [error_messages]) if critical issues found.
    """
    if not path or not os.path.exists(path):
        return False, ["File not found."]
    
    errors = []
    try:
        # We read as raw bytes first to check for hidden BOMs in the middle
        with open(path, 'rb') as f:
            raw = f.read()
            
        # Check for BOM (\xef\xbb\xbf) anywhere after index 0
        bom = b'\xef\xbb\xbf'
        first_bom_idx = raw.find(bom)
        if first_bom_idx != -1:
            # Check if there is another BOM starting after the first one's impact (approx start of file)
            # UTF-8 BOM is 3 bytes. If it's at byte 0, it's fine (utf-8-sig handles it).
            # If it's anywhere else, it's a problem.
            if first_bom_idx > 0:
                errors.append(f"Hidden BOM character (\\xef\\xbb\\xbf) found at byte {first_bom_idx}. This makes indices look different to the AI.")
            
            # Check for subsequent BOMs
            curr = first_bom_idx + 3
            while True:
                next_bom = raw.find(bom, curr)
                if next_bom == -1: break
                errors.append(f"Hidden BOM character (\\xef\\xbb\\xbf) found in the middle of the file (byte {next_bom}).")
                curr = next_bom + 3
            
        # Now read as text for logical checks
        with open(path, 'r', encoding='utf-8-sig') as f:
            content = f.read().replace('\r\n', '\n')
    except Exception as e:
        return False, [f"Could not read file: {e}"]

    blocks = content.strip().split('\n\n')
    indices = []
    
    for i, block in enumerate(blocks):
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines: continue
        
        # Check index
        idx_str = lines[0].replace('\ufeff', '') # Strip BOM for checking
        if not idx_str.isdigit():
            errors.append(f"Block {i+1}: Index '{idx_str}' is not a valid number.")
        
        indices.append(idx_str)
        
        # Check timestamp
        if len(lines) < 2 or '-->' not in lines[1]:
            errors.append(f"Block {i+1} (Index {idx_str}): Missing or malformed timestamp line.")
        
        # Check text
        if len(lines) < 3:
            errors.append(f"Block {i+1} (Index {idx_str}): Subtitle text is empty.")

    # Check for duplicates
    if indices:
        from collections import Counter
        counts = Counter(indices)
        duplicates = [idx for idx, count in counts.items() if count > 1]
        if duplicates:
            errors.append(f"Duplicate indices found: {', '.join(duplicates)}. This will cause the AI to overwrite or skip subtitles.")

    if errors:
        return False, errors
    return True, []

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

