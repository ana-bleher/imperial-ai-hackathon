"""Fallback rule: plain Python, no AI. Used on every turn until the agent is wired in,
and afterwards whenever the agent is slow (>6 s) or returns something invalid.

Rules (CLAUDE.md):
- Level 1-3. 2 hits in a row = level up. 2 misses in a row = level down + hint.
- At most 3 tries per scene, then move on with a parent note.
- First silence in a scene is not a miss: "Shall we try together?"
- Branch scenes: either branch word = hit. Neither, first time: repeat the options.
  Neither, second time: propose one. Then "yes" takes it, "no" takes the other,
  anything else takes the proposed one. No miss is ever counted on a branch scene.

State lives in the session dict (see new_scene_state / the keys used below).
`turn()` mutates it and returns a decision dict; agent/main.py applies the decision.
"""
import re
from difflib import SequenceMatcher

MIN_LEVEL, MAX_LEVEL = 1, 3
MAX_TRIES = 3

YES = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure", "please", "alright"}
NO = {"no", "nope", "nah", "not"}

STOPWORDS = {
    "the", "and", "but", "with", "that", "this", "then", "there", "their", "they", "them",
    "she", "her", "his", "him", "you", "your", "what", "when", "where", "which", "who",
    "into", "onto", "from", "over", "under", "very", "just", "have", "has", "had", "were",
    "was", "are", "is", "its", "it's", "for", "of", "to", "in", "on", "at", "a", "an",
    "one", "two", "some", "all", "out", "off", "up", "down", "too", "so", "as", "be",
    "been", "will", "would", "could", "should", "can", "said", "says", "hero", "little",
    "time", "back", "way", "now", "here", "each", "other", "about", "after", "before",
    "again", "still", "every", "while", "until", "towards", "toward", "himself", "herself",
    "themselves", "also", "like", "looks", "looked", "gets", "getting", "ready",
}


# ---------- text helpers ----------

def words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


def similar(target: str, said: str) -> bool:
    """Generous match: exact, or close enough for words of 4+ letters ("fowest" ~ "forest")."""
    if target == said:
        return True
    if len(target) < 4 or len(said) < 3:
        return False
    return SequenceMatcher(None, target, said).ratio() >= 0.75


def heard(target: str, said: list[str]) -> bool:
    return any(similar(target, w) for w in said)


def is_hit(transcript: str, targets: list[str]) -> bool:
    """A hit means most of the target words were heard (all of them for 1-2 words)."""
    said = words(transcript)
    if not targets or not said:
        return False
    found = sum(heard(t, said) for t in targets)
    return found * 2 > len(targets)


# ---------- challenge selection ----------

def _sentences(narration: str) -> list[list[str]]:
    """Sentences as lists of display words (punctuation stripped)."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", narration.strip()):
        toks = [t.strip(".,!?;:\"'()") for t in sent.split()]
        toks = [t for t in toks if t]
        if toks:
            out.append(toks)
    return out


def pick_key_word(narration: str, practised: set[str] = frozenset(),
                  exclude: set[str] = frozenset()) -> str:
    """Simple rule: prefer nouns, i.e. the word ending "a/the (+1 adjective) X" ("a quiet forest" -> forest),
    then any content word (3-9 letters). Skip words already practised when possible."""
    def ok(w):
        return 3 <= len(w) <= 9 and w not in STOPWORDS and w not in exclude and w.isalpha()

    nouns = []
    for toks in _sentences(narration):
        lower = [t.lower() for t in toks]
        for i, t in enumerate(lower):
            if t not in ("a", "an", "the", "some"):
                continue
            run = [w for w in lower[i + 1:i + 3] if ok(w)]
            if len(run) == 2 and run[1].endswith("s") and not run[0].endswith("s"):
                run = run[:1]  # "the path reaches": the second word is probably a verb
            if run:
                nouns.append(run[-1])
    candidates = nouns + [w for w in words(narration) if ok(w)]
    fresh = [w for w in candidates if w not in practised]
    if fresh:
        return fresh[0]
    if candidates:
        return candidates[0]
    return words(narration)[0]


def phrase_for(narration: str, key_word: str, level: int) -> str:
    """Level 1: the word. Level 2: 2-4 words ending in it. Level 3: its sentence (or 6 words if over 10)."""
    if level <= 1:
        return key_word
    for toks in _sentences(narration):
        lower = [t.lower() for t in toks]
        if key_word not in lower:
            continue
        i = lower.index(key_word)
        if level == 2:
            start = max(0, i - 2)
            return " ".join(toks[start:i + 1]) if i > 0 else " ".join(toks[:min(3, len(toks))])
        if len(toks) <= 10:
            return " ".join(toks)
        start = max(0, min(i - 3, len(toks) - 6))
        return " ".join(toks[start:start + 6])
    return key_word


def make_challenge(narration: str, key_word: str, level: int, hint: bool = False) -> dict:
    phrase = phrase_for(narration, key_word, level)
    prompt = f"Can you say '{phrase}'?"
    if hint:
        prompt = f"Let's try together. Listen: '{phrase}'. Can you say it?"
    return {"level": level, "prompt": prompt, "target_words": words(phrase)}


def branch_challenge(scene: dict, proposed: str | None = None) -> dict:
    a, b = (br["word"] for br in scene["branches"])
    prompt = f"Shall we take the {proposed}?" if proposed else f"Shall we go to the {a} or the {b}?"
    return {"level": 1, "prompt": prompt, "target_words": [a, b]}


# ---------- state ----------

def new_session_state() -> dict:
    return {"level": 1, "hit_streak": 0, "miss_streak": 0, "practised": []}


def enter_scene(state: dict, scene: dict, narration: str, exclude: set[str] = frozenset()) -> dict:
    """Reset per-scene counters and set the scene's first challenge."""
    state.update(scene_id=scene["id"], tries=0, silences=0, branch_misses=0, proposed=None)
    if "branches" in scene:
        state["key_word"] = None
        state["challenge"] = branch_challenge(scene)
    else:
        state["key_word"] = pick_key_word(narration, set(state["practised"]), exclude)
        state["challenge"] = make_challenge(narration, state["key_word"], state["level"])
    return state["challenge"]


