"""GPT-4o vision-based food photo analysis."""
import base64
import json

from openai import OpenAI

from lib.config import OPENAI_API_KEY, ANALYSIS_SYSTEM_PROMPT

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # Remove leading ``` or ```json and trailing ```
        first_newline = t.find("\n")
        if first_newline != -1:
            t = t[first_newline + 1:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def analyze_photo(image_bytes: bytes) -> tuple[dict, str]:
    """Analyze a food photo. Returns (parsed_dict, raw_response_text).

    Retries parsing once (with a reminder) if the first response isn't valid JSON.
    """
    b64 = base64.b64encode(image_bytes).decode("ascii")
    client = _get_client()

    messages = [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                },
                {"type": "text", "text": "Analyze this meal."},
            ],
        },
    ]

    resp = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1500,
        messages=messages,
    )
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(_strip_fences(raw)), raw
    except json.JSONDecodeError:
        pass

    # Retry once with an explicit reminder
    messages.append({"role": "assistant", "content": raw})
    messages.append({
        "role": "user",
        "content": "Your previous reply was not valid JSON. Reply again with ONLY the JSON object, no markdown, no prose.",
    })
    resp2 = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1500,
        messages=messages,
    )
    raw2 = resp2.choices[0].message.content or ""
    return json.loads(_strip_fences(raw2)), raw2
