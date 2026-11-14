""""Your own adventure": a 4-page story written page by page by Claude, from a background catalogue.

Pages 1-3 end with a choice between two places or things (a branch_choice: both answers valid).
Page 4 is a calm goodnight ending with the authored challenge "Can you whisper 'goodnight'?".
Pages have the same scene shape as data/story.json scenes, plus: page, parent, background_id,
image_path. They live on the session (sess["scenes"]); the Pip story's SCENES is never touched.

One Claude call per page (GENERATE_TIMEOUT), with a single forced tool write_page. Code validates
the page (validate_page); anything slow, failing or invalid -> a pre-written fallback page.
The child's name is never sent: the model writes {CHILD_NAME} and {PET} placeholders.
"""
import asyncio
import json
import logging
import re
from pathlib import Path

from tools._common import tool

log = logging.getLogger("adventure")

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = json.loads((ROOT / "data" / "backgrounds.json").read_text())["backgrounds"]
BACKGROUNDS = {b["id"]: b for b in CATALOGUE}
SYSTEM_PROMPT = (ROOT / "prompts" / "adventure.md").read_text(encoding="utf-8")

PAGES = 4
GENERATE_TIMEOUT = 10.0  # seconds per page
MIN_WORDS, MAX_WORDS = 30, 70
TITLE = "Your own adventure"
GOODNIGHT_CHALLENGE = {"prompt": "Can you whisper 'goodnight'?", "target_words": ["goodnight"]}
DEFAULT_AVATAR_POSITION = {"x": 0.3, "y": 0.62, "scale": 0.35}
CHOICE_WORD = re.compile(r"[a-z]{3,10}")
SCARY_WORDS = {
    "scary", "scared", "afraid", "fear", "frightened", "frightening", "terrified", "monster", "monsters",
    "ghost", "ghosts", "witch", "villain", "wolf", "wolves", "blood", "hurt", "injured", "injury",
    "kill", "killed", "die", "died", "dead", "death", "weapon", "sword", "gun", "fight", "attack",
    "scream", "screamed", "danger", "dangerous", "nightmare", "evil", "poison", "trapped", "cry", "cried",
}

WRITE_PAGE = tool(
    "write_page",
    "Write the next page of the bedtime adventure.",
    {
        "narration": {"type": "string",
                      "description": "35-60 simple, gentle words. Use {CHILD_NAME} for the child and {PET} "
                                     "for their pet. Page 4 ends with 'Goodnight.'"},
        "background_id": {"type": "string", "enum": [b["id"] for b in CATALOGUE]},
        "choices": {"type": "array", "description": "Pages 1-3: exactly two places or things to go to "
                                                   "next. Page 4: empty.",
                    "items": {"type": "object", "additionalProperties": False,
                              "required": ["word", "label"],
                              "properties": {
                                  "word": {"type": "string", "description": "One lowercase word, 3-10 letters."},
                                  "label": {"type": "string", "description": "Card text, at most 30 characters."}}}},
        "ending": {"type": "boolean", "description": "True only on page 4."},
    },
    ["narration", "background_id", "choices", "ending"],
)

_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.AsyncAnthropic(timeout=GENERATE_TIMEOUT, max_retries=0)
    return _client


async def call_model(message: str):
    """The one Claude call per page. Tests replace this function."""
    from agent.tutor import MODEL  # same model as the tutor
    return await client().messages.create(
        model=MODEL, max_tokens=800,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[WRITE_PAGE], tool_choice={"type": "tool", "name": "write_page"},
        messages=[{"role": "user", "content": message}],
    )


# ---------- validation ----------

def word_count(text: str) -> int:
    return len(text.split())


