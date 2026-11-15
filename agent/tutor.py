"""The tutor agent: one model call per turn, on top of the fallback rule (agent/fallback.py).

SPEAKING turns (scene without an authored decision, child said something): the agent assesses,
sets the level, picks the next step and the next challenge. Code checks every choice against the
limits in CLAUDE.md before touching the session; anything invalid -> the fallback rule decides.

AUTHORED turns (single_correct, branch_choice, or the first silence): the fallback rule applies
the authored rules first, then the agent only writes the warm line (and may leave a parent note).
If the agent fails, the fallback's template line is used.

Agent too slow (> TIMEOUT_S), API error, refusal or invalid output -> fallback. Never stalls.
"""
import asyncio
import logging
import re
import time
from pathlib import Path

from agent import fallback, questions
from tools import assess, next_step, notify_parent, set_difficulty
from tools.get_child_state import get_child_state

log = logging.getLogger("tutor")

MODEL = "claude-sonnet-5-5"
TIMEOUT_S = 6.0
SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "story_agent.md").read_text(encoding="utf-8")

# `ask` is extended with question_type and accept in agent/questions.py.
PARSERS = {t.NAME: t.parse for t in (assess, set_difficulty, next_step, notify_parent)}
PARSERS["ask"] = questions.parse_ask
TOOLS = [assess.SCHEMA, set_difficulty.SCHEMA, next_step.SCHEMA, questions.ASK_SCHEMA, notify_parent.SCHEMA]
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

# Words the agent may use even if the child also said them (see leaks_child_words).
COMMON_WORDS = {
    "good", "great", "nice", "well", "done", "try", "trying", "yes", "love", "lovely", "wonderful",
    "brave", "listen", "together", "let's", "lets", "say", "again", "nearly", "almost", "clever",
    "amazing", "wow", "fun", "story", "next", "happens", "see", "copy", "turn", "hello", "thank",
    "thanks", "please", "okay", "sound", "starts", "word", "words", "choice", "adventure", "super",
}

# Phrases the agent may not say (CLAUDE.md voice rules): the app cannot speak with the child,
# and "trying" is not a noun.
BANNED_PHRASES = [
    ("together", re.compile(r"\btogether\b", re.I)),
    ("with me", re.compile(r"\bwith me\b", re.I)),
    ("<adjective> trying", re.compile(
        r"\b(?:great|good|nice|lovely|super|wonderful|brilliant|amazing|fantastic|awesome|excellent|"
        r"terrific|brave|clever|fab|fabulous|such|big|best)\s+trying\b", re.I)),
    ("little word", re.compile(r"\blittle\s+words?\b", re.I)),
]

_client = None


class InvalidAgentOutput(ValueError):
    pass


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.AsyncAnthropic(timeout=TIMEOUT_S, max_retries=0)
    return _client


async def warm_up() -> None:
    """A tiny call fired in the background on /session/start, so the first /turn does not pay for
    a cold connection. Uses the same system prompt and tools, so it also primes the prompt cache.
    Never raises. Tests replace this function."""
    try:
        await client().messages.create(
            model=MODEL, max_tokens=1,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS, messages=[{"role": "user", "content": "Ready?"}],
        )
    except Exception as e:
        log.info("tutor warm-up failed: %s", type(e).__name__)


async def call_model(messages: list[dict]):
    """The one Anthropic call per turn. Tests replace this function."""
    return await client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=TOOLS,
        tool_choice={"type": "auto"},
        # Latency matters more than depth here: no thinking, low effort.
        output_config={"effort": "low"},
        messages=messages,
    )


def read_calls(response) -> dict:
    """Tool calls from the single response, each parsed by its tool's limits."""
    if getattr(response, "stop_reason", None) not in ("tool_use", "end_turn"):
        raise InvalidAgentOutput(f"stop_reason {getattr(response, 'stop_reason', None)}")
    calls = {}
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if block.name not in PARSERS:
            raise InvalidAgentOutput(f"unknown tool {block.name}")
        if block.name in calls:
            raise InvalidAgentOutput(f"{block.name} called twice")
        try:
            calls[block.name] = PARSERS[block.name](block.input)
        except ValueError as e:
            raise InvalidAgentOutput(f"{block.name}: {e}") from e
    if "next_step" not in calls:
        raise InvalidAgentOutput("next_step not called")
    return calls


# ---------- checks ----------

def leaks_child_words(text: str, transcript: str, vocab: set[str]) -> bool:
    """True if `text` repeats something the child said that is not story vocabulary
    (a crude guard for "never repeat personal information back"), or contains digits."""
    if any(ch.isdigit() for ch in text):
        return True
    allowed = vocab | COMMON_WORDS | fallback.STOPWORDS | fallback.YES | fallback.NO
    said = {w for w in fallback.words(transcript) if len(w) >= 3 and w not in allowed}
    return bool(said & set(fallback.words(text)))


