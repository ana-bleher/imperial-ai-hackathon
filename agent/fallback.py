"""Fallback rule: plain Python, no AI. Used on every turn until the agent is wired in,
and afterwards whenever the agent is slow (>6 s) or returns something invalid.

Rules (CLAUDE.md), by the scene's decision type:
- No decision (speaking challenge): the scene's authored `challenge` if it has one, else a say-it
  challenge from the narration. Assessed by question type (agent/questions.py). Level 1-3:
  2 hits in a row = level up, 2 misses in a row = level down. A miss with tries left steps the
  question down one rung (count -> choice -> say it). At most max_attempts (default 3) tries,
  then model the answer and move on with a parent note.
- single_correct: the correct_word is a hit. Anything else is a miss: authored hint + retry,
  until max_attempts, then reveal the answer, advance and leave a parent note.
  Never changes the level (levels apply to speaking challenges only).
- branch_choice: any branch word picks that branch. Neither, first time: repeat the options.
  Neither, second time: propose one. Then "yes" takes it, "no" takes the other, anything else
  takes the proposed one. Never counted as a miss.
- First silence in a scene is never a miss: "Take your time!" and the question again.
- Negations and self-corrections ("not sun... moon", "sun, no, moon", "sun... I mean moon"):
  judge the last word the child settled on (settled_words).

State lives in the session dict (see new_session_state / enter_scene).
`turn()` mutates it and returns a decision dict; agent/main.py applies the decision.
Every decision carries a short `reason` for the parent dashboard's agent_log
(it never quotes the child's words).
"""
import re
from difflib import SequenceMatcher

from agent import questions

MIN_LEVEL, MAX_LEVEL = 1, 3
MAX_TRIES = 3  # default when the scene's decision has no max_attempts

SINGLE_CORRECT, BRANCH_CHOICE = "single_correct", "branch_choice"
# Authored action names this code implements (CLAUDE.md: they describe behaviour, they are not code).
SUPPORTED_ACTIONS = {
    "on_correct": {"advance"},
    "on_incorrect": {"retry_with_hint", "retry"},
    "on_max_attempts": {"reveal_correct_and_advance", "advance"},
}

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
    return re.findall(r"[a-z0-9']+", (text or "").lower())


# "sun, no, moon" / "sun... I mean moon": only what comes after the last of these counts.
CORRECTIONS = ("i mean", "i meant", "no", "nope", "actually", "wait", "oops", "sorry")


def settled_words(transcript: str) -> list[str]:
    """The words the child settled on: drop everything before the last self-correction, then drop
    negated words ("not sun", "not the sun"). Falls back to the plain words if nothing is left."""
    said = words(transcript)
    text = " " + " ".join(said) + " "
    cut = max((text.rfind(f" {m} ") + len(m) + 1 for m in CORRECTIONS if f" {m} " in text), default=0)
    kept = text[cut:].split() if cut else said
    if not kept:  # "moon, no": nothing after the correction, keep what came before it
        kept = text[:cut].split()[:-1] if cut else said
    out, i = [], 0
    while i < len(kept):
        if kept[i] in ("not", "don't", "isn't"):
            i += 1
            while i < len(kept) and kept[i] in STOPWORDS:  # "not the sun": skip to the content word
                i += 1
            i += 1  # the negated word itself
            continue
        out.append(kept[i])
        i += 1
    return out or said


DONT_KNOW = ("i don't know", "i dont know", "don't know", "dont know", "i do not know", "dunno",
             "no idea", "not sure")
OFF_TOPIC_MIN_WORDS = 3  # shorter unmatched answers are ordinary wrong answers


def dont_know(transcript: str) -> bool:
    text = " " + " ".join(words(transcript)) + " "
    return any(f" {p} " in text for p in DONT_KNOW)


def off_topic(transcript: str, candidates: list[str]) -> bool:
    """A longer answer with nothing like any target, option or answer ("I like dinosaurs")."""
    said = settled_words(transcript)
    if len(words(transcript)) < OFF_TOPIC_MIN_WORDS or dont_know(transcript) or set(said) & (YES | NO):
        return False
    return not any(heard(c, said) for c in candidates)


CLOSE_RATIO = 0.6  # "shares most letters" with the answer (a hit needs 0.75, see similar())


