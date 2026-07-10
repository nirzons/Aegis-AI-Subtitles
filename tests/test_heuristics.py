import sys
import os

# Ensure the parent directory is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.text_processing import check_heuristics
from core.language_profiles import get_profile

def test_speaker_name_heuristic():
    # Setup test inputs
    profile = get_profile("en", "he")
    illegal_labels = ["Jeff", "Probst", "ג'ף", "פרובסט"]
    
    # Format of test cases: (target_text, eng_text, expected_flagged, description)
    cases = [
        ("JEFF: Hello", "JEFF: Hello", True, "Uppercase English speaker name (flagged)"),
        ("ג'ף: שלום", "JEFF: Hello", True, "Hebrew translation of illegal label (flagged)"),
        ("- ג'ף: שלום", "JEFF: Hello", True, "Dialogue style Hebrew illegal label (flagged)"),
        ("Regular sentence without colon", "Regular sentence without colon", False, "No colon (not flagged)"),
        ("From the standpoint of: something", "From the standpoint of: something", False, "Grammatical colon with mixed case (not flagged)"),
        ("נקודת המבט של: משהו", "From the standpoint of: something", False, "Hebrew grammatical colon (not flagged)"),
        ("12:30 is the time", "12:30 is the time", False, "Numbers with colon (not flagged)"),
        ("Note: This is an exemption", "Note: This is an exemption", False, "Exempted prefix 'Note' (not flagged)"),
        ("NOTE: This is also exempt", "NOTE: This is also exempt", False, "Exempted uppercase prefix 'NOTE' (not flagged)"),
    ]
    
    failed = False
    for target_text, eng_text, expected_flagged, desc in cases:
        eng_dict = {"1": eng_text}
        target_dict = {"1": target_text}
        
        is_suspicious, reasons, native_reasons, skip_judge = check_heuristics(
            eng_dict=eng_dict,
            target_dict=target_dict,
            illegal_labels=illegal_labels,
            profile=profile
        )
        
        # Check if "speaker" is in the flagged reasons if expected_flagged is True
        has_speaker_reason = False
        if reasons:
            has_speaker_reason = "speaker" in reasons.lower() or "illegal" in reasons.lower()
            
        if has_speaker_reason != expected_flagged:
            print(f"[FAIL] ASSERTION FAILED: {desc}")
            try:
                print(f"  Input: {target_text!r}")
            except:
                pass
            print(f"  Expected Flagged: {expected_flagged} | Got Flagged: {has_speaker_reason}")
            print(f"  Reasons: {reasons!r}")
            failed = True
        else:
            print(f"[PASS] PASSED: {desc}")
            
    if failed:
        sys.exit(1)
    else:
        print("\nALL ADVANCED COLON SAFETY TEST CASES PASSED SUCCESSFULLY.")

if __name__ == "__main__":
    test_speaker_name_heuristic()
