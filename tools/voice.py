"""ElevenLabs voice: speech-to-text and text-to-speech.

Our server never stores the child's audio: transcribe() sends it to ElevenLabs
and keeps nothing. speak() saves generated narrator speech under static/audio/.
"""

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

AUDIO_DIR = Path(__file__).resolve().parent.parent / "static" / "audio"
STT_MODEL = "scribe_v1"
TTS_MODEL = "eleven_flash_v2_5"  # lowest latency

# Browser MIME types (often with ";codecs=...") -> file extension for the upload name.
_EXTENSIONS = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/mp4": "mp4",
    "video/mp4": "mp4",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
}

_client = None


def _get_client() -> ElevenLabs:
    global _client
    if _client is None:
        _client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    return _client


def transcribe(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Return the transcript of the audio, or "" if nothing was said."""
    base_type = (mime_type or "audio/webm").split(";")[0].strip().lower()
    ext = _EXTENSIONS.get(base_type, "webm")
    result = _get_client().speech_to_text.convert(
        model_id=STT_MODEL,
        file=(f"audio.{ext}", audio_bytes, base_type),
        language_code="en",
        tag_audio_events=False,
    )
    return (result.text or "").strip()


def speak(text: str) -> str:
    """Generate speech for text, save it as an mp3 and return its path, e.g. /static/audio/<uuid>.mp3."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    chunks = _get_client().text_to_speech.convert(
        os.getenv("VOICE_ID"),
        text=text,
        model_id=TTS_MODEL,
        output_format="mp3_44100_128",
    )
    name = f"{uuid.uuid4().hex}.mp3"
    with open(AUDIO_DIR / name, "wb") as f:
        for chunk in chunks:
            f.write(chunk)
    return f"/static/audio/{name}"
