"""
Queries a local Ollama multimodal model (e.g., LLaVA) to determine whether
the bot should leave the call based on visual cues and the recent transcript.
"""
import json
import re
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llava"

PROMPT_TEMPLATE = """You are monitoring a video meeting screenshot and recent transcript around its scheduled end time.
Decide whether the meeting bot should LEAVE now.

Conditions to leave:
- Screen displays "Call ended", "Meeting ended", "You've been removed", or "Returning to home screen".
- The participant count or grid has drastically dropped (e.g. only 1-2 people remain, or everyone left).
- If there are only less then 10 people remaining. 
- The transcript contains closing remarks (e.g. "thanks everyone", "bye", "see you tomorrow", "wrap up").
Otherwise, stay.

Recent transcript:
---
{transcript}
---

Respond with ONLY a valid JSON object:
{{"should_leave": true or false, "reason": "short explanation", "confidence": 0.0 to 1.0}}
"""


def should_leave(screenshot_b64: str, transcript: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(transcript=transcript or "(no speech transcribed yet)")
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "images": [screenshot_b64],
                "stream": False,
                "format": "json"
            },
            timeout=45
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
    except Exception as exc:
        print(f"Ollama call failed: {exc}")
        return {"should_leave": False, "reason": "ollama_error", "confidence": 0.0}

    # Non-greedy extraction to prevent nested regex traps
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if not match:
        return {"should_leave": False, "reason": "unparseable_response", "confidence": 0.0}

    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"should_leave": False, "reason": "bad_json", "confidence": 0.0}