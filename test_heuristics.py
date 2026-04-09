import re

def test_speaker_regex(heb_text):
    # The new regex from text_processing.py
    speaker_match = re.search(r'(?m)^(?:\s*-\s*)?([^:\n]{1,15}):', heb_text)
    if speaker_match:
        return speaker_match.group(1).strip()
    return None

test_cases = [
    ("ג'ף: שלום", "ג'ף"), # Start of string
    ("- ג'ף: שלום", "ג'ף"), # Dash prefix
    ("שורה ראשונה\nג'ף: שורה שניה", "ג'ף"), # Second line
    ("הייתי לא בר מזל -\nג'ף: זה מעניין אותי -", "ג'ף"), # User's specific case
    ("- הייתי לא בר מזל\n- ג'ף: זה מעניין אותי", "ג'ף"), # Double dash dialogue
    ("Note: This should pass", "Note"), # English (will be caught but listed)
    ("Regular sentence without colon", None),
]

for text, expected in test_cases:
    result = test_speaker_regex(text)
    if result != expected:
        raise ValueError(f"ASSERTION FAILED! Input: {text!r} | Expected: {expected!r} | Got: {result!r}")

print("ALL TEST CASES PASSED SUCCESSFULLY.")