def attempt_kind(transcript: str, answers: list[str], others: list[str] = (),
                 on_topic: list[str] = (), open_q: bool = False) -> str:
    """How a missed answer may be praised: "none" (silence, "I don't know" or off-topic: no effort
    praise), "close" (shares most letters with an answer, or names another option: "Ooh, close!")
    or "attempt" (a real attempt: "Good try!")."""
    if not words(transcript) or dont_know(transcript):
        return "none"
    if not open_q and off_topic(transcript, [*answers, *others, *on_topic]):
        return "none"
    said = settled_words(transcript)
    if any(heard(o, said) for o in others):
        return "close"
    if any(SequenceMatcher(None, a, w).ratio() >= CLOSE_RATIO for a in answers for w in said if len(w) >= 3):
        return "close"
    return "attempt"


def challenge_attempt(challenge: dict, transcript: str) -> str:
    """attempt_kind for a speaking challenge (count questions: any number is on topic)."""
    qt = questions.qtype(challenge)
    right = questions.answers(challenge)
    others = [o for o in challenge["target_words"] if o not in right] if qt == questions.CHOICE else []
    on_topic = list(challenge["target_words"])
    if qt == questions.COUNT:
        on_topic += list(questions.NUMBERS) + list(questions.DIGITS)
    return attempt_kind(transcript, right, others, on_topic, open_q=qt == questions.OPEN)


EFFORT_LEADS = {"close": "Ooh, close! ", "attempt": "Good try! "}  # "none": no effort praise


def sentences(text: str) -> int:
    return len(re.findall(r"[.!?]+(?=\s|$)", text.strip())) or 1


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
    """A hit means most of the target words were heard (all of them for 1-2 words),
    judged on the words the child settled on."""
    said = settled_words(transcript)
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


def _ok_word(w: str, exclude: set[str]) -> bool:
    return 3 <= len(w) <= 9 and w not in STOPWORDS and w not in exclude and w.isalpha()


def nouns(narration: str, exclude: set[str] = frozenset()) -> list[str]:
    """Likely nouns: the word ending "a/the (+1 adjective) X" ("a quiet forest" -> forest)."""
    def ok(w):
        return _ok_word(w, exclude)

    found = []
    for toks in _sentences(narration):
        lower = [t.lower() for t in toks]
        for i, t in enumerate(lower):
            if t not in ("a", "an", "the", "some"):
                continue
            run = [w for w in lower[i + 1:i + 3] if ok(w)]
            if len(run) == 2 and run[1].endswith("s") and not run[0].endswith("s"):
                run = run[:1]  # "the path reaches": the second word is probably a verb
            if run:
                found.append(run[-1])
    return found


def pick_key_word(narration: str, practised: set[str] = frozenset(),
                  exclude: set[str] = frozenset(), prefer: list[str] = ()) -> str:
    """Simple rule: a practice word (`prefer`) if one occurs in the narration, else prefer nouns,
    then any content word (3-9 letters). Skip words already practised when possible."""
    said = set(words(narration))
    for w in prefer:
        if w in said and w not in exclude:
            return w
    candidates = nouns(narration, exclude) + [w for w in words(narration) if _ok_word(w, exclude)]
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
        prompt = f"Listen: '{phrase}'. Now you try!"
    targets = words(phrase)
    return {"level": level, "prompt": prompt, "target_words": targets,
            "question_type": questions.SAY, "accept": targets,
            "reason": f"Fallback say challenge from the narration at level {level}"}


def decision_type(scene: dict) -> str | None:
    """single_correct, branch_choice, or None for an agent-made speaking challenge."""
    dec = scene.get("decision") or {}
    if dec.get("type"):
        return dec["type"]
    return BRANCH_CHOICE if scene.get("branches") else None


def max_attempts(scene: dict) -> int:
    return (scene.get("decision") or {}).get("max_attempts") or MAX_TRIES


def branch_challenge(scene: dict, proposed: dict | None = None) -> dict:
    words_ = [br["word"] for br in scene["branches"]]
    if proposed:
        label = proposed.get("label") or f"go to the {proposed['word']}"
        prompt = f"Shall we {label[0].lower() + label[1:]}?"
    else:
        prompt = (scene.get("decision") or {}).get("prompt") or \
            "Shall we go to the " + " or the ".join(words_) + "?"
    return {"level": 1, "prompt": prompt, "target_words": words_, "question_type": questions.CHOICE,
            "reason": "Authored story choice"}


def question_challenge(scene: dict, level: int) -> dict:
    """single_correct: the authored prompt. Target words are all the options (not just the answer),
    so the screen never gives the answer away."""
    dec = scene["decision"]
    return {"level": level, "prompt": dec["prompt"], "target_words": [o["word"] for o in dec["options"]],
            "question_type": questions.CHOICE, "reason": "Authored quiz question"}


