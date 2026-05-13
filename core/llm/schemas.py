def generate_batch_schema(indices_list, use_scratchpad=True, profile=None):
    """Generates a dynamic JSON schema for primary translation."""
    use_native = profile and getattr(profile, 'use_native_instructions', False)
    # Use dict.fromkeys for deduplication while preserving order (important for schema clarity)
    indices = [str(i) for i in indices_list]
    indices = list(dict.fromkeys(indices))
    srt_properties = {idx: {"type": "string"} for idx in indices}
    
    # Standard properties reordered for maximum model focus (Sandwich Structure)
    # 1. Strategy & Priming
    properties = {
        "thought_process": {
            "type": "string", 
            "description": profile.native_schema_descriptions.get("thought_process", "The thought process, strategy, and deliberations before the final translation. Warning: Do not copy the field description! Write your actual thoughts.") if use_native else "The thought process, strategy, and deliberations before the final translation. Warning: Do not copy the field description! Write your actual thoughts."
        },
        "summary": {
            "type": "string",
            "description": profile.native_schema_descriptions.get("summary", "A brief summary of what is currently happening in the plot. Warning: Do not copy the field description! Write a real summary.") if use_native else "A brief summary of what is currently happening in the plot. Warning: Do not copy the field description! Write a real summary."
        }
    }
    
    required_fields = ["thought_process", "summary"]
    
    # 2. Scratchpad (Optional)
    if use_scratchpad:
        properties["continuous_translation_draft"] = {
            "type": "string",
            "description": profile.native_schema_descriptions.get("continuous_translation_draft", f"Translate all texts as one continuous, natural, and flowing paragraph in {profile.target_lang if profile else 'target language'}.") if use_native else "Translate all texts as one continuous, natural, and flowing paragraph."
        }
        properties["mapping_plan"] = {
            "type": "string",
            "description": profile.native_schema_descriptions.get("mapping_plan", "A concise mapping plan of dividing the draft into indices.") if use_native else "A concise mapping plan of dividing the draft into indices."
        }
        required_fields.extend(["continuous_translation_draft", "mapping_plan"])

    # 3. The Core Work
    properties["translated_srt"] = {
        "type": "object",
        "properties": srt_properties,
        "required": indices,
        "additionalProperties": False,
        "description": profile.native_schema_descriptions.get("translated_srt", f"A dictionary where keys are numeric indices and values are the final translations in {profile.target_lang if profile else 'target language'}.") if use_native else "A dictionary where keys are numeric indices and values are the final translations in the target language."
    }
    required_fields.append("translated_srt")

    # 4. Bookkeeping (Moved to the end)
    properties["last_speaker_info"] = {
        "type": "string",
        "description": profile.native_schema_descriptions.get("last_speaker_info", "The speaker's name (M/F) addressing a target (M/F/Unknown/Camera).") if use_native else "The speaker's name (M/F) addressing a target (M/F/Unknown/Camera)."
    }
    properties["continuity_note"] = {
        "type": ["string", "null"],
        "description": profile.native_schema_descriptions.get("continuity_note", "Continuity instruction for the next batch (leave empty if none).") if use_native else "Continuity instruction for the next batch (leave empty if none)."
    }
    required_fields.extend(["last_speaker_info", "continuity_note"])
    
    return {
        "type": "object",
        "properties": properties,
        "required": required_fields,
        "additionalProperties": False
    }


def generate_judge_schema(indices_list, profile=None):
    """Generates a dynamic JSON schema for the AI Judge."""
    use_native = profile and getattr(profile, 'use_native_instructions', False)
    # Use dict.fromkeys for deduplication while preserving order
    indices = [str(i) for i in indices_list]
    indices = list(dict.fromkeys(indices))
    # Error map keys are dynamic indices
    error_map_properties = {idx: {"type": "string"} for idx in indices}
    
    return {
        "type": "object",
        "properties": {
            "thought_process": {
                "type": "string",
                "description": profile.native_schema_descriptions.get("judge_thought_process", f"Mandatory: Write at least one sentence in {profile.target_lang if profile else 'target language'} analyzing the translation against the source. Explain exactly why you decided to reject or approve. Do not use '...'.") if use_native else "Mandatory: Write at least one sentence analyzing the translation against the source. Explain exactly why you decided to reject or approve. Do not use '...'."
            },
            "summary": {
                "type": "string",
                "description": profile.native_schema_descriptions.get("judge_summary", "A short summary (one sentence) of the plot. Do not use '...'.") if use_native else "A short summary (one sentence) of the plot. Do not use '...'."
            },
            "is_rejected": {
                "type": "boolean",
                "description": "True if rejected (error found). False if completely flawless."
            },
            "error_map": {
                "type": "object",
                "properties": error_map_properties,
                "required": indices,
                "additionalProperties": False,
                "description": profile.native_schema_descriptions.get("judge_error_map", f"Mapping of indices to errors. Mandatory to provide reasoning in {profile.target_lang if profile else 'target language'} for each rejection. For a valid translation, leave an empty string \"\".") if use_native else "Mapping of indices to errors. Mandatory to provide reasoning for each rejection. For a valid translation, leave an empty string \"\"."
            }
        },
        "required": ["thought_process", "summary", "is_rejected", "error_map"],
        "additionalProperties": False
    }
