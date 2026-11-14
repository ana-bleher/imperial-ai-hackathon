"""Paint the child's own avatar in the story's watercolour style, on fal.

The child still designs their avatar (skin, hair, outfit, pet) in the app. The frontend sends a PNG
of that drawn avatar; we repaint it with an image-to-image model so it matches the scene backgrounds,
then remove the background so it can sit on top of every scene.

Nothing here touches a photo of a real child: the input is the app's own illustration.

Needs FAL_KEY in the environment and `pip install fal-client`.
Model ids below are fal's current ones as far as we know; Kiko, check them in the fal dashboard.
"""

import hashlib
import os
import urllib.request
from pathlib import Path

import fal_client

AVATAR_DIR = Path(__file__).resolve().parent.parent / "static" / "avatars"
EDIT_MODEL = "fal-ai/flux-pro/kontext"   # image-to-image edit that keeps pose and colours
CUTOUT_MODEL = "fal-ai/birefnet"          # background removal -> transparent PNG

PROMPT = (
    "Repaint this character in soft watercolor children's picture-book style, matching gentle "
    "storybook backgrounds: loose wet-on-wet washes, soft pencil outlines, light paper texture, warm "
    "pastel palette. Keep exactly the same pose, face, skin tone, hair style, hair colour and clothing.")
PROMPT += (
    " Plain white background. No text, no extra objects."
)


def cache_key(png_bytes: bytes) -> str:
    """Same drawing -> same painting, so we only pay for a new one when the avatar changes."""
    return hashlib.sha1(png_bytes).hexdigest()[:16]


def paint(png_bytes: bytes) -> str | None:
    """Return the /static path of the painted, cut-out avatar, or None on any failure.

    Blocking (call it in a thread). Typically 5-15 seconds the first time, instant when cached.
    """
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(png_bytes)
    out = AVATAR_DIR / f"{key}.png"
    if out.exists():
        return f"/static/avatars/{out.name}"
    if not os.getenv("FAL_KEY"):
        return None
    try:
        source_url = fal_client.upload(png_bytes, "image/png")
        painted = fal_client.subscribe(EDIT_MODEL, arguments={"prompt": PROMPT, "image_url": source_url})
        painted_url = painted["images"][0]["url"]
        cutout = fal_client.subscribe(CUTOUT_MODEL, arguments={"image_url": painted_url})
        final_url = cutout["image"]["url"]
        with urllib.request.urlopen(final_url, timeout=30) as response:
            out.write_bytes(response.read())
        return f"/static/avatars/{out.name}"
    except Exception as error:  # never break the story because of the avatar
        print(f"[paint_avatar] failed: {error!r}")
        return None
