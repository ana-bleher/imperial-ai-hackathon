"""Kiko: quick manual test of the painted avatar.

1. Put FAL_KEY=... in your .env
2. Save a PNG of an avatar from the app as tests/sample_avatar.png
   (Ana: right-click the avatar in the builder -> or ask Claude for one)
3. py tests/try_paint_avatar.py
The result lands in static/avatars/. Open it and compare with a scene background.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()
from tools import paint_avatar  # noqa: E402

png = (Path(__file__).parent / "sample_avatar.png").read_bytes()
print(paint_avatar.paint(png) or "failed - check FAL_KEY and the model ids")
