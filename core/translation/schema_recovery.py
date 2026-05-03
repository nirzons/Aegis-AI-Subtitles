from utils.app_utils import log

def recover_schema(res_json, stats, session_log_file, log_queue=None):
    """
    Attempts to gracefully recover the required output structure when LLMs hallucinate JSON keys.
    Particularly necessary for high-temperature models or deeply analytical GPT-5 models that 
    sometimes ignore the strict envelope keys and wrap the indices in custom objects.
    """
    recovered = False
    if 'translated_srt' not in res_json:
        # Fallback 1: Common hallucinated root keys
        possible_keys = ["translation", "translations", "translated", "result", "output", "data"]
        for pk in possible_keys:
            if pk in res_json and isinstance(res_json[pk], dict):
                res_json['translated_srt'] = res_json[pk]
                recovered = True
                log(log_queue, session_log_file, f"   ↳ 💡 Recovered schema from hallucinated key: '{pk}'")
                break
        
        if not recovered:
            # Fallback 2: Check if any internal dictionary happens to use numeric string keys 
            # (which would correspond to specific subtitle indices)
            for key, value in res_json.items():
                if isinstance(value, dict) and any(str(k).isdigit() for k in value.keys()):
                    res_json['translated_srt'] = value
                    recovered = True
                    log(log_queue, session_log_file, f"   ↳ 💡 Recovered schema from inferred dictionary: '{key}'")
                    break
        
        if not recovered:
            # Fallback 3: The LLM flat-dumped the indices into the root instead of nesting them
            if any(str(k).isdigit() for k in res_json.keys()):
                res_json = {'translated_srt': res_json}
                recovered = True
                log(log_queue, session_log_file, "   ↳ 💡 Recovered schema from root-level flat dictionary")

        if recovered:
            stats["schema_recoveries"] += 1

    # If it's still missing, we trigger an explicit schema collapse which forces a retry loop
    if 'translated_srt' not in res_json or not isinstance(res_json['translated_srt'], dict):
        raise ValueError(f"Schema collapse: 'translated_srt' missing. Found: {list(res_json.keys())}")

    return res_json['translated_srt']
