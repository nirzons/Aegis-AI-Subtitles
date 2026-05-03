from openai import OpenAI
from core.llm._utils import _supports_structured_output
from core.llm.schemas import generate_batch_schema, generate_judge_schema

def call_lmstudio(model_cfg, system_prompt, user_prompt, api_key, indices_list=None, is_judge=False, response_format=None, profile=None):
    current_temp = model_cfg.get('temperature', 0.15)
    client = OpenAI(api_key=api_key, base_url="http://localhost:1234/v1", timeout=2700.0, max_retries=0)
    
    # Check for Structured Output support
    if response_format is not None or indices_list:
        # Prepare the call parameters
        req_params = {
            "model": model_cfg['name'],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": current_temp
        }
        
        # Use 'json_schema' (Strict Mode) for OpenAI high-end models AND LM Studio models.
        if _supports_structured_output(model_cfg):
            if response_format is not None:
                schema = response_format
            else:
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
        
        # Call the LLM (response_format is included if supported/requested above)
        response = client.chat.completions.create(**req_params)

        
        # Extract content with fallback for 'reasoning_content' (critical for DictaLM-Thinking)
        message = response.choices[0].message
        raw_content = getattr(message, 'content', "") or ""
        if not raw_content or not raw_content.strip():
            # Check for reasoning_content if standard content is empty
            raw_content = getattr(message, 'reasoning_content', "") or ""
        
        return raw_content, response.usage.prompt_tokens, response.usage.completion_tokens, 0, 0
