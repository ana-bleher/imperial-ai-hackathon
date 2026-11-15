"""Tutor fixes from a test run: off-topic answers, quiz misses, "I don't know", branches the child
did not pick, and age. The agent is mocked; nothing goes over the network.
Run:  pytest tests/test_tutor_fixes.py -v"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import fallback as fb
from agent import questions as q
from agent import tutor
from agent.main import SESSIONS, app
from test_adventure import start as start_adventure

client = TestClient(app)
NARRATION = "The tiny bells rang three times: ting, ting, ting! Mia tied a red ribbon to the rail."
SCENE = {"id": "x", "narration": NARRATION, "next": "y"}
COUNT = {"level": 2, "prompt": "How many times did the bells ring?", "target_words": ["three"],
         "question_type": "count"}
QUIZ = {"id": "q", "narration": "A sun and a moon.", "next": "s3", "decision": {
    "type": "single_correct", "prompt": "Which one warms the flowers: sun or moon?",
    "options": [{"word": "sun", "label": "Sun", "icon": "sun"}, {"word": "moon", "label": "Moon", "icon": "moon"}],
    "correct_word": "sun", "incorrect_words": ["moon"], "on_correct": "advance",
    "on_incorrect": "retry_with_hint", "max_attempts": 3, "on_max_attempts": "reveal_correct_and_advance",
    "hint": "The sun shines in the daytime and helps flowers grow. Can you say sun?"}}
BRANCH = {"id": "b", "narration": "A bridge and a boat.",
          "decision": {"type": "branch_choice", "prompt": "Bridge or boat?"}, "branches": [
              {"word": "bridge", "label": "Cross the bridge", "icon": "bridge", "next": "x"},
              {"word": "boat", "label": "Take the boat", "icon": "boat", "next": "y"}]}


def fake(*calls):
    async def model(messages):
        fake.message = messages[0]["content"]
        return SimpleNamespace(stop_reason="tool_use", usage=None, content=[
            SimpleNamespace(type="tool_use", name=n, input=i) for n, i in calls])
    return model


def session(scene=SCENE, challenge=None, level=1):
    s = {"child": {"child_name": "Mia", "pronouns": "she", "avatar": {}}, "log": [],
         **fb.new_session_state(), "level": level}
    fb.enter_scene(s, scene, scene["narration"], exclude={"mia"})
    if challenge:
        s["challenge"] = q.normalise(challenge)
        s["key_word"] = q.key_word(s["challenge"])
    return s


def decide(s, transcript, scene=SCENE):
    vocab = set(fb.words(json.dumps(scene))) | {"mia"}
    return asyncio.run(tutor.decide(s, scene, scene["narration"], transcript,
                                    next_narration=None, name_words={"mia"}, vocab=vocab))


def miss_calls(say, *more, level=2):
    return [("assess", {"result": "miss", "reason": "Not the answer"}), ("set_difficulty", {"level": level}),
            ("next_step", {"action": "retry_with_hint", "say": say}), *more]


# ---------- off-topic ----------

def test_off_topic_speaking_fallback_steers_back_to_the_same_question():
    s = session(challenge=COUNT, level=2)
    d = fb.turn(s, SCENE, NARRATION, "I like dinosaurs")
    assert d["retry"] and d["challenge"]["prompt"] == COUNT["prompt"]  # no step down
    assert d["feedback"] == "That sounds fun! How many times did the bells ring?"
    assert "try" not in d["feedback"].lower()


def test_short_wrong_answers_still_step_down():
    s = session(challenge=COUNT, level=2)
    assert fb.turn(s, SCENE, NARRATION, "seven")["challenge"]["question_type"] == "choice"


def test_off_topic_quiz_fallback():
    d = fb.turn(session(QUIZ), QUIZ, QUIZ["narration"], "I like dinosaurs")
    assert d["feedback"] == "That sounds fun! Which one warms the flowers: sun or moon?"


def test_off_topic_branch_fallback():
    d = fb.turn(session(BRANCH), BRANCH, BRANCH["narration"], "I like big dinosaurs")
    assert d["feedback"] == "That sounds fun! Bridge or boat?" and d["log_result"] == "no_choice"


def test_agent_nice_try_on_off_topic_is_rejected(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("Nice try!")))
    d, meta = decide(session(challenge=COUNT, level=2), "I like dinosaurs")
    assert "effort praise" in meta["fallback_reason"]
    assert d["feedback"] == "That sounds fun! How many times did the bells ring?"

    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "retry_with_hint", "say": "Good try!"})))
    d, meta = decide(session(QUIZ), "I like dinosaurs", QUIZ)
    assert "effort praise" in meta["fallback_reason"]


def test_agent_off_topic_keeps_the_question_and_appends_it(monkeypatch):
    easier = ("ask", {"prompt": "Was it two or three?", "target_words": ["two", "three"], "level": 2,
                      "question_type": "choice", "accept": ["three"], "reason": "Easier"})
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("That sounds lovely!", easier)))
    s = session(challenge=COUNT, level=2)
    d, meta = decide(s, "I like dinosaurs")
    assert meta["source"] == "agent" and "ANSWER IS OFF-TOPIC" in fake.message
    assert d["challenge"]["prompt"] == COUNT["prompt"]  # the same question, not a step down
    assert d["feedback"] == "That sounds lovely! How many times did the bells ring?"


# ---------- quiz misses ----------

def test_quiz_fallback_misses_are_short_and_different():
    s = session(QUIZ)
    first = fb.turn(s, QUIZ, QUIZ["narration"], "moon")["feedback"]
    second = fb.turn(s, QUIZ, QUIZ["narration"], "moon")["feedback"]
    assert first == "Good try! The sun shines in the daytime and helps flowers grow."
    assert second == "Ooh, close! Can you say 'sun'?"  # a different, simpler hint
    for line in (first, second):
        assert fb.sentences(line) <= 2
    third = fb.turn(s, QUIZ, QUIZ["narration"], "moon")
    assert third["action"] == "move_on" and third["feedback"] == "Good try! It's the sun."


def test_agent_quiz_miss_of_two_sentences_is_rejected(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(
        ("next_step", {"action": "retry_with_hint", "say": "Good try. Let's think about it again!"})))
    d, meta = decide(session(QUIZ), "moon", QUIZ)
    assert "one short sentence" in meta["fallback_reason"]
    assert d["feedback"] == "Good try! The sun shines in the daytime and helps flowers grow."


def test_agent_quiz_hint_changes_on_the_second_miss(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "retry_with_hint", "say": "Ooh, nearly!"})))
    s = session(QUIZ)
    first, _ = decide(s, "moon", QUIZ)
    s["last_feedback"] = first["feedback"]
    second, meta = decide(s, "moon", QUIZ)
    assert first["feedback"] == "Ooh, nearly! The sun shines in the daytime and helps flowers grow."
    assert second["feedback"] == "Ooh, nearly! Can you say 'sun'?" and meta["source"] == "agent"


def test_agent_same_line_twice_is_rejected(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "retry_with_hint", "say": "Ooh, nearly!"})))
    s = session(QUIZ)
    s["last_feedback"] = "Ooh, nearly! The sun shines in the daytime and helps flowers grow."
    d, meta = decide(s, "moon", QUIZ)
    assert "same line as last turn" in meta["fallback_reason"]
    assert d["feedback"] != s["last_feedback"]


def test_last_feedback_is_remembered_over_http():
    sess = client.post("/session/start", json={"child_name": "Ola"}).json()
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": "banana"}).json()
    assert SESSIONS[sess["session_id"]]["last_feedback"] == r["feedback"]


# ---------- "I don't know" ----------

@pytest.mark.parametrize("said", ["I don't know", "dunno", "I'm not sure"])
def test_dont_know_on_a_count_question_gives_the_easier_question(said):
    d = fb.turn(session(challenge=COUNT, level=2), SCENE, NARRATION, said)
    assert d["feedback"] == "That's okay! Was it two or three?"


def test_dont_know_on_an_adventure_page():
    with TestClient(app) as c:
        sess = start_adventure(c)
        r = c.post("/turn", json={"session_id": sess["session_id"], "transcript": "I don't know"}).json()
    assert r["retry"] and r["feedback"] == "That's okay! Was it one or two?"
    assert r["scene"]["challenge"]["prompt"] == "Was it one or two?"


def test_dont_know_on_the_quiz_and_branch():
    quiz = fb.turn(session(QUIZ), QUIZ, QUIZ["narration"], "I don't know")
    assert quiz["feedback"] == "That's okay! The sun shines in the daytime and helps flowers grow."
    branch = fb.turn(session(BRANCH), BRANCH, BRANCH["narration"], "I don't know")
    assert branch["feedback"] == "That's okay! Bridge or boat?"


def test_agent_dont_know_line_gets_the_easier_question(monkeypatch):
    easier = ("ask", {"prompt": "Was it two or three?", "target_words": ["two", "three"], "level": 2,
                      "question_type": "choice", "accept": ["three"], "reason": "Not sure, so a choice"})
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("That's okay, let's try an easier one.", easier)))
    d, meta = decide(session(challenge=COUNT, level=2), "I don't know")
    assert meta["source"] == "agent" and "CHILD IS NOT SURE" in fake.message
    assert d["feedback"] == "That's okay, let's try an easier one. Was it two or three?"


def test_a_easier_is_rejected(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("That's okay, here is a easier one!")))
    _, meta = decide(session(challenge=COUNT, level=2), "I don't know")
    assert "a easier" in meta["fallback_reason"]


# ---------- branches the child did not pick ----------

def to_proposal(s):
    for said in ("I like big dinosaurs", "I like big dinosaurs"):
        fb.turn(s, BRANCH, BRANCH["narration"], said)
    assert s["proposed"] == "bridge" and s["challenge"]["prompt"] == "Shall we cross the bridge?"


def test_off_topic_answer_to_a_proposal_does_not_sound_chosen():
    s = session(BRANCH)
    to_proposal(s)
    d = fb.turn(s, BRANCH, BRANCH["narration"], "I want a dinosaur")
    assert d["next_id"] == "x" and d["feedback"] == "Let's try the bridge!" and d["chosen_by_child"] is False
    s = session(BRANCH)
    to_proposal(s)
    assert fb.turn(s, BRANCH, BRANCH["narration"], "yes")["feedback"] == "The bridge it is, Mia! Off we go."


def test_agent_it_is_on_a_code_pick_is_rejected(monkeypatch):
    s = session(BRANCH)
    to_proposal(s)
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "advance", "say": "The bridge it is!"})))
    d, meta = decide(s, "I want a dinosaur", BRANCH)
    assert "code picked" in meta["fallback_reason"] and d["feedback"] == "Let's try the bridge!"
    assert "THE CHILD DID NOT CHOOSE" in fake.message

    s = session(BRANCH)
    to_proposal(s)
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "advance", "say": "Let's try the bridge!"})))
    d, meta = decide(s, "I want a dinosaur", BRANCH)
    assert meta["source"] == "agent" and d["feedback"] == "Let's try the bridge!"


# ---------- age ----------

@pytest.mark.parametrize("age,expected", [(5, 5), (12, 8), (1, 3), (5.7, 5), ("6", 6), ("five", None),
                                          (True, None), (None, None), ([5], None)])
def test_age_is_clamped_to_3_8(age, expected):
    sess = client.post("/session/start", json={"child_name": "Ayo", "age": age}).json()
    assert SESSIONS[sess["session_id"]]["child"]["age"] == expected
