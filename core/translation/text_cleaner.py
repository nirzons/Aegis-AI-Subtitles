def clean_and_strip_tags(input_payload, profile):
    import re
    from utils.srt_manager import RE_ITALIC_S, RE_ITALIC_D, RE_ALIGNMENT

    batch_italic_indices = set()
    batch_alignment_map = {} # stores {line_idx: pos} for each subtitle index
    final_input_payload = {}
    
    for idx, txt in input_payload.items():
        lines = txt.split('\n')
        cleaned_lines = []
        subtitle_aligns = {}
        
        for i, line in enumerate(lines):
            l_strip = line.strip()
            align_match = RE_ALIGNMENT.match(l_strip)
            if align_match:
                subtitle_aligns[i] = align_match.group('pos')
                cleaned_lines.append(align_match.group('rest').strip())
            else:
                cleaned_lines.append(line)
        
        if subtitle_aligns:
            batch_alignment_map[idx] = subtitle_aligns
        
        current_txt = '\n'.join(cleaned_lines).strip()

        # 2. Italic Strip: Check for <i>...</i>
        match_s = RE_ITALIC_S.match(current_txt)
        match_d = RE_ITALIC_D.match(current_txt)
        
        if match_s:
            # Case 1: Single wrap (even if multi-line)
            final_input_payload[idx] = match_s.group('c').strip()
            batch_italic_indices.add(idx)
        elif match_d:
            # Case 2: Double wrap (each line has its own pair)
            final_input_payload[idx] = f"{match_d.group('c1').strip()}\n{match_d.group('c2').strip()}"
            batch_italic_indices.add(idx)
        else:
            # Case 3: Mixed text or complex tags - leave current_txt (which might have had align stripped)
            final_input_payload[idx] = current_txt
            
    return final_input_payload, batch_italic_indices, batch_alignment_map
