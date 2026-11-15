""""Your own adventure": a 4-page story written page by page by Claude, from a background catalogue.

Page 1 is always the pre-written opening (no generation, so /session/start is fast).
Pages 1-3 end with a choice between two places or things (a branch_choice: both answers valid);
page 3's choices are the last, calm places before bedtime.
Page 4 briefly visits the place chosen on page 3, then the child and pet go home to bed in the
ending background, ending with "Goodnight." Authored challenge: "Can you whisper 'goodnight'?".

Pages 1-3 also carry a learning question about the page (`question`, validated with the
agent/questions.py rules; invalid -> say-it on a noun from the narration). They are played in two
phases (agent/main.py): "question" (question_view: a speaking scene whose `next` is the page itself)
then "choice" (the page as stored: its branch_choice).
Pages have the same scene shape as data/story.json scenes, plus: page, parent, background_id,
image_path. They live on the session (sess["scenes"]); the Pip story's SCENES is never touched.

One Claude call per page (GENERATE_TIMEOUT), with a single tool write_page (tool_choice auto: the
prompt requires exactly one write_page call; a response without it is an invalid page). Code validates
the page (validate_page); anything slow, failing or invalid -> a pre-written fallback page.
The child's name is never sent: the model writes {CHILD_NAME} and {PET} placeholders.
"""
import asyncio
import json
import logging
import re
from pathlib import Path

from agent import fallback as fb
from agent import questions
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
QUESTION_TYPES = ("recall", "count", "colour", "choice", "open")
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
                              "required": ["word", "label", "background_id"],
                              "properties": {
                                  "word": {"type": "string", "description": "One lowercase word, 3-10 letters."},
                                  "label": {"type": "string", "description": "Card text, at most 30 characters."},
                                  "background_id": {
                                      "type": "string", "enum": [b["id"] for b in CATALOGUE],
                                      "description": "The background of the page this choice leads to. "
                                                     "Page 3's choices lead to the goodnight page: use a "
                                                     "background with ending true."}}}},
        "ending": {"type": "boolean", "description": "True only on page 4."},
        "question": {
            "type": "object", "additionalProperties": False,
            "description": "Pages 1-3: one learning question about THIS page for a 4-6-year-old, answered "
                           "clearly by the narration (prefer something countable or colourful). "
                           "Page 4: anything (ignored).",
            "required": ["prompt", "question_type", "accept", "options"],
            "properties": {
                "prompt": {"type": "string", "description": "The short question. For recall, count and "
                                                            "colour it must NOT contain the answer."},
                "question_type": {"type": "string", "enum": list(QUESTION_TYPES)},
                "accept": {"type": "array", "items": {"type": "string"},
                           "description": "Answer words from the narration (count: the word, e.g. 'three'); "
                                          "choice: the right option; open: empty."},
                "options": {"type": "array", "items": {"type": "string"},
                            "description": "choice: the two options, both in the prompt; otherwise empty."},
            },
        },
    },
    ["narration", "background_id", "choices", "ending", "question"],
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
        # Forced tool choice ("tool"/"any") is rejected by this model; the prompt requires write_page,
        # and a response without it is an invalid page (fallback).
        tools=[WRITE_PAGE], tool_choice={"type": "auto"},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": message}],
    )


# ---------- validation ----------

def word_count(text: str) -> int:
    return len(text.split())


def check_background(bg_id, page: int, what: str) -> dict:
    """A catalogue background fit for `page`: an ending background on page 4, and only there."""
    bg = BACKGROUNDS.get(bg_id)
    if bg is None:
        raise ValueError(f"unknown {what} {bg_id!r}")
    if bool(bg.get("ending")) != (page == PAGES):
        raise ValueError(f"{what} on page {page}: page 4 must use an ending background, and only page 4")
    return bg


