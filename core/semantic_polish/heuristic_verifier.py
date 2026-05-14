from core.text_processing import check_heuristics
from core.language_profiles import get_profile

def verify_semantic_replacement(eng_text: str, proposed_he: str, profile=None) -> bool:
    """
    Executes local technical validations against a proposed localization replacement.
    Leverages Aegis core check_heuristics routines to ensure the edit doesn't
    breach layout limits, line length caps, or contain SDH leaks.

    Args:
        eng_text: The original source English text.
        proposed_he: The Senior Editor's proposed Hebrew replacement.
        profile: Optional LanguageProfile. Auto-loaded for 'he' if omitted.

    Returns:
        bool: True if valid and safe to present to the user; False if technically flawed.
    """
    if not proposed_he or not proposed_he.strip():
        return False
        
    if not profile:
        try:
            profile = get_profile("en", "he")
        except Exception:
            profile = None # Fallback to basic fallback heuristics inside text_processing
            
    # Format dictionaries to match batch processing inputs
    eng_dict = {"active_cues": eng_text}
    target_dict = {"active_cues": proposed_he}
    
    is_suspicious, reason, native_reason, skip_judge = check_heuristics(
        eng_dict=eng_dict,
        target_dict=target_dict,
        profile=profile
    )
    
    # Crucial rule: if skip_judge is triggered, it means there is a severe
    # layout violation (overlong line, square bracket SDH, foreign character leak).
    # In these scenarios, the replacement is technically corrupted and must be dropped.
    if skip_judge:
        return False
        
    # Also block if there are clear technical failures like robot talk or tag mismatch
    # by examining the 'reason' string.
    severe_triggers = ["Robot talk", "Tag mismatch", "Silent Skip"]
    if is_suspicious and any(trigger in reason for trigger in severe_triggers):
        return False
        
    return True