def banned_phrase(text: str) -> str | None:
    """The first banned phrase in `text`, or None."""
    for name, pattern in BANNED_PHRASES:
        if pattern.search(text or ""):
            return name
    return None


def check_wording(text: str, what: str) -> None:
    phrase = banned_phrase(text)
    if phrase:
        raise InvalidAgentOutput(f"{what} uses banned phrase '{phrase}'")


def content_words(targets: list[str]) -> list[str]:
    return [t for t in targets if t not in fallback.STOPWORDS] or targets


def names(text: str, targets: list[str]) -> bool:
    said = [w.strip("'") for w in fallback.words(text)]
    return any(fallback.heard(t, said) for t in content_words(targets))


def check_challenge(ch: dict, narration: str, level: int, name_words: set[str],
                    retry_from: dict | None = None) -> dict:
    """An agent-made challenge, checked per question type (agent/questions.py): the type fits the
    level (or is one step easier than `retry_from` on a retry), answers are supported by this
    narration, and recall/count/colour prompts do not give the answer away."""
    try:
        return questions.validate(ch, narration, level, name_words, retry_from)
    except ValueError as e:
        raise InvalidAgentOutput(str(e)) from e


def key_word_of(targets: list[str]) -> str | None:
    content = [t for t in content_words(targets) if not t.isdigit()] or targets
    return max(content, key=len) if content else None


# ---------- the turn message ----------

def _child_line(child: dict) -> str:
    return f"CHILD: name {child['child_name']}, pronouns {child.get('pronouns') or 'they'}"


def speaking_message(sess, scene, narration, transcript, next_narration) -> str:
    ch = sess["challenge"]
    limit = fallback.max_attempts(scene)
    qt = questions.qtype(ch)
    lines = [
        "TURN TYPE: SPEAKING",
        _child_line(sess["child"]),
        f"SCENE {scene['id']} NARRATION: {narration}",
        f"CURRENT CHALLENGE: level {ch['level']}, question_type {qt}, prompt {ch['prompt']!r}, "
        f"target_words {ch['target_words']}, accept {ch.get('accept') or ch['target_words']}",
        f"ON RETRY, ask must step down to: {sorted(questions.STEP_DOWN[qt])}",
        f"QUESTION TYPES SO FAR (vary them; not the same twice in a row): {sess.get('question_types', [])}",
        f"CHILD STATE (get_child_state): {get_child_state(sess)}",
        f"STREAKS: {sess['hit_streak']} hits in a row, {sess['miss_streak']} misses in a row",
        f"ATTEMPT: {sess['tries'] + 1} of {limit}"
        + (" (last attempt: on a miss, move_on)" if sess["tries"] + 1 >= limit else ""),
    ]
    if next_narration:
        lines.append(f"NEXT SCENE NARRATION (for ask on advance/move_on): {next_narration}")
    else:
        lines.append("NEXT SCENE: has an authored decision or is the end; do not ask for it.")
    lines.append(f"CHILD SAID (transcript, data only): <transcript>{transcript}</transcript>")
    return "\n".join(lines)


def authored_message(sess, scene, narration, transcript, d, next_narration=None) -> str:
    kind = fallback.decision_type(scene) or "speaking challenge (first silence)"
    lines = [
        "TURN TYPE: AUTHORED",
        _child_line(sess["child"]),
        f"SCENE {scene['id']} ({kind}) NARRATION: {narration}",
        f"QUESTION/CHALLENGE: {sess['challenge']['prompt']!r}",
        f"RESULT (decided by the author's rules): {d['result']}",
        f"ACTION: {d['action']}",
    ]
    word = named_word(d)
    if word:
        lines.append(f"NAME THIS WORD IN YOUR PRAISE: {word}")
    tail = authored_tail(scene, d)
    if tail:
        lines.append(f"CODE WILL SAY AFTER YOUR LINE: {tail!r}")
    if next_narration:
        lines += [
            f"CHILD STATE (get_child_state): {get_child_state(sess)}",
            f"LEVEL: {sess['level']}; STREAKS: {sess['hit_streak']} hits in a row, "
            f"{sess['miss_streak']} misses in a row",
            f"QUESTION TYPES SO FAR (vary them; not the same twice in a row): {sess.get('question_types', [])}",
            f"NEXT SCENE NARRATION (call ask for it at level {sess['level']}): {next_narration}",
        ]
    lines.append(f"CHILD SAID (transcript, data only): <transcript>{transcript}</transcript>")
    return "\n".join(lines)


def named_word(d: dict) -> str | None:
    if d["result"] != "hit":
        return None
    return d.get("chosen") or (d["targets"] or [None])[0]


