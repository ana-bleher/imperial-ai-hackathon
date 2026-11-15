"""Question types for speaking challenges (scenes without an authored decision). Plain Python, no AI.

A challenge is {level, prompt, target_words, question_type, accept}:
- say:    repeat target_words (from the narration). accept = target_words (+ number forms).
- choice: "A or B?". target_words = the two options (both in the prompt); accept = the right one.
- recall: what/who/where, answered with a word (or short phrase at level 3) from the narration.
- count:  how many, answer 1-5 from the narration. accept has the word and the digit ("three", "3").
- colour: a colour word from the narration.
- open:   why / feelings / prediction. No single answer: any on-topic attempt of 2+ words is a hit.
For recall, count and colour the prompt never contains the answer.

Ladder (types allowed at each level; a lower level's types are always allowed):
  1: say, choice   2: + recall, count, colour   3: + open
On a miss with tries left the retry is one step easier (STEP_DOWN):
  open -> recall or choice;  recall/count/colour -> choice (right answer + one wrong one);
  choice -> say it ("Listen: 'three'. Now you try!");  say -> say (same, or easier with a hint).

The agent's `ask` tool schema and parser live here too (they extend tools/ask.py with
question_type and accept).
"""
from agent import fallback as fb
from tools import ask as ask_tool
from tools._common import level as parse_level
from tools._common import text, tool

SAY, CHOICE, RECALL, COUNT, COLOUR, OPEN = "say", "choice", "recall", "count", "colour", "open"
TYPES = (SAY, CHOICE, RECALL, COUNT, COLOUR, OPEN)
LEVEL_TYPES = {1: (SAY, CHOICE), 2: (RECALL, COUNT, COLOUR), 3: (OPEN, RECALL)}
TYPES_UP_TO = {1: {SAY, CHOICE}, 2: {SAY, CHOICE, RECALL, COUNT, COLOUR}, 3: set(TYPES)}
STEP_DOWN = {OPEN: {RECALL, CHOICE}, RECALL: {CHOICE}, COUNT: {CHOICE}, COLOUR: {CHOICE},
             CHOICE: {SAY}, SAY: {SAY}}
SAY_WORDS = {1: (1, 1), 2: (2, 4), 3: (3, 20)}  # target word counts for a first `say` at each level

NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}
DIGITS = {d: w for w, d in NUMBERS.items()}
COLOURS = {"red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "black", "white",
           "grey", "gray", "gold", "golden", "silver"}


# ---------- answers ----------

def qtype(ch: dict) -> str:
    return ch.get("question_type") or SAY


def number_forms(word: str) -> list[str]:
    """'three' -> ['three', '3']; '3' -> ['three', '3']; anything else -> [word]."""
    if word in NUMBERS:
        return [word, NUMBERS[word]]
    if word in DIGITS:
        return [DIGITS[word], word]
    return [word]


def with_number_forms(words: list[str]) -> list[str]:
    out = []
    for w in words:
        for f in number_forms(w):
            if f not in out:
                out.append(f)
    return out


def answers(ch: dict) -> list[str]:
    return ch.get("accept") or ch.get("target_words") or []


def answer_word(ch: dict) -> str | None:
    """The answer to speak or show (the word, not the digit)."""
    acc = answers(ch)
    words = [w for w in acc if not w.isdigit()] or [DIGITS.get(w, w) for w in acc]
    return words[0] if words else None


def key_word(ch: dict) -> str | None:
    """The learning word of a challenge, for practised words and parent notes."""
    if qtype(ch) in (SAY, OPEN):
        content = [t for t in ch.get("target_words") or [] if t not in fb.STOPWORDS and not t.isdigit()]
        content = content or [t for t in ch.get("target_words") or [] if not t.isdigit()]
        return max(content, key=len) if content else None
    return answer_word(ch)


