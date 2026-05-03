from openai import OpenAI
from core.llm._utils import _strip_markdown_fences, _supports_structured_output
from core.llm.schemas import generate_batch_schema, generate_judge_schema

def call_openai(model_cfg, system_prompt, user_prompt, api_key, indices_list=None, is_judge=False, response_format=None, profile=None):
    client = OpenAI(api_key=api_key)
    current_temp = model_cfg.get('temperature', 0.0)
    is_gpt5 = "gpt-5" in model_cfg['name'].lower()
    
    # GPT-5 / o1 reasoning models optimization: 
    # Use the 'developer' role which is the new standard for o1 models.
    # This provides the best of both worlds: high-reasoning obedience and perfect caching.
    if is_gpt5:
        req_params = {
            "model": model_cfg['name'],
            "messages": [
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
    else:
        req_params = {
            "model": model_cfg['name'],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": current_temp
        }
        
        # OpenAI Structured Outputs (Strict Mode) check:
        # Requires gpt-4o, gpt-4o-mini, or o1 (if not using developer role)
        # OR LM Studio (which supports it in latest versions)
        supports_structured = _supports_structured_output(model_cfg)

        if response_format is not None:
            req_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "audit_output" if is_judge else "translation_output",
                    "strict": True,
                    "schema": response_format
                }
            }
        elif indices_list and supports_structured:
            use_scratch = model_cfg.get('enable_scratchpad', True)
            schema = generate_judge_schema(indices_list, profile=profile) if is_judge else generate_batch_schema(indices_list, use_scratchpad=use_scratch, profile=profile)
            req_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "audit_output" if is_judge else "translation_output",
                    "strict": True,
                    "schema": schema
                }
            }
        else:
            req_params["response_format"] = {"type": "json_object"}
        
    response = client.chat.completions.create(**req_params)

    raw_content = response.choices[0].message.content
    # Strip markdown if model added it
    raw_content = _strip_markdown_fences(raw_content)

    # Robust extraction for OpenAI/GPT-5 caching & reasoning
    cached_tokens = 0
    reasoning_tokens = 0
    usage = getattr(response, 'usage', None)
    if usage:
        # 1. Prompt Caching
        p_details = getattr(usage, 'prompt_tokens_details', None)
        if p_details:
            cached_tokens = getattr(p_details, 'cached_tokens', 0) or 0
        
        # 2. Reasoning (Brain Load)
        c_details = getattr(usage, 'completion_tokens_details', None)
        if c_details:
            reasoning_tokens = getattr(c_details, 'reasoning_tokens', 0) or 0
    
    return raw_content, response.usage.prompt_tokens, response.usage.completion_tokens, cached_tokens, reasoning_tokens