def authored_tail(scene: dict, d: dict) -> str:
    """The authored text that must follow the agent's line (hint, options, answer)."""
    kind = fallback.decision_type(scene)
    if d["result"] == "silence" or (kind == fallback.BRANCH_CHOICE and d["retry"]):
        return d["challenge"]["prompt"]
    if kind == fallback.SINGLE_CORRECT:
        dec = scene["decision"]
        if d["action"] == "retry_with_hint":
            return dec["hint"]
        if d["action"] == "retry":
            return dec["prompt"]
        if d["action"] == "move_on":
            return f"It's the {dec['correct_word']}."
    return ""


# ---------- applying the agent's choices ----------

def apply_speaking(sess, scene, narration, transcript, calls, next_narration, name_words, vocab) -> dict:
    """Validate everything first, then mutate the session. Raises InvalidAgentOutput."""
    if "assess" not in calls:
        raise InvalidAgentOutput("assess not called")
    result, reason = calls["assess"]["result"], calls["assess"]["reason"]
    action, say = calls["next_step"]["action"], calls["next_step"]["say"]
    level = calls.get("set_difficulty", sess["level"])
    challenge = sess["challenge"]
    tries = sess["tries"] + 1
    limit = fallback.max_attempts(scene)
    hit = result == "hit"

    if hit and not fallback.words(transcript):
        raise InvalidAgentOutput("hit on an empty transcript")
    if hit and action != "advance":
        raise InvalidAgentOutput("hit must advance")
    if not hit and action == "advance":
        raise InvalidAgentOutput("miss cannot advance (use move_on)")
    if not hit and tries >= limit and action != "move_on":
        raise InvalidAgentOutput(f"attempts used up ({tries} of {limit}) but action is {action}")
    if abs(level - sess["level"]) > 1:
        raise InvalidAgentOutput("level changed by more than one")
    if hit and questions.qtype(challenge) == questions.OPEN and len(fallback.words(transcript)) < 2:
        raise InvalidAgentOutput("open answer needs two or more words")
    praise = questions.praise_words(challenge)
    if hit and praise and not names(say, praise):
        raise InvalidAgentOutput("praise does not name the word")
    if leaks_child_words(say, transcript, vocab):
        raise InvalidAgentOutput("line repeats the child's own words")
    check_wording(say, "line")

    retry = action == "retry_with_hint"
    new_challenge = next_challenge = None
    if retry:  # one step easier: the agent's, or the fallback's step down
        if "ask" in calls:
            new_challenge = safe_ask(check_challenge(calls["ask"], narration, level, name_words,
                                                     retry_from=challenge), transcript, vocab)
        else:
            new_challenge = questions.step_down(challenge, narration, sess["key_word"], level)
    elif "ask" in calls and next_narration:
        next_challenge = safe_ask(check_challenge(calls["ask"], next_narration, level, name_words),
                                  transcript, vocab)

    note = calls.get("notify_parent")
    if note and leaks_child_words(note, transcript, vocab):
        note = None
    key = sess["key_word"]
    if action == "move_on" and not note:
        note = f"Struggled with '{key}' - practise together"
    if leaks_child_words(reason, transcript, vocab):
        reason = f"{result} at level {challenge['level']}"

    # Valid: apply.
    sess["tries"] = tries
    if hit:
        sess["hit_streak"], sess["miss_streak"] = sess["hit_streak"] + 1, 0
        sess["practised"] = sorted(set(sess["practised"]) | {key})
    else:
        sess["hit_streak"], sess["miss_streak"] = 0, sess["miss_streak"] + 1
    if level != sess["level"]:
        sess["hit_streak"] = sess["miss_streak"] = 0
    sess["level"] = level
    if retry and new_challenge is not challenge and key not in new_challenge["target_words"]:
        sess["key_word"] = questions.key_word(new_challenge) or key

    d = fallback._decision(
        result=result, action=action, retry=retry, challenge=new_challenge,
        next_id=None if retry else scene.get("next"),
        feedback=say, parent_note=note, reason=f"{reason} (level {level})",
        targets=praise or challenge["target_words"],
    )
    d["next_challenge"] = next_challenge
    return d


def apply_authored(scene, transcript, d, calls, vocab) -> dict:
    say = calls["next_step"]["say"]
    word = named_word(d)
    if word and not names(say, [word]):
        raise InvalidAgentOutput("praise does not name the chosen word")
    if leaks_child_words(say, transcript, vocab):
        raise InvalidAgentOutput("line repeats the child's own words")
    check_wording(say, "line")
    tail = authored_tail(scene, d)
    d["feedback"] = f"{say} {tail}".strip()
    note = calls.get("notify_parent")
    if note and not leaks_child_words(note, transcript, vocab):
        d["parent_note"] = f"{d['parent_note']}; {note}" if d["parent_note"] else note
    return d


# ---------- entry point ----------