def normalise(ch: dict) -> dict:
    """Fill question_type and accept; count answers accept both the word and the digit."""
    qt = qtype(ch)
    targets = list(ch.get("target_words") or [])
    accept = list(ch.get("accept") or [])
    if not accept and qt != CHOICE:
        accept = [] if qt == OPEN else targets
    if qt in (COUNT, CHOICE, SAY):
        accept = with_number_forms(accept)
    if qt == COUNT:
        accept = with_number_forms(accept + [t for t in targets if t in NUMBERS or t in DIGITS])
    return {"level": ch["level"], "prompt": ch["prompt"], "target_words": targets,
            "question_type": qt, "accept": accept, "reason": ch.get("reason") or ""}


def is_answer(ch: dict, transcript: str) -> bool:
    """The fallback rule's judgement for this question type, on the words the child settled on."""
    qt = qtype(ch)
    said = fb.settled_words(transcript)
    if not said:
        return False
    if qt == OPEN:
        return len(fb.words(transcript)) >= 2
    if qt == SAY:
        if fb.is_hit(transcript, ch["target_words"]):
            return True  # a phrase still needs most of its words; a single word also accepts "3" for "three"
        return len(ch["target_words"]) == 1 and any(fb.heard(a, said) for a in ch.get("accept", []))
    right = answers(ch)
    if not any(fb.heard(a, said) for a in right):
        return False
    if qt == CHOICE:  # naming both options is not an answer
        wrong = [o for o in ch["target_words"] if o not in right]
        return not any(fb.heard(w, said) for w in with_number_forms(wrong))
    return True


def praise_words(ch: dict) -> list[str] | None:
    """Words the praise on a hit must name (None for open questions: there is no single answer)."""
    qt = qtype(ch)
    if qt == OPEN:
        return None
    if qt == SAY:
        return ch["target_words"]
    return answers(ch)


# ---------- authored scene challenges ----------

def authored_challenge(scene: dict, level: int) -> dict | None:
    """A scene's authored `challenge` (no decision). Used for the first question at session start
    and as the fallback when the agent is slow, invalid or does not ask. Its target_words are
    the accepted answers. Type: question_type if given; else "how many" -> count; a prompt that
    contains the target words -> say; otherwise recall."""
    raw = scene.get("challenge")
    if not raw or fb.decision_type(scene) is not None:
        return None
    targets = [t.lower() for t in raw["target_words"]]
    prompt_words = {w.strip("'") for w in fb.words(raw["prompt"])}
    qt = raw.get("question_type")
    if qt not in TYPES:
        if raw["prompt"].lower().startswith("how many"):
            qt = COUNT
        elif set(targets) & prompt_words:
            qt = SAY
        else:
            qt = RECALL
    return normalise({"level": level, "prompt": raw["prompt"], "target_words": targets,
                      "question_type": qt, "accept": raw.get("accept") or targets,
                      "reason": "Authored question for this scene (fallback)"})


# ---------- step down (fallback) ----------

def _number_value(ch: dict) -> int | None:
    for a in answers(ch):
        if a in DIGITS:
            return int(a)
        if a in NUMBERS:
            return int(NUMBERS[a])
    return None


def wrong_option(ch: dict, narration: str) -> str:
    """One wrong answer from the story for a choice step-down."""
    qt, right = qtype(ch), set(answers(ch))
    said = fb.words(narration)
    if qt == COUNT:
        n = _number_value(ch) or 1
        in_story = [w for w in said if w in NUMBERS and w not in right]
        return in_story[0] if in_story else DIGITS[str(n - 1 if n > 1 else n + 1)]
    if qt == COLOUR:
        in_story = [w for w in said if w in COLOURS and w not in right]
        return in_story[0] if in_story else ("blue" if "blue" not in right else "red")
    nouns = [w for w in fb.nouns(narration) if w not in right and not fb.heard(w, list(right))]
    return nouns[0] if nouns else ("flower" if "flower" not in right else "star")


def choice_from(ch: dict, narration: str, level: int) -> dict:
    """Recall/count/colour/open -> "Was it A or B?" with the right answer and one wrong one."""
    right = answer_word(ch)
    wrong = wrong_option(ch, narration)
    if qtype(ch) == COUNT:
        a, b = sorted([right, wrong], key=lambda w: int(NUMBERS.get(w, "0")))
    else:
        a, b = sorted([right, wrong])
    return normalise({"level": level, "prompt": f"Was it {a} or {b}?", "target_words": [a, b],
                      "question_type": CHOICE, "accept": [right],
                      "reason": f"Fallback step down from {qtype(ch)} to a choice with the right answer"})