def scene_choices(scene: dict) -> list[dict] | None:
    """Tap cards: the options on single_correct scenes, the branches on branch scenes, else None."""
    kind = decision_type(scene)
    if kind == SINGLE_CORRECT:
        items = scene["decision"]["options"]
    elif kind == BRANCH_CHOICE:
        items = scene["branches"]
    else:
        return None
    return [{k: it.get(k) for k in ("word", "label", "icon")} for it in items]


# ---------- state ----------

def new_session_state() -> dict:
    return {"level": 1, "hit_streak": 0, "miss_streak": 0, "practised": [], "question_types": []}


def enter_scene(state: dict, scene: dict, narration: str, exclude: set[str] = frozenset()) -> dict:
    """Reset per-scene counters and set the scene's first challenge."""
    state.update(scene_id=scene["id"], tries=0, silences=0, branch_misses=0, proposed=None)
    kind = decision_type(scene)
    state["key_word"] = None
    if kind == BRANCH_CHOICE:
        state["challenge"] = branch_challenge(scene)
    elif kind == SINGLE_CORRECT:
        state["challenge"] = question_challenge(scene, state["level"])
    else:
        state["key_word"] = pick_key_word(narration, set(state["practised"]), exclude,
                                          prefer=state.get("practice_words", []))
        authored = questions.authored_challenge(scene, state["level"])
        if authored:  # the scene's own question comes first
            state["challenge"] = authored
            state["key_word"] = questions.key_word(authored) or state["key_word"]
        else:
            state["challenge"] = make_challenge(narration, state["key_word"], state["level"])
        record_type(state, state["challenge"])
    return state["challenge"]


def record_type(state: dict, challenge: dict) -> None:
    """Question types asked on entering speaking scenes, so the agent can vary them."""
    state.setdefault("question_types", []).append(questions.qtype(challenge))


def _decision(**kw) -> dict:
    d = {"result": None, "log_result": None, "action": None, "feedback": "", "retry": False,
         "next_id": None, "parent_note": None, "challenge": None, "reason": "", "targets": None}
    d.update(kw)
    d["log_result"] = d["log_result"] or d["result"]
    return d


# ---------- the rule ----------

def turn(state: dict, scene: dict, narration: str, transcript: str) -> dict:
    kind = decision_type(scene)
    if kind == BRANCH_CHOICE:
        return _branch_turn(state, scene, transcript)
    if kind == SINGLE_CORRECT:
        return _question_turn(state, scene, transcript)
    return _scene_turn(state, scene, narration, transcript)