def validate_page(raw, page: int, required_background: str | None = None) -> dict:
    """Code-enforced rules. Returns {narration, background_id, choices[, question]}; raises ValueError.
    `required_background`: the background the child's choice promised for this page."""
    if not isinstance(raw, dict):
        raise ValueError("write_page input is not an object")
    narration = raw.get("narration")
    if not isinstance(narration, str):
        raise ValueError("narration missing")
    narration = " ".join(narration.split())
    bg = check_background(raw.get("background_id"), page, "background")
    ending = page == PAGES
    if required_background and bg["id"] != required_background:
        raise ValueError(f"page uses {bg['id']}, but the choice leads to {required_background}")
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
    raw_q = raw.get("question")
    if not ending and isinstance(raw_q, dict) and isinstance(raw_q.get("prompt"), str):
        words |= set(re.findall(r"[a-z]+", raw_q["prompt"].lower()))
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
        if not {"home", "bed"} & set(re.findall(r"[a-z]+", narration.lower())):
            raise ValueError("page 4 must mention home or bed")
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
        choice_bg = check_background(c.get("background_id"), page + 1, "choice background")
        cleaned.append({"word": word, "label": label.strip(), "background_id": choice_bg["id"]})
    if cleaned[0]["word"] == cleaned[1]["word"]:
        raise ValueError("the two choices must be different")
    question, why = clean_question(raw_q, narration)
    if why:
        log.info("adventure page %s question fallback (say-it): %s", page, why)
    return {"narration": narration, "background_id": bg["id"], "choices": cleaned, "question": question}


# ---------- the page's learning question ----------

def plain(narration: str) -> str:
    """Narration without placeholders, for judging questions (no 'child' or 'pet' answers)."""
    return re.sub(r"\{[A-Z_]+\}", " ", narration)


def say_it_question(narration: str) -> dict:
    """Backup when the generated question is invalid: say a noun from the narration."""
    text = plain(narration)
    word = next(iter(fb.nouns(text)), None) or fb.pick_key_word(text)
    return {"prompt": f"Can you say '{word}'?", "target_words": [word], "question_type": "say", "accept": [word]}


def clean_question(raw, narration: str) -> tuple[dict, str | None]:
    """The page's question checked with agent/questions.py against this page's narration:
    (question, None), or (say-it question, why) when it is missing or invalid."""
    try:
        if not isinstance(raw, dict) or raw.get("question_type") not in QUESTION_TYPES:
            raise ValueError("question missing or of an unknown type")
        qt = raw["question_type"]
        accept = [a for a in raw.get("accept") or [] if isinstance(a, str) and a.strip()]
        options = [o for o in raw.get("options") or [] if isinstance(o, str) and o.strip()]
        targets = options if qt == "choice" else ([] if qt == "open" else accept[:1])
        ch = questions.parse_ask({"prompt": raw.get("prompt"), "target_words": targets, "level": 3,
                                  "question_type": qt, "accept": accept})
        questions.validate(ch, plain(narration), 3, set())  # level 3: every type allowed for the backup
        if set(re.findall(r"[a-z]+", ch["prompt"].lower())) & SCARY_WORDS:
            raise ValueError("scary words in the question")
        return {k: ch[k] for k in ("prompt", "target_words", "question_type", "accept")}, None
    except ValueError as e:
        return say_it_question(narration), str(e)


