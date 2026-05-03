def build_system_prompt(profile, model_cfg, idx_workflow, idx_tech, idx_clean, prompt_prefix, series_context):
    from core.constants import (
        get_workflow_step_templates, STEP_HEADER_EN, build_technical_rules
    )
    use_scratchpad = model_cfg.get("enable_scratchpad", True)
    
    workflow_steps = get_workflow_step_templates(profile, use_scratchpad)
    formatted_steps = []
    for i, step_text in enumerate(workflow_steps, 1):
        formatted_steps.append(step_text.replace("{n}", str(i)))
        
    # Default to English header
    sys_inst_header = STEP_HEADER_EN.replace("[IDX_WORKFLOW]", str(idx_workflow))
    
    # Check if profile provides its own header for native instructions
    if profile.use_native_instructions and profile.native_workflow_steps and 'header' in profile.native_workflow_steps:
        sys_inst_header = profile.native_workflow_steps['header'].replace("[IDX_WORKFLOW]", str(idx_workflow))

    sys_inst = sys_inst_header + "\n" + "\n".join(formatted_steps)
    
    tech_rules = build_technical_rules(profile)
    tech_rules = tech_rules.replace("[IDX_TECH]", str(idx_tech)).replace("[IDX_CLEAN]", str(idx_clean))

    system_prompt_parts = []
    if prompt_prefix:
        system_prompt_parts.append(prompt_prefix)
    if series_context:
        system_prompt_parts.append(series_context.strip())
    system_prompt_parts.append(sys_inst.strip())
    system_prompt_parts.append(tech_rules.strip())
    
    return "\n\n".join(system_prompt_parts) + "\n"

def build_user_prompt(
    profile, model_cfg, context_state, expected_count, indices, 
    text_chunk, input_payload, use_scratchpad, warning_section, 
    tag_rule, last_judge_error, last_judged_indices
):
    from core.constants import (
        get_json_schema, get_user_prompt_prefix, get_technical_rules_header,
        get_exact_count_rule, get_exact_indices_rule, get_do_not_translate_rule,
        get_tag_rule
    )
    summary_text = context_state.get('summary', profile.default_opening_summary)
    last_speaker = context_state.get('last_speaker_info') or context_state.get('last_speaker', profile.default_unknown_speaker)
    setting = context_state.get('current_setting', profile.default_setting_label)
    
    last_lines = context_state.get('last_two_lines_target', context_state.get('last_two_lines_heb', []))
    use_native = profile.use_native_instructions
    
    last_line_str = ""
    if last_lines:
        last_line_template = profile.native_last_line_label if use_native else "Last translated line (from previous batch): '{last_line}'"
        last_line_str = last_line_template.replace("{last_line}", last_lines[-1])
        
    continuity_note = context_state.get('continuity_note', '')
    continuity_str = ""
    if continuity_note and continuity_note.strip():
        continuity_template = profile.native_continuity_note_label if use_native else "⚠️ Continuity note from previous batch (Attention!): {note}"
        continuity_str = continuity_template.replace("{note}", continuity_note)

    story_header = profile.native_story_context_header if use_native else "### Story Context (Previous Batches) ###"
    setting_label = (profile.native_current_setting_label if use_native else "Current Setting: {setting}").replace("{setting}", setting)
    summary_label = (profile.native_plot_summary_label if use_native else "Plot Summary: {summary}").replace("{summary}", summary_text)
    speaker_label = (profile.native_last_speaker_label if use_native else "Last Speaker (previous batch): {speaker}").replace("{speaker}", last_speaker)

    context_section_lines = [
        story_header,
        setting_label,
        summary_label,
        speaker_label
    ]
    if last_line_str: context_section_lines.append(last_line_str)
    if continuity_str: context_section_lines.append(continuity_str)
        
    context_section = '\n'.join(context_section_lines)

    supports_structured = (model_cfg.get('provider') in ['openai', 'lmstudio'] and 
                         (model_cfg.get('provider') == 'lmstudio' or any(m in model_cfg.get('name', '').lower() for m in ["gpt-4o", "gpt-4o-mini", "o1"])))

    active_schema_template = get_json_schema(profile, is_lite=(not use_scratchpad))
    
    mandatory_schema_msg = profile.native_schema_mandatory_label if profile.use_native_instructions else "### MANDATORY: Respond EXACTLY in the specified JSON Schema format. ###"
    
    if not supports_structured:
        schema_instruction = f"\n{active_schema_template}\n"
    else:
        schema_instruction = f"\n{mandatory_schema_msg}\n"

    user_prompt_prefix = get_user_prompt_prefix(profile)
    tech_rules_header = get_technical_rules_header(profile)
    rule_count = get_exact_count_rule(profile, expected_count)
    rule_indices = get_exact_indices_rule(profile, indices)
    rule_do_not_translate = get_do_not_translate_rule(profile)

    user_prompt_f = f"""
{user_prompt_prefix}
{warning_section}
{context_section}

{text_chunk}

{tech_rules_header}
{rule_count}
{rule_indices}
{rule_do_not_translate}
{tag_rule}
{schema_instruction}
"""

    feedback_injection = ""
    if last_judge_error and set(indices).intersection(last_judged_indices):
        idx_label = profile.native_index_label if profile.use_native_instructions else "Index"
        feedback_injection = "\n" + (profile.native_feedback_header if profile.use_native_instructions else "### YOU MUST FIX THE FOLLOWING ERRORS BY INDEX (DO NOT REPEAT THESE MISTAKES): ###") + "\n"
        
        if isinstance(last_judge_error, dict):
            for err_idx, err_msg in last_judge_error.items():
                if err_idx in ["GLOBAL", "GENERAL", "general"] or str(err_idx).startswith("chunk_") or err_idx in indices or str(err_idx) in [str(i) for i in indices]:
                    prefix = f"{idx_label} {err_idx}: " if err_idx not in ["GLOBAL", "GENERAL", "general"] and not str(err_idx).startswith("chunk_") else ""
                    feedback_injection += f"{prefix}{err_msg}\n"
        else:
            feedback_injection += f"{last_judge_error}\n"
        
        feedback_injection += "----------------------------------------\n"

    return user_prompt_f + feedback_injection
