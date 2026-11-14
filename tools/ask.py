"""ask(prompt, target_words, level): sets the speaking challenge the child hears next.
Only used on scenes without an authored decision. Narration checks happen in agent/tutor.py."""
from tools._common import level, text, tool

NAME = "ask"
SCHEMA = tool(
    NAME,
    "Set the next speaking challenge (only on scenes without an authored decision). "
    "On retry it replaces the current scene's challenge; on advance or move_on it sets the next "
    "scene's challenge. target_words are copied from that scene's narration, in order: "
    "level 1 = one word, level 2 = 2-4 words, level 3 = a longer phrase or full sentence. "
    "The prompt is one short sentence that contains the words, e.g. \"Can you say 'quiet forest'?\".",
    {
        "prompt": {"type": "string", "description": "One short sentence containing the target words."},
        "target_words": {"type": "array", "items": {"type": "string"},
                         "description": "The words to say, copied from the narration, in order."},
        "level": {"type": "integer", "enum": [1, 2, 3]},
    },
    ["prompt", "target_words", "level"],
)

LEVEL_WORDS = {1: (1, 1), 2: (2, 4), 3: (3, 20)}


def parse(raw: dict) -> dict:
    lvl = level(raw)
    words = raw.get("target_words")
    if not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words):
        raise ValueError("target_words must be a list of words")
    words = [w.strip().lower().strip(".,!?;:\"'()") for w in words]
    lo, hi = LEVEL_WORDS[lvl]
    if not lo <= len(words) <= hi:
        raise ValueError(f"level {lvl} needs {lo}-{hi} target words, got {len(words)}")
    return {"level": lvl, "prompt": text(raw, "prompt", 160), "target_words": words}
