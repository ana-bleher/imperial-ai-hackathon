"""Endings (s5a, s5b, adventure page 4) always keep their authored goodnight challenge, even when the
agent calls ask; retries repeat the same goodnight. The agent and the page writer are mocked.
Run:  pytest tests/test_endings.py -v"""
import pytest
from fastapi.testclient import TestClient

from agent import adventure, main, tutor
from agent.main import SESSIONS, app
from test_adventure import FakeWriter, choose
from test_adventure import start as start_adventure
from test_tutor_fixes import fake

PIP_GOODNIGHT = "Can you whisper 'goodnight' to Pip?"
# A valid question for either ending's narration, if code let the agent set it.
RECALL = ("ask", {"prompt": "What came out in the sky?", "target_words": ["stars"], "level": 2,
                  "question_type": "recall", "accept": ["stars"], "reason": "Recall fits the stars"})


def hit(say, *more):
    return [("assess", {"result": "hit", "reason": "Heard it"}), ("set_difficulty", {"level": 2}),
            ("next_step", {"action": "advance", "say": say}), *more]


def miss(say, *more):
    return [("assess", {"result": "miss", "reason": "Not yet"}), ("set_difficulty", {"level": 2}),
            ("next_step", {"action": "retry_with_hint", "say": say}), *more]


def at(c, scene_id):
    sess = c.post("/session/start", json={"child_name": "Mia", "avatar": {"pet": "fox"}}).json()
    s = SESSIONS[sess["session_id"]]
    s["level"] = 2
    main.enter_scene(s, scene_id)
    return sess


def turn(c, sess, transcript):
    return c.post("/turn", json={"session_id": sess["session_id"], "transcript": transcript}).json()


@pytest.mark.parametrize("before, ending, answer", [("s4a", "s5a", "three"), ("s4b", "s5b", "two")])
def test_pip_ending_keeps_goodnight_after_the_agent_called_ask(monkeypatch, before, ending, answer):
    monkeypatch.setattr(tutor, "call_model", fake(*hit(f"Yes, {answer}!", RECALL)))
    c = TestClient(app)
    sess = at(c, before)
    assert main.next_speaking_narrations(SESSIONS[sess["session_id"]], main.SCENES[before]) == {}
    r = turn(c, sess, answer)
    assert "NEXT SCENE NARRATION" not in fake.message  # the agent is never asked for an ending
    assert r["scene"]["id"] == ending and r["scene"]["challenge"]["prompt"] == PIP_GOODNIGHT
    assert r["scene"]["challenge"]["target_words"] == ["goodnight"]


def test_agent_ask_targeting_an_ending_is_ignored(monkeypatch):
    c = TestClient(app)
    sess = at(c, "s4a")
    s = SESSIONS[sess["session_id"]]
    main.enter_scene(s, "s5a", {"level": 2, "prompt": "What came out?", "target_words": ["stars"],
                                "question_type": "recall", "accept": ["stars"], "reason": "x"})
    assert s["challenge"]["prompt"] == PIP_GOODNIGHT


@pytest.mark.parametrize("transcript", ["banana", "I don't know", "I like big dinosaurs"])
def test_ending_retries_repeat_the_goodnight(monkeypatch, transcript):
    c = TestClient(app)
    for calls in (miss("Good try!", RECALL), None):  # the agent's ask is ignored; the fallback too
        if calls:
            monkeypatch.setattr(tutor, "call_model", fake(*calls))
        else:
            monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "nonsense", "say": ""})))
        sess = at(c, "s5a")
        for _ in range(2):
            r = turn(c, sess, transcript)
            assert r["retry"] and r["scene"]["challenge"]["prompt"] == PIP_GOODNIGHT
            assert r["scene"]["challenge"]["target_words"] == ["goodnight"]
        assert turn(c, sess, "goodnight")["story_complete"]


def test_adventure_page_four_keeps_goodnight_after_the_agent_called_ask(monkeypatch):
    monkeypatch.setattr(adventure, "call_model", FakeWriter())
    with TestClient(app) as c:
        sess = start_adventure(c)
        choose(c, sess, "garden")
        choose(c, sess, "lake")
        s = SESSIONS[sess["session_id"]]
        assert all(not main.is_ending(s["scenes"][n]) for n in main.next_speaking_narrations(s, s["scenes"]["a3-lake"]))
        monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "advance",
                                                                    "say": "Ooh, the cottage! Off we go."}), RECALL))
        r = choose(c, sess, "cottage")
        assert r["scene"]["index"] == 4
        assert r["scene"]["challenge"]["prompt"] == "Can you whisper 'goodnight'?"
        monkeypatch.setattr(tutor, "call_model", fake(*miss("Good try!", RECALL)))
        r = turn(c, sess, "banana")
        assert r["retry"] and r["scene"]["challenge"]["prompt"] == "Can you whisper 'goodnight'?"
        assert turn(c, sess, "goodnight")["story_complete"]
