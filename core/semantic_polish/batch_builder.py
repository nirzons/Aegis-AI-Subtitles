import os
import json
from utils.srt_manager import load_srt_index_to_text, parse_srt_blocks
from core.text_processing import unfix_rtl

def load_srt_content(srt_path):
    """Loads raw content of an SRT file."""
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"SRT file not found at {srt_path}")
    with open(srt_path, 'r', encoding='utf-8-sig') as f:
        return f.read()

def build_semantic_polish_batches(
    source_srt_path: str,
    translated_srt_path: str,
    batch_size: int = 40,
    context_size: int = 2,
    is_rtl_target: bool = True
) -> list:
    """
    Pairs source.srt and translated.srt lines, chunks them into blocks,
    and adds context lines before and after each batch.
    
    Returns a list of dictionaries, each representing a single batch ready for processing.
    """
    # 1. Parse the source SRT to get strict ordering and text
    source_content = load_srt_content(source_srt_path)
    _, source_by_index, ordered_indices = parse_srt_blocks(source_content)
    
    # 2. Load the translated subtitles as a raw dictionary
    translated_by_index = load_srt_index_to_text(translated_srt_path)
    
    # 3. If target is RTL (like Hebrew), restore it to logical layout for LLM digestion
    processed_translated = {}
    for idx, text in translated_by_index.items():
        if is_rtl_target:
            processed_translated[idx] = unfix_rtl(text, is_rtl=True)
        else:
            processed_translated[idx] = text
            
    # 4. Split indices into chunks and build batches with boundary contexts
    batches = []
    total_indices = len(ordered_indices)
    
    for i in range(0, total_indices, batch_size):
        chunk_end = min(i + batch_size, total_indices)
        
        # Determine boundary ranges for context
        context_before_indices = ordered_indices[max(0, i - context_size) : i]
        active_indices = ordered_indices[i : chunk_end]
        context_after_indices = ordered_indices[chunk_end : min(chunk_end + context_size, total_indices)]
        
        # Construct the combined structured dictionary for prompt population
        # Separated into distinct keys so that polish_manager can format the prompt cleanly
        batch_data = {
            "batch_index": len(batches),
            "active_indices": active_indices,
            "context_before_indices": context_before_indices,
            "context_after_indices": context_after_indices,
            "payload": {
                "context_before": {
                    idx: {
                        "en": source_by_index.get(idx, "").strip(),
                        "he": processed_translated.get(idx, "").strip()
                    }
                    for idx in context_before_indices
                },
                "active_chunk": {
                    idx: {
                        "en": source_by_index.get(idx, "").strip(),
                        "he": processed_translated.get(idx, "").strip()
                    }
                    for idx in active_indices
                },
                "context_after": {
                    idx: {
                        "en": source_by_index.get(idx, "").strip(),
                        "he": processed_translated.get(idx, "").strip()
                    }
                    for idx in context_after_indices
                }
            }
        }
        batches.append(batch_data)
        
    return batches

if __name__ == "__main__":
    # Quick test placeholder to avoid errors if run directly
    print("Batch Builder Loaded.")
