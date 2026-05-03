from openai import OpenAI

def call_deepseek(model_cfg, system_prompt, user_prompt, api_key, indices_list=None, is_judge=False, response_format=None, profile=None):
    current_temp = model_cfg.get('temperature', 0.15)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model=model_cfg['name'],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=current_temp,
        response_format={"type": "json_object"}
    )
    usage_dict = response.usage.model_dump() if hasattr(response.usage, 'model_dump') else vars(response.usage)
    cached_tokens = usage_dict.get('prompt_cache_hit_tokens', 0)
    
    # New robust details extraction for DeepSeek
    reasoning_tokens = 0
    if getattr(response.usage, 'prompt_tokens_details', None):
        cached_tokens = getattr(response.usage.prompt_tokens_details, 'cached_tokens', 0) or 0
    if getattr(response.usage, 'completion_tokens_details', None):
        reasoning_tokens = getattr(response.usage.completion_tokens_details, 'reasoning_tokens', 0) or 0
        
    return response.choices[0].message.content, response.usage.prompt_tokens, response.usage.completion_tokens, cached_tokens, reasoning_tokens
