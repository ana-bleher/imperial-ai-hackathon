"""How Pip talks: banned phrases in the agent's lines and questions, and the fallback templates.
The agent is mocked; nothing goes over the network.  Run:  pytest tests/test_wording.py -v"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import fallback as fb
from agent import questions as q
from agent import tutor
from agent.main import SESSIONS, app

client = TestClient(app)
NARRATION = "Mia steps into a quiet forest. A sleepy owl hoots hello. The bells rang three times."
SCENE = {"id": "x", "narration": NARRATION, "next": "y"}
QUESTION = {"id": "q", "narration": "A sun and a moon.", "next": "s3", "decision": {
    "type": "single_correct", "prompt": "Which one shines in the day: sun or moon?",
    "options": [{"word": "sun", "label": "Sun", "icon": "sun"}, {"word": "moon", "label": "Moon", "icon": "moon"}],
    "correct_word": "sun", "incorrect_words": ["moon"], "on_correct": "advance",
    "on_incorrect": "retry_with_hint", "max_attempts": 3, "on_max_attempts": "reveal_correct_and_advance",
    "hint": "The sun shines in the daytime. Can you say sun?"}}

BANNED_SAYS = [  # each names the word, so only the banned phrase makes it invalid
    "Let's say {w} together!",
    "Say it with me, {w}!",
    "What great trying, {w}!",
    "Nice trying, it's {w}!",
    "Good trying! Listen: {w}.",
    "{w} is a lovely little word!",
]


def fake(*calls):
    async def model(messages):
        return SimpleNamespace(stop_reason="tool_use", usage=None, content=[
            SimpleNamespace(type="tool_use", name=n, input=i) for n, i in calls])
    return model


def session(scene=SCENE):
    s = {"child": {"child_name": "Mia", "pronouns": "she", "avatar": {}}, "log": [], **fb.new_session_state()}
    fb.enter_scene(s, scene, scene["narration"], exclude={"mia"})
    return s


def decide(s, transcript, scene=SCENE):
    vocab = set(fb.words(json.dumps(scene))) | {"mia"}
    return asyncio.run(tutor.decide(s, scene, scene["narration"], transcript,
                                    next_narration=None, name_words={"mia"}, vocab=vocab))


# ---------- the agent ----------

@pytest.mark.parametrize("say", BANNED_SAYS)
def test_banned_phrase_in_speaking_line_falls_back(monkeypatch, say):
    monkeypatch.setattr(tutor, "call_model", fake(
        ("assess", {"result": "hit", "reason": "Said it"}), ("set_difficulty", {"level": 1}),
        ("next_step", {"action": "advance", "say": say.format(w="forest")})))
    s = session()
    d, meta = decide(s, s["challenge"]["target_words"][0])
    assert meta["source"] == "fallback" and "banned phrase" in meta["fallback_reason"]
    assert d["feedback"] == f"You said '{s['key_word']}'!"  # the fallback rule's line


@pytest.mark.parametrize("say", BANNED_SAYS)
def test_banned_phrase_in_authored_line_uses_the_template(monkeypatch, say):
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "advance", "say": say.format(w="sun")})))
    d, meta = decide(session(QUESTION), "sun", QUESTION)
    assert "banned phrase" in meta["fallback_reason"] and d["feedback"] == "Yes, the sun! Well done!"


def test_banned_phrase_in_question_falls_back(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(
        ("assess", {"result": "miss", "reason": "Not heard"}), ("set_difficulty", {"level": 1}),
        ("next_step", {"action": "retry_with_hint", "say": "Nice try! Listen: owl."}),
        ("ask", {"prompt": "Say it with me: 'owl'", "target_words": ["owl"], "level": 1,
                 "question_type": "say", "accept": [], "reason": "Easier word"})))
    d, meta = decide(session(), "banana")
    assert meta["source"] == "fallback" and "question uses banned phrase 'with me'" in meta["fallback_reason"]
    assert tutor.banned_phrase(d["feedback"]) is None


def test_allowed_lines_pass():
    for say in ["Yes! You said 'forest'!", "Good try! Listen: forest. Now you try!", "Keep trying, you can do it!",
                "Ooh, close! It's 'owl'. Can you say it?", "Brilliant, three bells!"]:
        assert tutor.banned_phrase(say) is None, say


def test_banned_phrase_reason_is_logged_over_http(monkeypatch):
    sess = client.post("/session/start", json={"child_name": "Tam", "pronouns": "he"}).json()
    monkeypatch.setattr(tutor, "call_model", fake(
        ("assess", {"result": "hit", "reason": "Said it"}), ("set_difficulty", {"level": 1}),
        ("next_step", {"action": "advance", "say": "Great trying, lantern!"})))
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": "lantern"}).json()
    assert r["feedback"] == "You said 'lantern'!"
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert entry["source"] == "fallback" and "banned phrase '<adjective> trying'" in entry["fallback_reason"]


# ---------- fallback templates ----------

def clean(text: str) -> bool:
    return tutor.banned_phrase(text) is None


def test_hint_templates_name_the_word():
    for level in (1, 2, 3):
        ch = fb.make_challenge(NARRATION, "owl", level, hint=True)
        assert ch["prompt"].startswith("Listen: '") and ch["prompt"].endswith("Now you try!")
        assert "owl" in ch["prompt"] and clean(ch["prompt"])


def test_step_down_templates_name_the_answer():
    count = q.normalise({"level": 2, "prompt": "How many times did the bells ring?",
                         "target_words": ["three", "3"], "question_type": "count"})
    choice = q.step_down(count, NARRATION, "three", 2)
    assert choice["question_type"] == "choice" and "three" in choice["prompt"] and clean(choice["prompt"])
    say = q.step_down(choice, NARRATION, "three", 2)
    assert say["prompt"] == "Listen: 'three'. Now you try!" and clean(say["prompt"])
    open_q = q.normalise({"level": 3, "prompt": "Why did the owl hoot?", "target_words": [], "question_type": "open"})
    from_open = q.step_down(open_q, NARRATION, "owl", 3)
    assert "owl" in from_open["prompt"] and clean(from_open["prompt"])


def run_feedback(scene, answers, level=1, challenge=None):
    s = {**fb.new_session_state(), "level": level}
    fb.enter_scene(s, scene, scene["narration"], exclude={"mia"})
    if challenge:
        s["challenge"] = q.normalise(challenge)
        s["key_word"] = q.key_word(s["challenge"])
    return [fb.turn(s, scene, scene["narration"], a) for a in answers]


def test_every_fallback_line_follows_the_rules():
    count = {"level": 2, "prompt": "How many times did the bells ring?", "target_words": ["three"],
             "question_type": "count"}
    branch = {"id": "b", "narration": "A bridge and a boat.",
              "decision": {"type": "branch_choice", "prompt": "Bridge or boat?"}, "branches": [
                  {"word": "bridge", "label": "Cross the bridge", "icon": "bridge", "next": "x"},
                  {"word": "boat", "label": "Take the boat", "icon": "boat", "next": "y"}]}
    runs = [
        run_feedback(SCENE, ["", "banana", "banana", "banana"], level=2),  # silence, retry, hint, move on
        run_feedback(SCENE, ["banana", "banana", "banana"], challenge=count),  # count -> choice -> say -> move on
        run_feedback(QUESTION, ["", "moon", "moon", "moon"]),
        run_feedback(branch, ["", "dinosaur", "dinosaur", "yes"]),
        run_feedback(SCENE, ["owl"], challenge={"level": 1, "prompt": "Can you say 'owl'?",
                                                "target_words": ["owl"], "question_type": "say"}),
    ]
    lines = [d["feedback"] for run in runs for d in run] + \
            [d["challenge"]["prompt"] for run in runs for d in run if d.get("challenge")]
    for line in lines:
        assert clean(line), line
        assert "trying" not in line.lower(), line
    misses = [d for d in runs[0] + runs[1] if d["result"] == "miss"]
    for d in misses:  # every hint or modelled answer names the word or answer
        named = d["challenge"]["target_words"] if d.get("challenge") else ["owl", "forest", "three", "sleepy", "quiet"]
        assert any(w in d["feedback"] for w in named), d["feedback"]