def validate_page(raw, page: int) -> dict:
    """Code-enforced rules. Returns {narration, background_id, choices}; raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("write_page input is not an object")
    narration = raw.get("narration")
    if not isinstance(narration, str):
        raise ValueError("narration missing")
    narration = " ".join(narration.split())
    bg = BACKGROUNDS.get(raw.get("background_id"))
    if bg is None:
        raise ValueError(f"unknown background {raw.get('background_id')!r}")
    ending = page == PAGES
    if bool(bg.get("ending")) != ending:
        raise ValueError("page 4 must use an ending background, and only page 4")
    if raw.get("ending") is not None and bool(raw.get("ending")) != ending:
        raise ValueError(f"ending must be {ending} on page {page}")
    if not MIN_WORDS <= word_count(narration) <= MAX_WORDS:
        raise ValueError(f"narration has {word_count(narration)} words, needs {MIN_WORDS}-{MAX_WORDS}")
    if "{CHILD_NAME}" not in narration:
        raise ValueError("narration does not contain {CHILD_NAME}")
    leftover = set(re.findall(r"\{([A-Z_]+)\}", narration)) - {"CHILD_NAME", "PET"}
    if leftover:
        raise ValueError(f"unknown placeholders {sorted(leftover)}")
    choices = raw.get("choices") or []
    if not isinstance(choices, list):
        raise ValueError("choices must be a list")
    words = set(re.findall(r"[a-z]+", narration.lower()))
    for c in choices:
        if isinstance(c, dict) and isinstance(c.get("word"), str):
            words.add(c["word"].lower())
        if isinstance(c, dict) and isinstance(c.get("label"), str):
            words |= set(re.findall(r"[a-z]+", c["label"].lower()))
    scary = sorted(words & SCARY_WORDS)
    if scary:
        raise ValueError(f"scary words: {scary}")
    if ending:
        if choices:
            raise ValueError("page 4 has no choices")
        if not narration.endswith("Goodnight."):
            narration = f"{narration} Goodnight."
        return {"narration": narration, "background_id": bg["id"], "choices": []}
    if len(choices) != 2:
        raise ValueError(f"pages 1-3 need exactly 2 choices, got {len(choices)}")
    cleaned = []
    for c in choices:
        if not isinstance(c, dict):
            raise ValueError("choice must be an object")
        word, label = c.get("word"), c.get("label")
        if not isinstance(word, str) or not CHOICE_WORD.fullmatch(word):
            raise ValueError(f"choice word {word!r} must be 3-10 lowercase letters")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 30:
            raise ValueError(f"choice label {label!r} must be 1-30 characters")
        cleaned.append({"word": word, "label": label.strip()})
    if cleaned[0]["word"] == cleaned[1]["word"]:
        raise ValueError("the two choices must be different")
    return {"narration": narration, "background_id": bg["id"], "choices": cleaned}


# ---------- scenes ----------

def page_id(page: int, word: str | None) -> str:
    return "a1" if page == 1 else f"a{page}-{word}"


def build_scene(page: int, scene_id: str, data: dict, parent: str | None = None,
                fallback: bool = False) -> dict:
    """A page in the story.json scene shape (plus page, parent, background_id, image_path)."""
    bg = BACKGROUNDS[data["background_id"]]
    scene = {
        "id": scene_id, "page": page, "parent": parent, "fallback": fallback,
        "narration": data["narration"], "image_prompt": "",
        "background_id": bg["id"], "image_path": bg["url"],
        "avatar_position": bg.get("avatar_position") or DEFAULT_AVATAR_POSITION,
    }
    if page < PAGES:
        a, b = data["choices"]
        second = b["label"][:1].lower() + b["label"][1:]
        scene["decision"] = {"type": "branch_choice", "prompt": f"{a['label']} or {second}?"}
        scene["branches"] = [{"word": c["word"], "label": c["label"], "icon": None,
                              "next": page_id(page + 1, c["word"])} for c in data["choices"]]
    else:
        scene["next"] = None
        scene["challenge"] = dict(GOODNIGHT_CHALLENGE)
    return scene


# ---------- fallback pages ----------

FALLBACK_OPENING = {
    "narration": "One bright morning, {CHILD_NAME} and {PET} stepped into a sunny meadow. Soft grass "
                 "tickled their toes and a gentle sun peeped over the hills. Two little paths wound "
                 "away, one towards a flower garden and one towards a golden forest.",
    "background_id": "sunrise-meadow",
    "choices": [{"word": "garden", "label": "Visit the flower garden"},
                {"word": "forest", "label": "Follow the forest trail"}],
}
FALLBACK_MIDDLE = {
    2: {"background_id": "riverside",
        "choices": [{"word": "lake", "label": "Walk to the quiet lake"},
                    {"word": "treehouse", "label": "Climb to the treehouse"}]},
    3: {"background_id": "enchanted-treehouse",
        "choices": [{"word": "cottage", "label": "Rest in the cosy cottage"},
                    {"word": "home", "label": "Go home to bed"}]},
}
FALLBACK_ENDINGS = {
    "cozy-cottage": "{CHILD_NAME} and {PET} found a little cottage with a warm, glowing window. Inside, "
                    "a soft blanket waited by the fire. They snuggled up close and listened to the "
                    "quiet evening. Their eyes grew heavy and sleepy. What a lovely adventure it had been. "
                    "Goodnight.",
    "bedtime-bedroom": "At last, {CHILD_NAME} and {PET} came home to a cosy bedroom. The stars twinkled "
                       "softly through the window and the moon smiled down. {CHILD_NAME} climbed into "
                       "bed and pulled up the warm blanket. What a lovely adventure it had been. Goodnight.",
}


def matching_background(word: str | None, page: int) -> str | None:
    """A catalogue background whose id, title or tags mention the chosen word (not an ending one)."""
    if not word:
        return None
    for b in CATALOGUE:
        text = " ".join([b["id"], b["title"], *b.get("tags", [])]).lower()
        if word in re.findall(r"[a-z]+", text) and not b.get("ending"):
            return b["id"]
    return None


def fallback_page(page: int, choice: dict | None = None) -> dict:
    """Pre-written page data: the sunrise-meadow opening, a gentle "the path led on..." page,
    or a cosy ending on page 4."""
    if page == 1:
        return dict(FALLBACK_OPENING)
    word = (choice or {}).get("word")
    if page == PAGES:
        bg = "cozy-cottage" if word in ("cottage", "house", "cabin") else "bedtime-bedroom"
        return {"narration": FALLBACK_ENDINGS[bg], "background_id": bg, "choices": []}
    spec = FALLBACK_MIDDLE[page]
    bg = matching_background(word, page) or spec["background_id"]
    place = BACKGROUNDS[bg]["title"].lower()
    narration = (f"The path led on, and {{CHILD_NAME}} and {{PET}} wandered gently to the {place}. "
                 "Birds sang softly and the air felt warm and calm. They smiled and looked around. "
                 "Where shall they go next on their cosy adventure?")
    return {"narration": narration, "background_id": bg, "choices": spec["choices"]}


# ---------- generation ----------

def catalogue_for_prompt() -> list[dict]:
    return [{k: b.get(k) for k in ("id", "title", "description", "time_of_day", "ending")} for b in CATALOGUE]


def page_message(page: int, story_so_far: list[dict], pet: str, choice: dict | None) -> str:
    lines = [
        f"PAGE: {page} of {PAGES}" + (" (the ending: no choices, an ending background)" if page == PAGES else ""),
        f"THE CHILD'S PET: {pet} (write {{PET}})",
        f"BACKGROUND CATALOGUE: {json.dumps(catalogue_for_prompt())}",
    ]
    if story_so_far:
        lines.append("STORY SO FAR:")
        lines += [f"- page {p['page']} at {p['background_id']}: {p['narration']}" for p in story_so_far]
    if choice:
        lines.append(f"THE CHILD JUST CHOSE: {choice['word']} ({choice.get('label', '')}). "
                     "Continue the story into that place.")
    return "\n".join(lines)


def read_write_page(response) -> dict:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and block.name == "write_page":
            return block.input
    raise ValueError("write_page not called")


async def generate_page(page: int, story_so_far: list[dict], pet: str, choice: dict | None) -> tuple[dict, str | None]:
    """(validated page data, None), or (fallback page data, why) when slow, failing or invalid."""
    try:
        response = await asyncio.wait_for(call_model(page_message(page, story_so_far, pet, choice)),
                                          GENERATE_TIMEOUT)
        return validate_page(read_write_page(response), page), None
    except asyncio.TimeoutError:
        why = f"generation took over {GENERATE_TIMEOUT:.0f}s"
    except ValueError as e:
        why = f"invalid page: {e}"
    except Exception as e:  # API or network error: the story must never stall
        why = f"generation error: {type(e).__name__}"
    log.warning("adventure page %s fallback: %s", page, why)
    return fallback_page(page, choice), why