def say_from(ch: dict, level: int) -> dict:
    """Choice -> the narrator models the answer, then the child says it: "Listen: 'three'. Now you try!"."""
    right = answer_word(ch)
    return normalise({"level": level, "prompt": f"Listen: '{right}'. Now you try!", "target_words": [right],
                      "question_type": SAY, "accept": [right],
                      "reason": "Fallback step down from a choice to modelling the answer"})


def step_down(ch: dict, narration: str, key: str, level: int) -> dict:
    """The fallback's retry challenge: one step easier than `ch`. For say: the same challenge,
    or an easier one with a hint when the level went down."""
    qt = qtype(ch)
    if qt == SAY:
        if level == ch["level"]:
            return ch
        return normalise({**fb.make_challenge(narration, key, level, hint=True), "question_type": SAY,
                          "reason": f"Fallback: easier say challenge at level {level} with a hint"})
    if qt == CHOICE:
        return say_from(ch, level)
    if qt == OPEN:  # no single answer to build a choice from: model a story word to say
        return normalise({**fb.make_challenge(narration, key, max(1, min(level, 2)), hint=True),
                          "level": level, "question_type": SAY,
                          "reason": "Fallback step down from an open question to saying a story word"})
    return choice_from(ch, narration, level)


# ---------- the agent's ask tool ----------

ASK_SCHEMA = tool(
    "ask",
    "Set the next challenge (only on scenes without an authored decision). On retry it replaces "
    "the current scene's challenge and must be ONE STEP EASIER (open -> recall or choice; "
    "recall/count/colour -> choice of the right answer and one wrong one; choice -> say; say -> say). "
    "On advance or move_on it sets the next scene's challenge. question_type by level: "
    "1 = say or choice, 2 = recall, count or colour, 3 = open, or recall needing a short phrase. "
    "say: target_words are copied from the narration and the prompt contains them "
    "(\"Can you say 'quiet forest'?\"). choice: target_words are the two options, both in the prompt; "
    "accept is the right one. recall/count/colour: target_words is the answer from the narration "
    "(count: 1-5) and the prompt must NOT contain it. open: a why/feelings/prediction question, "
    "target_words and accept may be empty. accept lists acceptable answer words (synonyms; the "
    "digit and word for numbers).",
    {
        "prompt": {"type": "string", "description": "One short question or invitation."},
        "target_words": {"type": "array", "items": {"type": "string"},
                         "description": "say: words to repeat; choice: the two options; "
                                        "recall/count/colour: the answer; open: may be empty."},
        "level": {"type": "integer", "enum": [1, 2, 3]},
        "question_type": {"type": "string", "enum": list(TYPES)},
        "accept": {"type": "array", "items": {"type": "string"},
                   "description": "Acceptable answer words; for choice, the right option."},
        "reason": {"type": "string",
                   "description": "One line for the parent dashboard: why this type and difficulty, "
                                  "from the child's state and streaks. Never quote the child."},
    },
    ["prompt", "target_words", "level", "question_type", "accept", "reason"],
)
assert ask_tool.NAME == ASK_SCHEMA["name"]


def _word_list(raw: dict, field: str, max_items: int) -> list[str]:
    value = raw.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(w, str) and w.strip() for w in value):
        raise ValueError(f"{field} must be a list of words")
    if len(value) > max_items:
        raise ValueError(f"{field} has more than {max_items} items")
    out = [w.strip().lower().strip(".,!?;:\"'()") for w in value]
    if any(len(w) > 30 for w in out):
        raise ValueError(f"{field} items must be short")
    return out