def _scene_turn(state: dict, scene: dict, narration: str, transcript: str) -> dict:
    challenge = state["challenge"]
    qt = questions.qtype(challenge)
    phrase = " ".join(challenge["target_words"])
    answer = questions.answer_word(challenge)
    key = state["key_word"]

    if not words(transcript):
        state["silences"] += 1
        if state["silences"] == 1:
            line = f"Listen: '{phrase}'. Now you try!" if qt == questions.SAY else challenge["prompt"]
            return _decision(result="silence", action="retry", retry=True, challenge=challenge,
                             feedback=f"Take your time! {line}",
                             reason="First silence: gentle encouragement, not counted as a miss")
        # Later silences count as a miss.

    state["tries"] += 1
    unsure = dont_know(transcript)
    lead = EFFORT_LEADS.get(challenge_attempt(challenge, transcript), "")
    candidates = list(challenge["target_words"]) + list(challenge.get("accept") or [])
    if qt == questions.COUNT:
        candidates += list(questions.NUMBERS) + list(questions.DIGITS)
    stray = qt != questions.OPEN and off_topic(transcript, candidates)
    if not unsure and questions.is_answer(challenge, transcript):
        state["hit_streak"] += 1
        state["miss_streak"] = 0
        if qt == questions.SAY:
            reason = f"Heard '{phrase}' at level {challenge['level']}"
            named = phrase if len(challenge["target_words"]) <= 4 else key
            feedback = f"You said '{named}'!"
        elif qt == questions.OPEN:
            reason = f"Gave an answer of two or more words to an open question at level {challenge['level']}"
            feedback = "What a lovely idea!"
        else:
            reason = f"Answered the {qt} question with '{answer}' at level {challenge['level']}"
            feedback = f"Yes, {answer}! Well done!"
        if state["hit_streak"] >= 2:
            if state["level"] < MAX_LEVEL:
                reason += f"; two hits in a row, level up to {state['level'] + 1}"
            state["level"] = min(MAX_LEVEL, state["level"] + 1)
            state["hit_streak"] = 0
        state["practised"] = sorted(set(state["practised"]) | {key})
        return _decision(result="hit", action="advance", next_id=scene.get("next"),
                         feedback=feedback, reason=reason)

    state["miss_streak"] += 1
    state["hit_streak"] = 0
    level_down = state["miss_streak"] >= 2
    if level_down:
        state["level"] = max(MIN_LEVEL, state["level"] - 1)
        state["miss_streak"] = 0

    limit = max_attempts(scene)
    if state["tries"] >= limit:  # effort praise only after a real attempt, else a neutral reveal
        tried = bool(lead)
        model = phrase if qt == questions.SAY else answer
        if qt == questions.OPEN:  # no single answer to model
            feedback = ("Good try! " if tried else "") + "Let's see what happens next."
        else:  # model the answer; at most two short sentences (the length rule)
            feedback = f"Good try! It's '{model}'." if tried else f"Let's find out: it's '{model}'!"
        return _decision(result="miss", action="move_on", next_id=scene.get("next"),
                         feedback=feedback,
                         parent_note=f"Struggled with '{key}' - practise together",
                         reason=f"'{key}' not heard after {limit} tries; moved on")

    if stray:  # off-topic: acknowledge kindly and ask the same question again (no "nice try")
        return _decision(result="miss", action="retry", retry=True, challenge=challenge,
                         feedback=f"That sounds fun! {challenge['prompt']}",
                         reason=f"Off-topic answer (try {state['tries']} of {limit}); asked the same question again")
    new = questions.step_down(challenge, narration, key, state["level"])
    state["challenge"] = new
    if unsure:  # the help line carries the clue or the easier question itself
        return _decision(result="miss", action="retry_with_hint", retry=True, challenge=new,
                         feedback=f"That's okay! {new['prompt']}",
                         reason=f"Child was not sure (try {state['tries']} of {limit}); "
                                f"gave {questions.qtype(new)} help")
    if new is challenge:
        return _decision(result="miss", action="retry", retry=True, challenge=challenge,
                         feedback=f"{lead}Listen: '{phrase}'. Now you try!",
                         reason=f"'{phrase}' not heard (try {state['tries']} of {limit}); modelled it again")
    if qt == questions.SAY:
        target = " ".join(new["target_words"])
        return _decision(result="miss", action="retry_with_hint", retry=True, challenge=new,
                         feedback=f"{lead}Listen: '{target}'. Now you try!",
                         reason=f"Two misses in a row; easier level {state['level']} with a hint")
    new_type = questions.qtype(new)
    # The hint always names the answer: the say-it prompt, or a choice that contains it.
    feedback = f"{lead}{new['prompt']}"
    return _decision(result="miss", action="retry_with_hint", retry=True, challenge=new,
                     feedback=feedback,
                     reason=f"{qt} question not answered (try {state['tries']} of {limit}); "
                            f"stepped down to {new_type}"
                            + (f", level {state['level']}" if level_down else ""))


def _question_turn(state: dict, scene: dict, transcript: str) -> dict:
    """single_correct: assess against correct_word. Does not touch the level or streaks."""
    dec = scene["decision"]
    challenge = state["challenge"]
    correct = dec["correct_word"]
    others = [o["word"] for o in dec["options"] if o["word"] != correct] + dec.get("incorrect_words", [])
    said = words(transcript)

    if not said:
        state["silences"] += 1
        if state["silences"] == 1:
            return _decision(result="silence", action="retry", retry=True, challenge=challenge,
                             feedback="Take your time! " + dec["prompt"],
                             reason="First silence: repeated the question, not counted as a miss")

    state["tries"] += 1
    settled = settled_words(transcript)
    if not dont_know(transcript) and heard(correct, settled) and not any(heard(o, settled) for o in others):
        return _decision(result="hit", action="advance", next_id=scene.get("next"), targets=[correct],
                         feedback=f"Yes, the {correct}! Well done!",
                         reason=f"Answered '{correct}' correctly on try {state['tries']}")

    limit = max_attempts(scene)
    kind = attempt_kind(transcript, [correct], others)
    if state["tries"] >= limit:  # effort praise only after a real attempt, else a neutral reveal
        return _decision(result="miss", action="move_on", next_id=scene.get("next"), targets=[correct],
                         feedback=f"Good try! It's the {correct}." if kind != "none"
                         else f"Let's find out: it's the {correct}!", tail=f"It's the {correct}.",
                         parent_note=f"Needed help with: {dec['prompt']} (answer: '{correct}') - talk about it together",
                         reason=f"Not answered after {limit} tries; revealed '{correct}' and moved on")

    if off_topic(transcript, [correct, *others]):  # acknowledge, then the same question
        return _decision(result="miss", action="retry", retry=True, challenge=challenge, targets=[correct],
                         feedback=f"That sounds fun! {dec['prompt']}", tail=dec["prompt"], off_topic=True,
                         reason=f"Off-topic answer (try {state['tries']} of {limit}); asked the question again")
    hinted = dec.get("on_incorrect", "retry_with_hint") == "retry_with_hint"
    tail = quiz_hint(dec, state["tries"]) if hinted else dec["prompt"]
    lead = "That's okay! " if dont_know(transcript) else EFFORT_LEADS.get(kind, "")
    return _decision(result="miss", action="retry_with_hint" if hinted else "retry", retry=True,
                     challenge=challenge, targets=[correct], feedback=f"{lead}{tail}", tail=tail,
                     reason=f"Answer was not '{correct}' (try {state['tries']} of {limit}); "
                            + (f"gave hint {state['tries']}" if hinted else "asked again"))


