"""Paint an illustrated avatar with fal, then remove its background.

The input is an illustration, never a photo of a real child. The cached paint()
entry point returns a /static path; paint_avatar() supports manual file tests.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

import fal_client
import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
AVATAR_DIR = ROOT / "static" / "avatars"
EDIT_MODEL = "fal-ai/flux-pro/kontext"
CUTOUT_MODEL = "fal-ai/birefnet"
PROMPT = (
    "Repaint the single illustrated child avatar in this image as a soft "
    "watercolor children's picture-book character, matching warm, gentle "
    "bedtime story illustrations. Preserve the character's skin tone, hair "
    "color and hairstyle, outfit colors, expression, and pose. Show the whole "
    "body including shoes, with generous space around it. Use delicate pencil "
    "outlines, soft watercolor washes, subtle paper texture, and friendly "
    "rounded shapes. Keep the character facing forward, alone against a plain "
    "white background. No scenery, props, text, ground shadow, or extra "
    "characters. Illustrated only, never photorealistic."
)
TRAIT_KEYS = ("skin_tone", "hair_style", "hair_colour", "outfit")


def clean_traits(traits: dict | None) -> dict:
    """Only the known traits, as short plain words (they go into a prompt)."""
    cleaned = {}
    for key in TRAIT_KEYS:
        value = (traits or {}).get(key)
        if isinstance(value, str):
            value = re.sub(r"[^A-Za-z -]+", " ", value.replace("_", " "))
            value = " ".join(value.split())[:30].strip()
            if value:
                cleaned[key] = value
    return cleaned


def traits_sentence(traits: dict | None) -> str:
    """e.g. 'The child has medium skin, red curly hair, and wears a raincoat. Keep exactly this
    skin tone - do not lighten or darken it.' Missing traits are skipped; none gives ''."""
    t = clean_traits(traits)
    has = []
    if "skin_tone" in t:
        has.append(f"{t['skin_tone']} skin")
    hair = " ".join(t[k] for k in ("hair_colour", "hair_style") if k in t)
    if hair:
        has.append(f"{hair} hair")
    parts = []
    if has and "outfit" in t:
        parts.append(f"The child has {', '.join(has)}, and wears a {t['outfit']}.")
    elif has:
        parts.append(f"The child has {' and '.join(has)}.")
    elif "outfit" in t:
        parts.append(f"The child wears a {t['outfit']}.")
    if "skin_tone" in t:
        parts.append("Keep exactly this skin tone \u2014 do not lighten or darken it.")
    return " ".join(parts)


def build_prompt(traits: dict | None = None) -> str:
    sentence = traits_sentence(traits)
    return f"{sentence} {PROMPT}" if sentence else PROMPT


def _download_png(url: str, destination: Path) -> None:
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("fal returned a non-PNG image")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)


def paint_avatar(input_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Return the local transparent PNG path; also save a .painted.png preview.

    Uploads the input to fal and makes two billable model requests. Reads
    FAL_KEY from the environment or the repository's ignored .env file.
    """
    source = Path(input_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Avatar not found: {source}")
    if not source.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The input avatar must be a PNG")
    load_dotenv(ROOT / ".env")
    if not os.getenv("FAL_KEY"):
        raise RuntimeError("Set FAL_KEY in .env before running the avatar test")

    destination = (
        Path(output_path).resolve()
        if output_path is not None
        else ROOT / "static" / "avatars" / f"{uuid4().hex}.png"
    )
    if destination.suffix.lower() != ".png":
        raise ValueError("The output path must end in .png")
    painted_path = destination.with_name(f"{destination.stem}.painted.png")
    if source in (destination, painted_path):
        raise ValueError("Choose an output path that does not overwrite the input")

    print("Uploading avatar to fal...", flush=True)
    image_url = fal_client.upload_file(str(source))
    _paint_source(image_url, destination)
    return destination


def _paint_source(image_url: str, destination: Path, prompt: str = PROMPT) -> None:
    painted_path = destination.with_name(f"{destination.stem}.painted.png")
    print(f"Painting with {EDIT_MODEL}...", flush=True)
    painted = fal_client.subscribe(
        EDIT_MODEL,
        arguments={
            "image_url": image_url,
            "prompt": prompt,
            "num_images": 1,
            "output_format": "png",
            "seed": 42,
        },
        client_timeout=300,
    )
    painted_url = painted["images"][0]["url"]
    _download_png(painted_url, painted_path)
    print(f"Painted preview: {painted_path}", flush=True)
    print(f"Removing background with {CUTOUT_MODEL}...", flush=True)
    cutout = fal_client.subscribe(
        CUTOUT_MODEL,
        arguments={"image_url": painted_url, "output_format": "png"},
        client_timeout=300,
    )
    _download_png(cutout["image"]["url"], destination)


def cache_key(png_bytes: bytes, traits: dict | None = None) -> str:
    """Without traits, the existing cache names are kept so unchanged avatars cost nothing.
    With traits, they are part of the key, so the same drawing with new traits repaints."""
    digest = hashlib.sha1(png_bytes)
    cleaned = clean_traits(traits)
    if cleaned:
        digest.update(json.dumps(cleaned, sort_keys=True).encode())
    return digest.hexdigest()[:16]


def paint(png_bytes: bytes, traits: dict | None = None) -> str | None:
    """Return a cached /static avatar path, or None on failure.

    Blocking: call from a worker thread when used by an async endpoint.
    """
    try:
        destination = AVATAR_DIR / f"{cache_key(png_bytes, traits)}.png"
        if destination.exists():
            return f"/static/avatars/{destination.name}"
        load_dotenv(ROOT / ".env")
        if not os.getenv("FAL_KEY"):
            return None
        if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        image_url = fal_client.upload(png_bytes, "image/png")
        _paint_source(image_url, destination, build_prompt(traits))
        return f"/static/avatars/{destination.name}"
    except Exception as error:  # Avatar generation must never interrupt the story.
        message = str(error)
        key = os.getenv("FAL_KEY")
        if key:
            message = message.replace(key, "[redacted]")
        print(f"[paint_avatar] failed ({type(error).__name__}): {message}")
        return None
