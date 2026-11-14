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
import time
from pathlib import Path

from agent import fallback
from tools import ask, assess, next_step, notify_parent, set_difficulty
from tools.get_child_state import get_child_state

log = logging.getLogger("tutor")

MODEL = "claude-sonnet-5-5"
TIMEOUT_S = 6.0
SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "story_agent.md").read_text(encoding="utf-8")

PARSERS = {t.NAME: t.parse for t in (ask, assess, set_difficulty, next_step, notify_parent)}
TOOLS = [t.SCHEMA for t in (assess, set_difficulty, next_step, ask, notify_parent)]
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

# Words the agent may use even if the child also said them (see leaks_child_words).
COMMON_WORDS = {
    "good", "great", "nice", "well", "done", "try", "trying", "yes", "love", "lovely", "wonderful",
    "brave", "listen", "together", "let's", "lets", "say", "again", "nearly", "almost", "clever",
    "amazing", "wow", "fun", "story", "next", "happens", "see", "copy", "turn", "hello", "thank",
    "thanks", "please", "okay", "sound", "starts", "word", "words", "choice", "adventure", "super",
}

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
        thinking={"type": "between_tools"},
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


def content_words(targets: list[str]) -> list[str]:
    return [t for t in targets if t not in fallback.STOPWORDS] or targets


def names(text: str, targets: list[str]) -> bool:
    said = [w.strip("'") for w in fallback.words(text)]
    return any(fallback.heard(t, said) for t in content_words(targets))


def check_challenge(ch: dict, narration: str, level: int, name_words: set[str]) -> dict:
    """An agent-made challenge must use words from this narration at the set level."""
    narr = set(fallback.words(narration))
    if ch["level"] != level:
        raise InvalidAgentOutput(f"ask level {ch['level']} but level is {level}")
    missing = [w for w in ch["target_words"] if w not in narr]
    if missing:
        raise InvalidAgentOutput(f"target words not in narration: {missing}")
    if set(ch["target_words"]) <= name_words:
        raise InvalidAgentOutput("target is the child's name")
    if not set(ch["target_words"]) <= {w.strip("'") for w in fallback.words(ch["prompt"])}:
        raise InvalidAgentOutput("prompt does not contain the target words")
    return ch


def key_word_of(targets: list[str]) -> str:
    return max(content_words(targets), key=len)


# ---------- the turn message ----------

def _child_line(child: dict) -> str:
    return f"CHILD: name {child['child_name']}, pronouns {child.get('pronouns') or 'they'}"


def speaking_message(sess, scene, narration, transcript, next_narration) -> str:
    ch = sess["challenge"]
    limit = fallback.max_attempts(scene)
    lines = [
        "TURN TYPE: SPEAKING",
        _child_line(sess["child"]),
        f"SCENE {scene['id']} NARRATION: {narration}",
        f"CURRENT CHALLENGE: level {ch['level']}, prompt {ch['prompt']!r}, "
        f"target_words {ch['target_words']}",
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


def authored_message(sess, scene, narration, transcript, d) -> str:
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
    if hit and not names(say, challenge["target_words"]):
        raise InvalidAgentOutput("praise does not name the word")
    if leaks_child_words(say, transcript, vocab):
        raise InvalidAgentOutput("line repeats the child's own words")

    retry = action == "retry_with_hint"
    new_challenge = next_challenge = None
    if retry:
        if "ask" in calls:
            new_challenge = check_challenge(calls["ask"], narration, level, name_words)
        elif level == challenge["level"]:
            new_challenge = challenge
        else:
            new_challenge = fallback.make_challenge(narration, sess["key_word"], level, hint=True)
    elif "ask" in calls and next_narration:
        next_challenge = check_challenge(calls["ask"], next_narration, level, name_words)

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
        sess["key_word"] = key_word_of(new_challenge["target_words"])

    d = fallback._decision(
        result=result, action=action, retry=retry, challenge=new_challenge,
        next_id=None if retry else scene.get("next"),
        feedback=say, parent_note=note, reason=f"{reason} (level {level})",
        targets=challenge["target_words"],
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


async def decide(sess: dict, scene: dict, narration: str, transcript: str, *,
                 next_narration: str | None, name_words: set[str], vocab: set[str]) -> tuple[dict, dict]:
    """Returns (decision, meta). The decision has the shape of fallback.turn()'s, plus
    `next_challenge` (agent-chosen first challenge for the next scene, or None)."""
    first_silence = not fallback.words(transcript) and sess["silences"] == 0
    if fallback.decision_type(scene) is not None or first_silence:
        d = fallback.turn(sess, scene, narration, transcript)  # authored rules decide
        calls, meta = await _ask_agent(authored_message(sess, scene, narration, transcript, d))
        if calls:
            fallback_line = d["feedback"]
            try:
                d = apply_authored(scene, transcript, d, calls, vocab)
            except InvalidAgentOutput as e:
                d["feedback"] = fallback_line
                meta["fallback_reason"] = f"invalid agent output: {e}"
        _finish(meta)
        d.setdefault("next_challenge", None)
        return d, meta

    calls, meta = await _ask_agent(speaking_message(sess, scene, narration, transcript, next_narration))
    if calls:
        try:
            d = apply_speaking(sess, scene, narration, transcript, calls, next_narration, name_words, vocab)
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
