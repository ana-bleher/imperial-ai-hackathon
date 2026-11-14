"""Manual fal integration test (uses credits and uploads a synthetic avatar).

Run from the repository root:
    py tests/try_paint_avatar.py
    py tests/try_paint_avatar.py path/to/avatar.png --output path/to/result.png

Edit PROMPT in tools/paint_avatar.py to change the watercolor style.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.paint_avatar import paint_avatar  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("avatar", nargs="?", type=Path, default=ROOT / "tests/sample_avatar.png")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "tests/avatar_results/sample_avatar.png"
    )
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        result = paint_avatar(args.avatar, args.output)
    except Exception as exc:
        # Keep credentials out of error messages, including errors from dependencies.
        import os

        message = str(exc)
        key = os.getenv("FAL_KEY")
        if key:
            message = message.replace(key, "[redacted]")
        sys.exit(f"Avatar test failed ({type(exc).__name__}): {message}")
    print(f"Transparent avatar: {result}")
    print(f"Total: {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
