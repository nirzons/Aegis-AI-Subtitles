import os
import re
from core.text_processing import unfix_rtl

# Italic Passthrough: pre-compiled at module level for performance.
# RE_ITALIC_S: single <i>…</i> wrap, content may span multiple lines.
# RE_ITALIC_D: two lines each with their own <i>…</i> pair.
RE_ITALIC_S = re.compile(r'^<i>(?P<c>[^<>\n]*(?:\n[^<>\n]*)*)</i>$')
RE_ITALIC_D = re.compile(r'^<i>(?P<c1>[^<>\n]*)</i>\n<i>(?P<c2>[^<>\n]*)</i>$')

# Alignment Passthrough: Support for {\anX} and {anX} at the start of blocks.
RE_ALIGNMENT = re.compile(r'^\{(?P<bs>\\)?an(?P<pos>[1-9])\}(?P<rest>.*)', re.DOTALL)

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
            if first_bom_idx > 0:
                errors.append(f"Hidden BOM character (\\xef\\xbb\\xbf) found at byte {first_bom_idx}. This makes indices look different to the AI.")
            
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
        
        idx_str = lines[0].replace('\ufeff', '') # Strip BOM for checking
        if not idx_str.isdigit():
            errors.append(f"Block {i+1}: Index '{idx_str}' is not a valid number.")
        
        indices.append(idx_str)
        
        if len(lines) < 2 or '-->' not in lines[1]:
            errors.append(f"Block {i+1} (Index {idx_str}): Missing or malformed timestamp line.")
        
        if len(lines) < 3:
            errors.append(f"Block {i+1} (Index {idx_str}): Subtitle text is empty.")

    if indices:
        from collections import Counter
        counts = Counter(indices)
        duplicates = [idx for idx, count in counts.items() if count > 1]
        if duplicates:
            errors.append(f"Duplicate indices found: {', '.join(duplicates)}. This will cause the AI to overwrite or skip subtitles.")

    if errors:
        return False, errors
    return True, []

def parse_srt_blocks(content):
    """
    Parses SRT content into a dictionary of {index: text} and a list of ordered indices.
    """
    content = content.replace('\r\n', '\n')
    blocks = content.strip().split('\n\n')
    
    eng_by_index = {}
    ordered_srt_indices = []
    
    for b in blocks:
        lines_b = b.split('\n')
        if len(lines_b) >= 2:
            idx_b = lines_b[0].strip().replace('\ufeff', '')
            text_b = "\n".join([l.strip() for l in lines_b[2:]]).strip()
            eng_by_index[idx_b] = text_b
            ordered_srt_indices.append(idx_b)
            
    return blocks, eng_by_index, ordered_srt_indices

def get_upcoming_cues(blocks, current_index, count=2):
    """Extracts the next few cues for UI previewing."""
    upcoming = []
    for b_up in blocks[current_index : current_index + count]:
        l_up = b_up.split('\n')
        if len(l_up) >= 2:
            upcoming.append({
                "index": l_up[0].strip(),
                "time": l_up[1].strip(),
                "text": "\n".join([line.strip() for line in l_up[2:]]).strip()
            })
    return upcoming

def extract_chunk_metadata(chunk):
    """Extracts index, timestamp, and text from a chunk of SRT blocks."""
    metadata = []
    for b in chunk:
        lines_b = b.split('\n')
        if len(lines_b) >= 2:
            idx_b = lines_b[0].strip()
            time_b = lines_b[1].strip()
            text_b = "\n".join([l.strip() for l in lines_b[2:]]).strip()
            metadata.append({
                "index": idx_b,
                "timestamp": time_b,
                "text": text_b
            })
    return metadata
