"""Manual check: transcribe an audio file, then speak the transcript back.

Usage: python tests/voice_roundtrip.py path/to/clip.webm
"""

import mimetypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.voice import transcribe, speak  # noqa: E402

mimetypes.add_type("audio/webm", ".webm")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mp4", ".m4a")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python tests/voice_roundtrip.py <audio file>")
    path = Path(sys.argv[1])
    mime_type = mimetypes.guess_type(path.name)[0] or "audio/webm"
    audio = path.read_bytes()

    t0 = time.perf_counter()
    transcript = transcribe(audio, mime_type)
    t1 = time.perf_counter()
    print(f"Transcript:  {transcript!r}")
    print(f"Transcribe:  {t1 - t0:.2f}s")

    if not transcript:
        sys.exit("Empty transcript, nothing to speak.")

    out = speak(transcript)
    t2 = time.perf_counter()
    print(f"Output file: {out}")
    print(f"Speak:       {t2 - t1:.2f}s")
    print(f"Total:       {t2 - t0:.2f}s")


if __name__ == "__main__":
    main()
