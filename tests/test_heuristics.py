import re

def test_speaker_regex(target_text):
    # The new regex from text_processing.py
    speaker_match = re.search(r'(?m)^(?:\s*-\s*)?([^:\n]{1,15}):', target_text)
    if speaker_match:
        return speaker_match.group(1).strip()
    return None

test_cases = [
    ("JEFF: Hello", "JEFF"), # English (source)
    ("ג'ף: שלום", "ג'ף"), # Hebrew
    ("- ג'ף: שלום", "ג'ף"), # Dash prefix
    ("Line one\nJEFF: Line two", "JEFF"), # Second line
    ("- I was unlucky\n- JEFF: That's interesting", "JEFF"), # Double dash dialogue
    ("Note: This should pass", "Note"), 
    ("Regular sentence without colon", None),
]

for text, expected in test_cases:
    result = test_speaker_regex(text)
    if result != expected:
        print(f"❌ ASSERTION FAILED! Input: {text!r} | Expected: {expected!r} | Got: {result!r}")
        exit(1)

print("ALL TEST CASES PASSED SUCCESSFULLY.")
