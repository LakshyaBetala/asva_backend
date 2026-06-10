"""Boot guard: refuse to start if the wrong voice_agent package would load.

The old ai_voice (SPC) repo was once `pip install -e`'d globally and silently
shadowed this repo's code — every call played the chemicals persona. This
check makes that failure loud and impossible to miss.
"""
import sys

import voice_agent

print("voice_agent ->", voice_agent.__file__)
if "almmatix_voice" not in voice_agent.__file__:
    print("WRONG voice_agent on sys.path! Expected this repo's src/.", file=sys.stderr)
    sys.exit(1)
