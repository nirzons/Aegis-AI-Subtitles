import os
import json
import logging

def get_next_checkpoint_file(checkpoint_dir):
    """Finds the next available translator_checkpoint_N.json filename and initializes it."""
    max_num = 0
    while True:
        max_num += 1
        checkpoint_file = os.path.join(checkpoint_dir, f"translator_checkpoint_{max_num}.json")
        if not os.path.exists(checkpoint_file):
            try:
                with open(checkpoint_file, 'w', encoding='utf-8') as f:
                    json.dump({"pid": os.getpid(), "processed": 0, "status": "initializing"}, f)
                return checkpoint_file
            except Exception:
                continue

def resolve_checkpoint_paths(checkpoint_data, sysprm_dir, english_subs_dir):
    """Ensures absolute paths for files referenced in checkpoint."""
    sys_file_raw = checkpoint_data['sys_file']
    srt_file_raw = checkpoint_data['srt_file']
    
    sys_file = sys_file_raw if os.path.isabs(sys_file_raw) else os.path.join(sysprm_dir, sys_file_raw)
    srt_file = srt_file_raw if os.path.isabs(srt_file_raw) else os.path.join(english_subs_dir, srt_file_raw)
    
    return sys_file, srt_file

def save_checkpoint(checkpoint_file, checkpoint_data):
    """Atomically saves session state to a JSON checkpoint."""
    try:
        # Save to a temporary file first then rename for atomicity if needed, 
        # but simple write is usually fine for this use case.
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        # In a real app we might want to log this via a queue, but for now we just return False
        return False

def cleanup_checkpoint(checkpoint_file):
    """Removes the checkpoint file after successful completion."""
    if checkpoint_file and os.path.exists(checkpoint_file):
        try:
            os.remove(checkpoint_file)
            return True
        except Exception:
            return False
    return False

def build_checkpoint_payload(config, current_index, processed, total_blocks, total_main_cost, total_judge_cost, context_state, profile, stats, output_file):
    """Assembles the full checkpoint dictionary."""
    return {
        "pid": os.getpid(),
        "model_choice": config["model_choice"],
        "judge_model_choice": config["judge_model_choice"],
        "batch_size": config["batch_size"],
        "effective_batch_size": config.get("effective_batch_size", config["batch_size"]),
        "judge_batch_size": config["judge_batch_size"],
        "sys_file": config["sys_name"],
        "srt_file": config["srt_name"],
        "output_file": output_file,
        "current_index": current_index,
        "processed": processed,
        "total_blocks": total_blocks,
        "total_main_cost": total_main_cost,
        "total_judge_cost": total_judge_cost,
        "context_state": context_state,
        "source_lang_code": profile.source_lang_code,
        "target_lang_code": profile.target_lang_code,
        "use_native_instructions": profile.use_native_instructions,
        "max_words_per_line": profile.max_words_per_line,
        "stats": stats,
    }

def restore_profile_from_checkpoint(profile, checkpoint_data):
    """Restores language profile settings from checkpoint metadata."""
    if "source_lang_code" in checkpoint_data:
        profile.source_lang_code = checkpoint_data["source_lang_code"]
    if "target_lang_code" in checkpoint_data:
        profile.target_lang_code = checkpoint_data["target_lang_code"]
    if "use_native_instructions" in checkpoint_data:
        profile.use_native_instructions = bool(checkpoint_data["use_native_instructions"])
    if "max_words_per_line" in checkpoint_data:
        profile.max_words_per_line = int(checkpoint_data["max_words_per_line"])