def _decision(**kw) -> dict:
    d = {"result": None, "log_result": None, "action": None, "feedback": "", "retry": False,
         "next_id": None, "parent_note": None, "challenge": None}
    d.update(kw)
    d["log_result"] = d["log_result"] or d["result"]
    return d


# ---------- the rule ----------

def turn(state: dict, scene: dict, narration: str, transcript: str) -> dict:
    if "branches" in scene:
        return _branch_turn(state, scene, transcript)
    return _scene_turn(state, scene, narration, transcript)


def _scene_turn(state: dict, scene: dict, narration: str, transcript: str) -> dict:
    challenge = state["challenge"]
    phrase = " ".join(challenge["target_words"])

    if not words(transcript):
        state["silences"] += 1
        if state["silences"] == 1:
            return _decision(result="silence", action="retry", retry=True, challenge=challenge,
                             feedback=f"Shall we try together? Listen: '{phrase}'.")
        # Later silences count as a miss.

    state["tries"] += 1
    hit = is_hit(transcript, challenge["target_words"])

    if hit:
        state["hit_streak"] += 1
        state["miss_streak"] = 0
        if state["hit_streak"] >= 2:
            state["level"] = min(MAX_LEVEL, state["level"] + 1)
            state["hit_streak"] = 0
        state["practised"] = sorted(set(state["practised"]) | {state["key_word"]})
        named = phrase if len(challenge["target_words"]) <= 4 else state["key_word"]
        return _decision(result="hit", action="advance", next_id=scene.get("next"),
                         feedback=f"You said '{named}'!")

    state["miss_streak"] += 1
    state["hit_streak"] = 0
    level_down = state["miss_streak"] >= 2
    if level_down:
        state["level"] = max(MIN_LEVEL, state["level"] - 1)
        state["miss_streak"] = 0

    if state["tries"] >= MAX_TRIES:
        return _decision(result="miss", action="move_on", next_id=scene.get("next"),
                         feedback="What great trying! Let's see what happens next.",
                         parent_note=f"Struggled with '{state['key_word']}' - practise together")

    if level_down:
        new = make_challenge(narration, state["key_word"], state["level"], hint=True)
        state["challenge"] = new
        target = " ".join(new["target_words"])
        return _decision(result="miss", action="retry_with_hint", retry=True, challenge=new,
                         feedback=f"Nice try! It starts with '{target[0]}'. Listen: '{target}'. Your turn!")

    return _decision(result="miss", action="retry", retry=True, challenge=challenge,
                     feedback=f"Good try! Listen: '{phrase}'. Your turn!")


def _match_branch(scene: dict, said: list[str]) -> dict | None:
    """First branch word heard, in the order the child said things."""
    for w in said:
        for br in scene["branches"]:
            if similar(br["word"], w):
                return br
    return None


def _branch_turn(state: dict, scene: dict, transcript: str) -> dict:
    branches = scene["branches"]
    said = words(transcript)

    chosen = _match_branch(scene, said)
    if chosen:
        return _decision(result="hit", action="advance", next_id=chosen["next"],
                         feedback=f"You said '{chosen['word']}'! Let's go!", chosen=chosen["word"])

    if not said and state["silences"] == 0:
        state["silences"] += 1
        return _decision(result="silence", action="retry", retry=True, challenge=state["challenge"],
                         feedback="Shall we try together? " + state["challenge"]["prompt"])

    if state["proposed"]:
        proposed = next(br for br in branches if br["word"] == state["proposed"])
        other = next(br for br in branches if br is not proposed)
        pick = other if (set(said) & NO and not set(said) & YES) else proposed
        return _decision(result="hit", log_result="choice", action="advance", next_id=pick["next"],
                         feedback=f"Let's take the {pick['word']}!", chosen=pick["word"])

    # Neither word: not counted as a miss.
    state["branch_misses"] += 1
    if state["branch_misses"] == 1:
        ch = branch_challenge(scene)
        state["challenge"] = ch
        return _decision(result="miss", log_result="no_choice", action="retry", retry=True,
                         challenge=ch, feedback=f"Ooh, which way? {ch['prompt']}")

    state["proposed"] = branches[0]["word"]
    ch = branch_challenge(scene, proposed=state["proposed"])
    state["challenge"] = ch
    return _decision(result="miss", log_result="no_choice", action="retry", retry=True,
                     challenge=ch, feedback=ch["prompt"])
