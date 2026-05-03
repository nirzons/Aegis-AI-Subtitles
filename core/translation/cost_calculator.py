def calculate_costs(tokens_in, tokens_out, tokens_cached, tokens_reasoning, cfg):
    """
    Calculates the financial cost of a single API interaction, factoring in:
    1. Context caching discounts (if using deepseek or supported endpoints).
    2. Hardware tokens tracking vs. Local model zero-costs.
    3. Reasoning load percentages for GPT-5/o1/Thinker models.
    """
    discount = cfg.get('cache_discount', 0.0)
    hit_pct = 0

    # Local providers (lmstudio) don't incur financial cost, so we just track token volume
    if cfg.get('provider') == 'lmstudio':
        cost = tokens_in + tokens_out
        hit_str = ""
    elif discount > 0 and tokens_in > 0:
        miss_tokens = tokens_in - tokens_cached
        # Calculate cost considering the discounted cache-hit price
        cache_hit_price = cfg['input_price'] * (1 - (discount / 100.0))
        cost = (miss_tokens / 1e6 * cfg['input_price']) + (tokens_cached / 1e6 * cache_hit_price) + (tokens_out / 1e6 * cfg['output_price'])
        hit_pct = (tokens_cached / tokens_in * 100)
        hit_str = f" [Hit: {tokens_cached:,} ({hit_pct:.1f}%)]"
    else:
        # Standard API pricing without caching discount
        cost = (tokens_in / 1e6 * cfg['input_price']) + (tokens_out / 1e6 * cfg['output_price'])
        hit_str = ""

    # Measure 'Brain Load' - How much token overhead the model spent specifically on Reasoning vs Generation
    brain_load = (tokens_reasoning / tokens_out * 100) if tokens_out > 0 else 0
    brain_str = f" | 🧠 Brain: {tokens_reasoning:,} ({brain_load:.1f}%)" if tokens_reasoning > 0 else ""
    
    return cost, hit_str, hit_pct, brain_str