def quiz_hint(dec: dict, tries: int) -> str:
    """One short sentence. First miss: the authored hint's first sentence. Later misses: a different,
    simpler hint that names the answer."""
    if tries <= 1 and dec.get("hint"):
        return re.split(r"(?<=[.!?])\s+", dec["hint"].strip())[0]
    return f"Can you say '{dec['correct_word']}'?"


def _match_branch(scene: dict, said: list[str]) -> dict | None:
    """First branch word heard, in the order the child said things."""
    for w in said:
        for br in scene["branches"]:
            if similar(br["word"], w):
                return br
    return None


def choice_line(state: dict, word: str) -> str:
    """Follow the child's pick; never sounds like a right answer (a choice has no right or wrong)."""
    name = (state.get("child") or {}).get("child_name")
    return f"The {word} it is, {name}! Off we go." if name else f"The {word} it is! Off we go."


def _branch_turn(state: dict, scene: dict, transcript: str) -> dict:
    branches = scene["branches"]
    said = words(transcript)

    chosen = _match_branch(scene, settled_words(transcript))
    if chosen:
        return _decision(result="hit", action="advance", next_id=chosen["next"],
                         feedback=choice_line(state, chosen["word"]), chosen=chosen["word"],
                         reason=f"Chose '{chosen['word']}'")

    if not said and state["silences"] == 0:
        state["silences"] += 1
        return _decision(result="silence", action="retry", retry=True, challenge=state["challenge"],
                         feedback="Take your time! " + state["challenge"]["prompt"],
                         reason="First silence: repeated the options, not counted as a miss")

    if state["proposed"]:
        proposed = next(br for br in branches if br["word"] == state["proposed"])
        other = next(br for br in branches if br is not proposed)
        declined = bool(set(said) & NO and not set(said) & YES)
        accepted = bool(set(said) & YES) and not declined
        pick = other if declined else proposed
        # Only an accepted proposal is the child's choice; otherwise code picked: "Let's try the boat!"
        line = choice_line(state, pick["word"]) if accepted else f"Let's try the {pick['word']}!"
        return _decision(result="hit", log_result="choice", action="advance", next_id=pick["next"],
                         feedback=line, chosen=pick["word"], chosen_by_child=accepted,
                         reason=f"Proposed '{proposed['word']}'; "
                                + (f"child said no, took '{pick['word']}'" if declined else "went with it"))

    # Neither word: not counted as a miss.
    state["branch_misses"] += 1
    if state["branch_misses"] == 1:
        ch = branch_challenge(scene)
        state["challenge"] = ch
        return _decision(result="miss", log_result="no_choice", action="retry", retry=True,
                         challenge=ch, feedback=("That's okay! " if dont_know(transcript) else
                                                 "That sounds fun! " if off_topic(transcript, [
                                                     b["word"] for b in branches]) else
                                                 "Ooh, which way? ") + ch["prompt"],
                         reason="No branch word heard; repeated the options (not a miss)")

    proposed = branches[0]
    state["proposed"] = proposed["word"]
    ch = branch_challenge(scene, proposed=proposed)
    state["challenge"] = ch
    return _decision(result="miss", log_result="no_choice", action="retry", retry=True,
                     challenge=ch, feedback=ch["prompt"],
                     reason=f"Still no branch word; proposed '{proposed['word']}' (not a miss)")