def parse_ask(raw: dict) -> dict:
    """Shape only; narration and ladder checks happen in validate(). question_type and accept
    are optional (default: a say challenge, accept = target_words)."""
    lvl = parse_level(raw)
    qt = raw.get("question_type") or SAY
    if qt not in TYPES:
        raise ValueError(f"question_type must be one of {', '.join(TYPES)}")
    targets = _word_list(raw, "target_words", 20)
    if not targets and qt != OPEN:
        raise ValueError("target_words must not be empty")
    reason = raw.get("reason")
    reason = " ".join(reason.split())[:160] if isinstance(reason, str) else ""
    return normalise({"level": lvl, "prompt": text(raw, "prompt", 160), "target_words": targets,
                      "question_type": qt, "accept": _word_list(raw, "accept", 8),
                      "reason": reason or f"Agent chose a {qt} question at level {lvl}"})


def _supported(word: str, narr: set[str]) -> bool:
    return any(f in narr for f in number_forms(word))


def validate(ch: dict, narration: str, level: int, name_words: set[str], retry_from: dict | None = None) -> dict:
    """Code-enforced limits on an agent-made challenge. Raises ValueError."""
    narr = set(fb.words(narration))
    qt, targets, acc = ch["question_type"], ch["target_words"], ch["accept"]
    prompt_words = {w.strip("'") for w in fb.words(ch["prompt"])}
    if ch["level"] != level:
        raise ValueError(f"ask level {ch['level']} but level is {level}")
    if retry_from is None:
        if qt not in TYPES_UP_TO[level]:
            raise ValueError(f"{qt} is above level {level}")
    else:
        old = qtype(retry_from)
        if qt not in STEP_DOWN[old]:
            raise ValueError(f"retry after {old} must step down to {sorted(STEP_DOWN[old])}, not {qt}")
    if targets and set(targets) <= name_words:
        raise ValueError("target is the child's name")

    if qt == SAY:
        lo, hi = SAY_WORDS[level]
        if retry_from is not None:
            lo = 1  # a modelled say-it hint may be a single word
        if not lo <= len(targets) <= hi:
            raise ValueError(f"level {level} say needs {lo}-{hi} target words, got {len(targets)}")
        missing = [w for w in targets if not _supported(w, narr)]
        if missing:
            raise ValueError(f"target words not in narration: {missing}")
        if not set(targets) <= prompt_words:
            raise ValueError("prompt does not contain the target words")
        if retry_from is not None and qtype(retry_from) == CHOICE:
            if not set(targets) & set(with_number_forms(answers(retry_from))):
                raise ValueError("say-it hint must model the right answer")
        return ch

    if qt == OPEN:
        return ch

    if qt == CHOICE:
        if len(targets) != 2 or targets[0] == targets[1]:
            raise ValueError("choice needs exactly two different options")
        if not set(targets) <= prompt_words:
            raise ValueError("choice prompt must contain both options")
        right = [o for o in targets if set(number_forms(o)) & set(acc)]
        if len(right) != 1:
            raise ValueError("accept must name exactly one of the two options")
        if not _supported(right[0], narr):
            raise ValueError(f"answer not in narration: {right[0]}")
        if retry_from is not None and qtype(retry_from) != OPEN:
            if not set(number_forms(right[0])) & set(with_number_forms(answers(retry_from))):
                raise ValueError("choice must include the right answer")
        return ch

    # recall, count, colour: the answer is in the narration and not in the prompt
    if qt == RECALL:
        hi = 4 if level >= 3 else 1
        if not 1 <= len(targets) <= hi:
            raise ValueError(f"level {level} recall needs 1-{hi} answer words")
    elif len([t for t in targets if not t.isdigit()] or targets) != 1:
        raise ValueError(f"{qt} needs one answer")
    missing = [w for w in targets if not _supported(w, narr)]
    if missing:
        raise ValueError(f"answer not in narration: {missing}")
    if qt == COUNT and _number_value(ch) is None:
        raise ValueError("count answer must be 1-5")
    if qt == COLOUR and not set(targets) & COLOURS:
        raise ValueError("colour answer must be a colour")
    shown = set(with_number_forms(targets)) & prompt_words
    if shown:
        raise ValueError(f"prompt gives the answer away: {sorted(shown)}")
    return ch

