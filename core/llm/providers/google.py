from google import genai
from google.genai import types
from core.llm._utils import _strip_markdown_fences

def call_google(model_cfg, system_prompt, user_prompt, api_key, indices_list=None, is_judge=False, response_format=None, profile=None):
    current_temp = model_cfg.get('temperature', 0.15)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_cfg['name'],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=current_temp,
            response_mime_type="application/json" 
        ),
        contents=[user_prompt]
    )
    text = response.text
    text = _strip_markdown_fences(text)
    return text.strip(), response.usage_metadata.prompt_token_count, response.usage_metadata.candidates_token_count, 0, 0