def question_view(page: dict) -> dict:
    """A page in its question phase: a speaking scene with the page's question as its authored
    challenge, and `next` = the page itself (code then switches to the choice phase)."""
    view = {k: v for k, v in page.items() if k not in ("decision", "branches")}
    view["next"] = page["id"]
    view["challenge"] = page["question"]
    return view


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
        scene["question"] = data.get("question") or say_it_question(data["narration"])
        scene["branches"] = [{"word": c["word"], "label": c["label"], "icon": None,
                              "background_id": c.get("background_id"),
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
    "choices": [{"word": "garden", "label": "Visit the flower garden", "background_id": "wildflower-garden"},
                {"word": "forest", "label": "Follow the forest trail", "background_id": "golden-forest-trail"}],
    "question": {"prompt": "How many little paths were there?", "target_words": ["two"],
                 "question_type": "count", "accept": ["two", "2"]},
}
# A gentle question for every fallback middle page ("Birds sang softly ...").
MIDDLE_QUESTION = {"prompt": "What sang softly?", "target_words": ["birds"],
                   "question_type": "recall", "accept": ["birds", "bird"]}
FALLBACK_MIDDLE = {
    2: {"background_id": "riverside",
        "choices": [{"word": "lake", "label": "Walk to the quiet lake", "background_id": "lakeside-dawn"},
                    {"word": "treehouse", "label": "Climb to the treehouse",
                     "background_id": "enchanted-treehouse"}]},
    3: {"background_id": "enchanted-treehouse",
        "choices": [{"word": "cottage", "label": "Rest in the cosy cottage", "background_id": "cozy-cottage"},
                    {"word": "home", "label": "Go home to bed", "background_id": "bedtime-bedroom"}]},
}
FALLBACK_ENDINGS = {  # {visit}: one sentence at the place chosen on page 3 (or nothing)
    "cozy-cottage": "{visit}Then {CHILD_NAME} and {PET} walked home to their little cottage with the warm, "
                    "glowing window. Inside, a soft bed waited by the fire. They snuggled up under the "
                    "blanket and their eyes grew heavy and sleepy. What a lovely adventure it had been. "
                    "Goodnight.",
    "bedtime-bedroom": "{visit}Then {CHILD_NAME} and {PET} went home to a cosy bedroom. The stars twinkled "
                       "softly through the window and the moon smiled down. {CHILD_NAME} climbed into "
                       "bed and pulled up the warm blanket. What a lovely adventure it had been. Goodnight.",
}
HOME_WORDS = {"home", "bed", "bedroom", "house", "cottage"}  # a choice that already means going home


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
    promised = BACKGROUNDS.get((choice or {}).get("background_id"))  # the choice's own background
    if promised and bool(promised.get("ending")) != (page == PAGES):
        promised = None
    if page == PAGES:
        bg = promised["id"] if promised else \
            ("cozy-cottage" if word in ("cottage", "house", "cabin") else "bedtime-bedroom")
        visit = "" if not word or word in HOME_WORDS else \
            f"{{CHILD_NAME}} and {{PET}} had one last quiet look at the {word}. "
        return {"narration": FALLBACK_ENDINGS[bg].replace("{visit}", visit), "background_id": bg, "choices": []}
    spec = FALLBACK_MIDDLE[page]
    bg = (promised and promised["id"]) or matching_background(word, page) or spec["background_id"]
    place = BACKGROUNDS[bg]["title"].lower()
    narration = (f"The path led on, and {{CHILD_NAME}} and {{PET}} wandered gently to the {place}. "
                 "Birds sang softly and the air felt warm and calm. They smiled and looked around. "
                 "Where shall they go next on their cosy adventure?")
    return {"narration": narration, "background_id": bg, "choices": spec["choices"],
            "question": dict(MIDDLE_QUESTION)}


# ---------- generation ----------

def catalogue_for_prompt() -> list[dict]:
    return [{k: b.get(k) for k in ("id", "title", "description", "time_of_day", "ending")} for b in CATALOGUE]


def page_message(page: int, story_so_far: list[dict], pet: str, choice: dict | None) -> str:
    notes = {
        PAGES - 1: " (its two choices are the LAST place before bedtime: calm, evening-friendly places)",
        PAGES: " (the ending: briefly visit the chosen place in one or two sentences, then go home and get "
               "cosy in bed, matching the ending background; no choices; end with 'Goodnight.')",
    }
    lines = [
        f"PAGE: {page} of {PAGES}" + notes.get(page, ""),
        f"THE CHILD'S PET: {pet} (write {{PET}})",
        f"BACKGROUND CATALOGUE: {json.dumps(catalogue_for_prompt())}",
    ]
    if story_so_far:
        lines.append("STORY SO FAR:")
        lines += [f"- page {p['page']} at {p['background_id']}: {p['narration']}" for p in story_so_far]
    if choice:
        lines.append(f"THE CHILD JUST CHOSE: {choice['word']} ({choice.get('label', '')}). "
                     "Continue the story into that place.")
        if choice.get("background_id"):
            lines.append(f"THIS PAGE MUST USE background_id: {choice['background_id']} "
                         "(the picture the child chose).")
    return "\n".join(lines)


def read_write_page(response) -> dict:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and block.name == "write_page":
            return block.input
    raise ValueError("write_page not called")


async def generate_page(page: int, story_so_far: list[dict], pet: str, choice: dict | None) -> tuple[dict, str | None]:
    """(validated page data, None), or (fallback page data, why) when slow, failing or invalid.
    Page 1 is always the pre-written opening: no model call."""
    if page == 1:
        return dict(FALLBACK_OPENING), None
    try:
        response = await asyncio.wait_for(call_model(page_message(page, story_so_far, pet, choice)),
                                          GENERATE_TIMEOUT)
        required = (choice or {}).get("background_id")
        return validate_page(read_write_page(response), page, required_background=required), None
    except asyncio.TimeoutError:
        why = f"generation took over {GENERATE_TIMEOUT:.0f}s"
    except ValueError as e:
        why = f"invalid page: {e}"
    except Exception as e:  # API or network error: the story must never stall
        why = f"generation error: {type(e).__name__}: {' '.join(str(e).split())[:300]}"
    log.warning("adventure page %s fallback: %s", page, why)
    return fallback_page(page, choice), why
