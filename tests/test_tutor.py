"""Tutor agent tests. The Anthropic call is mocked (tutor.call_model); nothing goes over the network.
Run:  pytest tests/test_tutor.py -v"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import fallback as fb
from agent import tutor
from agent.main import app

client = TestClient(app)
START = json.loads(open("contract/session_start_request.json").read())

SCENE = {"id": "s1", "narration": "Mia steps into a quiet forest. A sleepy owl hoots hello.", "next": "s2"}
NEXT_NARRATION = "The moon rises over the silver river. Mia waves goodnight."
QUESTION = {"id": "q", "narration": "A sun and a moon.", "next": "s3", "decision": {
    "type": "single_correct", "prompt": "Which one shines in the day: sun or moon?",
    "options": [{"word": "sun", "label": "Sun", "icon": "sun"}, {"word": "moon", "label": "Moon", "icon": "moon"}],
    "correct_word": "sun", "incorrect_words": ["moon"], "on_correct": "advance",
    "on_incorrect": "retry_with_hint", "max_attempts": 3, "on_max_attempts": "reveal_correct_and_advance",
    "hint": "The sun shines in the daytime. Can you say sun?"}}
BRANCH = {"id": "b", "narration": "A bridge and a boat.",
          "decision": {"type": "branch_choice", "prompt": "Bridge or boat?"}, "branches": [
    {"word": "bridge", "label": "Cross the bridge", "icon": "bridge", "next": "x"},
    {"word": "boat", "label": "Take the boat", "icon": "boat", "next": "y"}]}


# ---------- fake model ----------

class FakeModel:
    def __init__(self, *calls, delay=0.0, stop_reason="tool_use", usage=None):
        self.calls, self.delay, self.stop_reason, self.messages = calls, delay, stop_reason, []
        self.usage = usage

    async def __call__(self, messages):
        self.messages.append(messages)
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(stop_reason=self.stop_reason, usage=self.usage, content=[
            SimpleNamespace(type="text", text="ignored"),
            *(SimpleNamespace(type="tool_use", name=n, input=i) for n, i in self.calls)])


def use(monkeypatch, *calls, **kw) -> FakeModel:
    model = FakeModel(*calls, **kw)
    monkeypatch.setattr(tutor, "call_model", model)
    return model


def hit(say, level=1, **extra):
    return [("assess", {"result": "hit", "reason": "Said the word"}), ("set_difficulty", {"level": level}),
            ("next_step", {"action": "advance", "say": say}), *extra.get("more", [])]


def miss(action, say, level=1, *more):
    return [("assess", {"result": "miss", "reason": "Target not heard"}), ("set_difficulty", {"level": level}),
            ("next_step", {"action": action, "say": say}), *more]


def session(scene=SCENE, level=1):
    s = {"child": {"child_name": "Mia", "pronouns": "she", "avatar": {}}, "log": [], **fb.new_session_state()}
    s["level"] = level
    fb.enter_scene(s, scene, scene["narration"], exclude={"mia"})
    return s


def decide(s, transcript, scene=SCENE, next_narration=None):
    vocab = set(fb.words(json.dumps(scene))) | set(fb.words(next_narration or "")) | {"mia"}
    return asyncio.run(tutor.decide(s, scene, scene["narration"], transcript,
                                    next_narration=next_narration, name_words={"mia"}, vocab=vocab))


# ---------- speaking turns: the agent decides ----------

def test_agent_hit_over_http_uses_agent_line_and_logs_turn_time(monkeypatch):
    sess = client.post("/session/start", json=START).json()
    word = sess["scene"]["challenge"]["target_words"][0]
    model = use(monkeypatch, *hit(f"You said '{word}', Mia, well done!"))
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": word}).json()
    assert r["result"] == "hit" and r["feedback"] == f"You said '{word}', Mia, well done!"
    assert r["scene"]["id"] == "s2"
    msg = model.messages[0][0]["content"]
    assert "TURN TYPE: SPEAKING" in msg and f"<transcript>{word}</transcript>" in msg
    assert "CHILD STATE (get_child_state)" in msg
    from agent.main import SESSIONS
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert entry["source"] == "agent" and entry["fallback_reason"] is None
    assert isinstance(entry["agent_ms"], int) and isinstance(entry["turn_ms"], int)


def test_agent_accepts_near_miss(monkeypatch):
    use(monkeypatch, *hit("You said 'forest'!"))
    s = session()
    d, meta = decide(s, "fowest")
    assert meta["source"] == "agent" and d["result"] == "hit" and d["next_id"] == "s2"
    assert s["key_word"] in s["practised"]


@pytest.mark.parametrize("usage", [
    {"input_tokens": 90, "output_tokens": 60, "cache_creation_input_tokens": 0,
     "cache_read_input_tokens": 1800},
    SimpleNamespace(input_tokens=90, output_tokens=60, cache_creation_input_tokens=0,
                    cache_read_input_tokens=1800),
])
def test_agent_records_cache_and_token_usage(monkeypatch, caplog, usage):
    use(monkeypatch, *hit("You said 'forest'!"), usage=usage)
    with caplog.at_level("INFO", logger="tutor"):
        _, meta = decide(session(), "forest")
    assert {key: meta[key] for key in tutor.USAGE_FIELDS} == {
        "input_tokens": 90, "output_tokens": 60,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1800,
    }
    assert "cache_read_input_tokens=1800" in caplog.text


def test_missing_usage_is_unknown_not_a_cache_miss(monkeypatch):
    use(monkeypatch, *hit("You said 'forest'!"))
    _, meta = decide(session(), "forest")
    assert all(meta[key] is None for key in tutor.USAGE_FIELDS)


def test_invalid_output_keeps_usage_for_fallback_measurements(monkeypatch):
    use(monkeypatch, *hit("Lovely!"), usage={"input_tokens": 90, "output_tokens": 60,
                                          "cache_creation_input_tokens": 1800, "cache_read_input_tokens": 0})
    _, meta = decide(session(), "forest")
    assert meta["source"] == "fallback"
    assert meta["cache_creation_input_tokens"] == 1800
    assert meta["cache_read_input_tokens"] == 0


def test_malformed_usage_does_not_force_fallback(monkeypatch):
    use(monkeypatch, *hit("You said 'forest'!"), usage={"input_tokens": -1, "output_tokens": "60",
                                                     "cache_read_input_tokens": True})
    _, meta = decide(session(), "forest")
    assert meta["source"] == "agent"
    assert all(meta[key] is None for key in tutor.USAGE_FIELDS)


def test_agent_level_up_and_next_scene_challenge(monkeypatch):
    s = session()
    s["hit_streak"] = 1
    use(monkeypatch, *hit("You said 'forest'!", level=2, more=[
        ("ask", {"prompt": "Can you say 'silver river'?", "target_words": ["silver", "river"], "level": 2})]))
    d, meta = decide(s, "forest", next_narration=NEXT_NARRATION)
    assert meta["source"] == "agent" and s["level"] == 2
    assert d["next_challenge"] == {"level": 2, "prompt": "Can you say 'silver river'?",
                                   "target_words": ["silver", "river"], "question_type": "say",
                                   "accept": ["silver", "river"], "reason": "Agent chose a say question at level 2"}


def test_agent_miss_retries_with_its_own_challenge(monkeypatch):
    use(monkeypatch, *miss("retry_with_hint", "Nearly! It starts with 'ow'.", 1,
                           ("ask", {"prompt": "Can you say 'owl'?", "target_words": ["owl"], "level": 1})))
    s = session()
    d, meta = decide(s, "banana")
    assert meta["source"] == "agent" and d["retry"] and d["action"] == "retry_with_hint"
    assert d["challenge"]["target_words"] == ["owl"] and s["key_word"] == "owl"
    assert s["tries"] == 1 and s["miss_streak"] == 1


def test_attempt_limit_moves_on_with_template_parent_note(monkeypatch):
    use(monkeypatch, *miss("move_on", "Good try, it's 'forest'!"))
    s = session()
    s["tries"] = 2
    d, meta = decide(s, "banana")
    assert meta["source"] == "agent" and not d["retry"] and d["next_id"] == "s2"
    assert d["parent_note"] and s["key_word"] in d["parent_note"]


def test_agent_parent_note_is_kept(monkeypatch):
    use(monkeypatch, *miss("retry_with_hint", "Let's listen to the story again.", 1,
                           ("notify_parent", {"note": "Seemed upset in the forest scene - check in"})))
    d, _ = decide(session(), "i am sad")
    assert d["parent_note"] == "Seemed upset in the forest scene - check in"


# ---------- invalid agent output -> fallback rule ----------

@pytest.mark.parametrize("calls,why", [
    (hit("Lovely!"), "praise does not name the word"),
    ([("assess", {"result": "hit", "reason": "ok"}), ("next_step", {"action": "retry_with_hint", "say": "You said forest!"})],
     "hit must advance"),
    (miss("advance", "Good try!"), "miss cannot advance"),
    (hit("You said 'forest'!", level=3), "more than one"),
    ([("assess", {"result": "hit", "reason": "ok"}), ("set_difficulty", {"level": 5}),
      ("next_step", {"action": "advance", "say": "You said forest!"})], "set_difficulty"),
    (miss("retry_with_hint", "That was wrong, try again."), "wrong"),
    (miss("retry_with_hint", "Try again!", 1, ("ask", {"prompt": "Say 'dragon'?", "target_words": ["dragon"], "level": 1})),
     "not in narration"),
    (miss("retry_with_hint", "Try again!", 1,
          ("ask", {"prompt": "Say 'quiet forest'?", "target_words": ["quiet", "forest"], "level": 1})), "level 1 say needs"),
    ([("assess", {"result": "hit", "reason": "ok"})], "next_step not called"),
    ([("unknown_tool", {})], "unknown tool"),
])
def test_invalid_output_uses_fallback(monkeypatch, calls, why):
    use(monkeypatch, *calls)
    s = session()
    d, meta = decide(s, "forest")
    assert meta["source"] == "fallback" and why in meta["fallback_reason"]
    assert d["result"] == "hit" and d["feedback"] == "You said 'forest'!"  # the fallback's template


def test_retry_when_attempts_used_up_is_invalid(monkeypatch):
    use(monkeypatch, *miss("retry_with_hint", "Let's try again!"))
    s = session()
    s["tries"] = 2
    d, meta = decide(s, "banana")
    assert meta["source"] == "fallback" and "attempts used up" in meta["fallback_reason"]
    assert d["action"] == "move_on"


def test_slow_agent_uses_fallback(monkeypatch):
    monkeypatch.setattr(tutor, "TIMEOUT_S", 0.05)
    use(monkeypatch, *hit("You said 'forest'!"), delay=1.0)
    d, meta = decide(session(), "forest")
    assert meta["source"] == "fallback" and "took over" in meta["fallback_reason"]
    assert d["feedback"] == "You said 'forest'!"


def test_api_error_uses_fallback():
    d, meta = decide(session(), "forest")  # conftest: call_model raises
    assert meta["source"] == "fallback" and "RuntimeError" in meta["fallback_reason"]
    assert d["result"] == "hit"


def test_refusal_uses_fallback(monkeypatch):
    use(monkeypatch, stop_reason="refusal")
    _, meta = decide(session(), "forest")
    assert meta["source"] == "fallback" and "refusal" in meta["fallback_reason"]


# ---------- safety ----------

def test_line_repeating_personal_info_is_rejected(monkeypatch):
    use(monkeypatch, *miss("retry_with_hint", "Hello Zorblax, let's find the owl!"))
    d, meta = decide(session(), "my name is zorblax")
    assert meta["source"] == "fallback" and "child's own words" in meta["fallback_reason"]
    assert "zorblax" not in d["feedback"].lower()


def test_parent_note_with_child_words_is_dropped(monkeypatch):
    use(monkeypatch, *miss("retry_with_hint", "Let's find the owl!", 1,
                           ("notify_parent", {"note": "Mentioned zorblax street 12"})))
    d, meta = decide(session(), "i live on zorblax street")
    assert meta["source"] == "agent" and d["parent_note"] is None


# ---------- authored turns: rules decide, agent writes the line ----------

def test_question_wrong_answer_agent_line_plus_authored_hint(monkeypatch):
    model = use(monkeypatch, ("assess", {"result": "hit", "reason": "ignored"}),
                ("next_step", {"action": "advance", "say": "Ooh, nearly, let's think again!"}))
    s = session(QUESTION)
    d, meta = decide(s, "moon", QUESTION)
    assert meta["source"] == "agent"
    assert d["result"] == "miss" and d["retry"] and d["action"] == "retry_with_hint"  # authored, not the agent's
    assert d["feedback"] == "Ooh, nearly, let's think again! The sun shines in the daytime."
    assert "TURN TYPE: AUTHORED" in model.messages[0][0]["content"]
    assert s["level"] == 1


def test_question_correct_agent_praise_must_name_word(monkeypatch):
    use(monkeypatch, ("next_step", {"action": "advance", "say": "Yes, 'sun', clever you!"}))
    d, _ = decide(session(QUESTION), "sun", QUESTION)
    assert d["result"] == "hit" and d["next_id"] == "s3" and d["feedback"] == "Yes, 'sun', clever you!"

    use(monkeypatch, ("next_step", {"action": "advance", "say": "Clever you!"}))
    d, meta = decide(session(QUESTION), "sun", QUESTION)
    assert meta["source"] == "fallback" and d["feedback"] == "Yes, the sun! Well done!"


def test_question_reveal_at_max_attempts(monkeypatch):
    use(monkeypatch, ("next_step", {"action": "move_on", "say": "What great thinking!"}))
    s = session(QUESTION)
    s["tries"] = 2
    d, _ = decide(s, "moon", QUESTION)
    assert not d["retry"] and d["feedback"] == "What great thinking! It's the sun."
    assert d["parent_note"]


def test_branch_choice_follows_child_and_agent_celebrates(monkeypatch):
    use(monkeypatch, ("next_step", {"action": "advance", "say": "The boat, what an adventure!"}),
        ("notify_parent", {"note": "Chose confidently"}))
    d, _ = decide(session(BRANCH), "boat", BRANCH)
    assert d["next_id"] == "y" and d["feedback"] == "The boat, what an adventure!"
    assert d["parent_note"] == "Chose confidently"


def test_branch_unrecognised_repeats_options_after_agent_line(monkeypatch):
    use(monkeypatch, ("next_step", {"action": "retry_with_hint", "say": "Ooh, what a fun idea!"}))
    d, _ = decide(session(BRANCH), "dinosaur", BRANCH)
    assert d["retry"] and d["log_result"] == "no_choice"
    assert d["feedback"] == "Ooh, what a fun idea! Bridge or boat?"


def test_first_silence_is_authored_not_a_miss(monkeypatch):
    use(monkeypatch, ("next_step", {"action": "retry_with_hint", "say": "Take your time!"}))
    s = session()
    d, _ = decide(s, "")
    assert d["result"] == "silence" and s["tries"] == 0
    assert d["feedback"].startswith("Take your time! Can you say")


# ---------- tools ----------

def test_child_state_never_includes_child_words():
    from tools.get_child_state import get_child_state
    s = session()
    s["log"] = [{"result": "miss", "scene_id": "s1", "targets": ["forest"], "transcript": "secret"}]
    state = get_child_state(s)
    assert state["recent"] == [{"scene": "s1", "result": "miss", "targets": ["forest"]}]
    assert "secret" not in json.dumps(state)


def test_tool_schemas_are_strict():
    for t in tutor.TOOLS:
        assert t["strict"] and t["input_schema"]["additionalProperties"] is False
    assert {t["name"] for t in tutor.TOOLS} == {"assess", "set_difficulty", "next_step", "ask", "notify_parent"}
