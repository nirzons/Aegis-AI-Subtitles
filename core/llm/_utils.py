def _strip_markdown_fences(text: str) -> str:
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return text.strip()


def _supports_structured_output(model_cfg: dict) -> bool:
    provider = model_cfg.get('provider')
    name = model_cfg.get('name', '').lower()
    if provider == 'lmstudio':
        return True
    if provider == 'openai':
        return any(m in name for m in ["gpt-4o", "gpt-4o-mini", "o1"])
    return False
