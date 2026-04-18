"""Whisper transcription for Telegram voice messages (UA-biased)."""
from openai import OpenAI

from lib.config import OPENAI_API_KEY

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


_UA_DISH_PROMPT = (
    "борщ вареники голубці деруни сирники капусняк котлета гречка окрошка "
    "пельмені салат олівʼє вінегрет узвар компот холодець"
)


def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Return the transcript of a Telegram OGG/Opus voice message, Ukrainian-biased."""
    resp = _get_client().audio.transcriptions.create(
        model="whisper-1",
        file=(filename, audio_bytes, "audio/ogg"),
        language="uk",
        prompt=_UA_DISH_PROMPT,
    )
    return (resp.text or "").strip()
