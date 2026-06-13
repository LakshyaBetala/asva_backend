"""Upload a Sarvam pronunciation dictionary and print its dict_id.

Server-side phoneme-level word fixes — stronger than the text-substitution
pronunciation pack. Max 100 words per dictionary; entries are scoped to
target_language_code at synthesis time.

Edit DICT below with words testers flag as mispronounced (value = how it
SHOULD sound, written phonetically), run:

    python scripts/upload_pronunciation_dict.py

then put the printed id in .env:  SARVAM_TTS_DICT_ID=p_xxxxxxxx
"""
import json
import os
import sys

import httpx
from dotenv import dotenv_values

env = {**dotenv_values(".env"), **os.environ}
KEY = env.get("SARVAM_API_KEY", "")
if not KEY:
    sys.exit("no SARVAM_API_KEY")

# word → how to say it. Add entries per tester feedback, by ear.
DICT = {
    "pronunciations": {
        "en-IN": {
            "Almmatix": "All-matix",
            "BHK": "bee aitch kay",
            "2BHK": "two bee aitch kay",
            "3BHK": "three bee aitch kay",
        },
        "hi-IN": {
            # Native letter-names so Bulbul says "bee-ech-ke" inside Hindi,
            # not a mangled Latin token. (BHK pronunciation, feedback 2026-06-13.)
            "Almmatix": "ऑलमैटिक्स",
            "BHK": "बी एच के",
            "WhatsApp": "वॉट्सऐप",
        },
        "ta-IN": {
            "Almmatix": "ஆல்மேட்டிக்ஸ்",
            "BHK": "பி எச் கே",
            "WhatsApp": "வாட்ஸ்அப்",
        },
    }
}

resp = httpx.post(
    "https://api.sarvam.ai/text-to-speech/pronunciation-dictionary",
    headers={"api-subscription-key": KEY},
    files={"file": ("dict.json", json.dumps(DICT), "application/json")},
    timeout=30.0,
)
print(resp.status_code, resp.text)
