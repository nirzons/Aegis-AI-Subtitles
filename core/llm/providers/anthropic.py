import anthropic
from core.llm._utils import _strip_markdown_fences

def call_anthropic(model_cfg, system_prompt, user_prompt, api_key, indices_list=None, is_judge=False, response_format=None, profile=None):
    """
    Standard provider hook for Anthropic's Claude API.
    """
    client = anthropic.Anthropic(api_key=api_key)
    current_temp = model_cfg.get('temperature', 0.0)
    
    message = client.messages.create(
        model=model_cfg['name'],
        max_tokens=4096,
        temperature=current_temp,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt}
        ]
    )
    
    # Claude content blocks; pull first text element
    raw_content = message.content[0].text
    raw_content = _strip_markdown_fences(raw_content)
    
    # Standard API token reporting
    in_t = getattr(message.usage, 'input_tokens', 0) or 0
    out_t = getattr(message.usage, 'output_tokens', 0) or 0
    
    # Extract native prompt caching telemetry if available
    cached_t = getattr(message.usage, 'cache_creation_input_tokens', 0) or 0
    cached_t += getattr(message.usage, 'cache_read_input_tokens', 0) or 0
    
    return raw_content.strip(), in_t, out_t, cached_t, 0