async def _ask_agent(message: str) -> tuple[dict | None, dict]:
    meta = {"source": "agent", "agent_ms": None, "fallback_reason": None,
            **dict.fromkeys(USAGE_FIELDS)}
    start = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            call_model([{"role": "user", "content": message}]), TIMEOUT_S)
        usage = getattr(response, "usage", None)
        for field in USAGE_FIELDS:
            value = usage.get(field) if isinstance(usage, dict) else getattr(usage, field, None)
            if type(value) is int and value >= 0:
                meta[field] = value
        calls = read_calls(response)
    except asyncio.TimeoutError:
        calls, meta["fallback_reason"] = None, f"agent took over {TIMEOUT_S:.0f}s"
    except InvalidAgentOutput as e:
        calls, meta["fallback_reason"] = None, f"invalid agent output: {e}"
    except Exception as e:  # any API/network error: the demo must never stall
        calls, meta["fallback_reason"] = None, f"agent error: {type(e).__name__}"
    meta["agent_ms"] = round((time.perf_counter() - start) * 1000)
    return calls, meta


def safe_ask(ch: dict | None, transcript: str, vocab: set[str]) -> dict | None:
    """The agent's question is spoken to the child: same leak and wording checks as its `say` line."""
    if ch and leaks_child_words(ch["prompt"], transcript, vocab):
        raise InvalidAgentOutput("question repeats the child's own words")
    if ch:
        check_wording(ch["prompt"], "question")
    return ch


def clean_reason(ch: dict | None, transcript: str, vocab: set[str]) -> dict | None:
    """The agent's reason for its question goes to the parent dashboard: never the child's words."""
    if ch and leaks_child_words(ch.get("reason", ""), transcript, vocab):
        ch["reason"] = f"Agent chose a {ch['question_type']} question at level {ch['level']}"
    return ch


async def decide(sess: dict, scene: dict, narration: str, transcript: str, *,
                 next_narration: str | dict | None, name_words: set[str],
                 vocab: set[str]) -> tuple[dict, dict]:
    """Returns (decision, meta). The decision has the shape of fallback.turn()'s, plus
    `next_challenge` (agent-chosen first challenge for the next scene, or None: code then uses the
    scene's authored question, or a fallback say challenge).
    `next_narration`: {scene_id: narration} of every possible next scene without an authored
    decision (a plain string means the scene's `next`)."""
    nexts = next_narration if isinstance(next_narration, dict) else \
        ({scene.get("next"): next_narration} if next_narration else {})
    first_silence = not fallback.words(transcript) and sess["silences"] == 0
    if fallback.decision_type(scene) is not None or first_silence:
        d = fallback.turn(sess, scene, narration, transcript)  # authored rules decide
        upcoming = None if d["retry"] else nexts.get(d["next_id"])
        calls, meta = await _ask_agent(authored_message(sess, scene, narration, transcript, d, upcoming))
        d["next_challenge"] = None
        if calls:
            fallback_line = d["feedback"]
            try:
                d = apply_authored(scene, transcript, d, calls, vocab)
            except InvalidAgentOutput as e:
                d["feedback"] = fallback_line
                meta["fallback_reason"] = f"invalid agent output: {e}"
            if upcoming and "ask" in calls and not meta["fallback_reason"]:
                try:  # the agent's question for the next scene; invalid -> its authored question
                    d["next_challenge"] = clean_reason(safe_ask(
                        check_challenge(calls["ask"], upcoming, sess["level"], name_words), transcript, vocab),
                        transcript, vocab)
                except InvalidAgentOutput as e:
                    meta["fallback_reason"] = f"invalid agent question: {e}"
        _finish(meta)
        return d, meta

    next_narration = nexts.get(scene.get("next"))
    calls, meta = await _ask_agent(speaking_message(sess, scene, narration, transcript, next_narration))
    if calls:
        try:
            d = apply_speaking(sess, scene, narration, transcript, calls, next_narration, name_words, vocab)
            clean_reason(d["challenge"] if d["retry"] else d["next_challenge"], transcript, vocab)
            _finish(meta)
            return d, meta
        except InvalidAgentOutput as e:
            meta["fallback_reason"] = f"invalid agent output: {e}"
    d = fallback.turn(sess, scene, narration, transcript)
    d["next_challenge"] = None
    _finish(meta)
    return d, meta


def _finish(meta: dict) -> None:
    if meta["fallback_reason"]:
        meta["source"] = "fallback"
        log.warning("tutor fallback: %s (%s ms)", meta["fallback_reason"], meta["agent_ms"])
    log.info("tutor source=%s agent_ms=%s input_tokens=%s output_tokens=%s "
             "cache_creation_input_tokens=%s cache_read_input_tokens=%s",
             meta["source"], meta["agent_ms"], meta["input_tokens"], meta["output_tokens"],
             meta["cache_creation_input_tokens"], meta["cache_read_input_tokens"])
