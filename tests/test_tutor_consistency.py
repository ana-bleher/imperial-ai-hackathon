"""Prompt/code consistency: the length rule, off-topic lines that only acknowledge, effort phrases
only when they fit, neutral move_on reveals, and questions that ask one thing once.
The agent is mocked; nothing goes over the network.
Run:  pytest tests/test_tutor_consistency.py -v"""
import pytest

from agent import fallback as fb
from agent import tutor
from test_tutor_fixes import BRANCH, COUNT, NARRATION, QUIZ, SCENE, decide, fake, miss_calls, session

SAY_OWL = {"level": 1, "prompt": "Can you say 'ribbon'?", "target_words": ["ribbon"], "question_type": "say"}


def last_try(s):
    s["tries"] = fb.max_attempts(SCENE) - 1
    return s


# ---------- the length rule ----------

def test_line_over_fifteen_words_is_rejected(monkeypatch):
    long = "Good try! The bells rang and rang and rang in the tower above the quiet sleepy town."
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls(long)))
    _, meta = decide(session(challenge=COUNT, level=2), "seven")
    assert "15 words" in meta["fallback_reason"]


def test_two_short_sentences_are_fine(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("Good try! Listen to the bells.")))
    _, meta = decide(session(challenge=COUNT, level=2), "seven")
    assert meta["source"] == "agent"


# ---------- off-topic: acknowledge only, code appends the question ----------

def test_agent_off_topic_acknowledgement_names_the_topic_and_code_appends_the_question(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("Dinosaurs are fun!")))
    d, meta = decide(session(challenge=COUNT, level=2), "I like dinosaurs")
    assert meta["source"] == "agent"
    assert d["feedback"] == "Dinosaurs are fun! How many times did the bells ring?"


def test_agent_off_topic_line_with_the_question_is_rejected(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("Dinosaurs are fun! How many bells rang?")))
    d, meta = decide(session(challenge=COUNT, level=2), "I like dinosaurs")
    assert "off-topic line repeats a question" in meta["fallback_reason"]
    assert d["feedback"] == "That sounds fun! How many times did the bells ring?"


def test_agent_off_topic_quiz_line_is_acknowledgement_plus_code_question(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "retry_with_hint", "say": "Dinosaurs are fun!"})))
    d, meta = decide(session(QUIZ), "I like dinosaurs", QUIZ)
    assert meta["source"] == "agent"
    assert d["feedback"] == "Dinosaurs are fun! Which one warms the flowers: sun or moon?"


def test_personal_words_are_still_never_repeated(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("Zorblax is fun!")))
    _, meta = decide(session(challenge=COUNT, level=2), "my friend is zorblax")
    assert "child's own words" in meta["fallback_reason"]


# ---------- effort phrases ----------

@pytest.mark.parametrize("transcript", ["", "I don't know", "I like dinosaurs"])
@pytest.mark.parametrize("say", ["Good try!", "Nice try! Listen again.", "Ooh, close!"])
def test_no_effort_praise_without_a_real_attempt(monkeypatch, transcript, say):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls(say)))
    s = session(challenge=COUNT, level=2)
    s["silences"] = 1  # a later silence: counted as a miss, routed to the agent
    _, meta = decide(s, transcript)
    assert meta["fallback_reason"] == "invalid agent output: effort praise without a real attempt"


def test_close_only_when_the_answer_is_close(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("Ooh, close!", level=1)))
    _, meta = decide(session(challenge=SAY_OWL), "banana")
    assert "not close" in meta["fallback_reason"]
    _, meta = decide(session(challenge=SAY_OWL), "ribble")  # most of the letters of 'ribbon'
    assert meta["source"] == "agent"


def test_quiz_close_means_the_other_option(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "retry_with_hint", "say": "Ooh, close!"})))
    _, meta = decide(session(QUIZ), "moon", QUIZ)
    assert meta["source"] == "agent"
    _, meta = decide(session(QUIZ), "stars", QUIZ)
    assert "not close" in meta["fallback_reason"]


def test_no_effort_praise_on_a_story_choice(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(("next_step", {"action": "retry_with_hint", "say": "Good try!"})))
    _, meta = decide(session(BRANCH), "swing", BRANCH)
    assert "effort praise" in meta["fallback_reason"]


def test_fallback_leads_follow_the_answer():
    s = session(QUIZ)
    assert fb.turn(s, QUIZ, QUIZ["narration"], "stars")["feedback"].startswith("Good try! ")
    s = session(QUIZ)
    assert fb.turn(s, QUIZ, QUIZ["narration"], "moon")["feedback"].startswith("Ooh, close! ")
    s = session(QUIZ)
    assert fb.turn(s, QUIZ, QUIZ["narration"], "I don't know")["feedback"].startswith("That's okay! ")
    s = session(challenge=COUNT, level=2)
    s["silences"] = 1
    line = fb.turn(s, SCENE, NARRATION, "")["feedback"]  # a later silence: no effort praise
    assert line == "Was it two or three?"  # the step-down alone, no "Good try!"


def test_effort_note_tells_the_agent_what_fits(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls("Good try!")))
    decide(session(challenge=COUNT, level=2), "seven")
    assert "EFFORT PRAISE: a real attempt" in fake.message


# ---------- move_on after the last try ----------

def test_fallback_move_on_is_neutral_without_a_real_attempt():
    s = session(QUIZ)
    s["tries"] = 2
    assert fb.turn(s, QUIZ, QUIZ["narration"], "I don't know")["feedback"] == "Let's find out: it's the sun!"
    d = fb.turn(last_try(session(challenge=COUNT, level=2)), SCENE, NARRATION, "I like dinosaurs")
    assert d["action"] == "move_on" and d["feedback"] == "Let's find out: it's 'three'!"


def test_fallback_move_on_praises_a_real_attempt():
    d = fb.turn(last_try(session(challenge=COUNT, level=2)), SCENE, NARRATION, "seven")
    assert d["action"] == "move_on" and d["feedback"] == "Good try! It's 'three'."
    for line in (d["feedback"], "Let's find out: it's 'three'!"):
        assert fb.sentences(line) <= 2


def test_agent_move_on_with_effort_praise_after_off_topic_is_rejected(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(
        ("assess", {"result": "miss", "reason": "Not the answer"}), ("set_difficulty", {"level": 2}),
        ("next_step", {"action": "move_on", "say": "Good try! It's three."})))
    d, meta = decide(last_try(session(challenge=COUNT, level=2)), "I like dinosaurs")
    assert "effort praise" in meta["fallback_reason"]
    assert d["feedback"] == "Let's find out: it's 'three'!"


# ---------- a question asks one thing once ----------

def ask(prompt, qt, targets, accept):
    return ("ask", {"prompt": prompt, "target_words": targets, "level": 2, "question_type": qt,
                    "accept": accept, "reason": "Easier"})


def test_double_choice_question_falls_back_to_the_choice_frame(monkeypatch):
    double = "Did the bells go ting once, or three times? Was it one or three?"
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls(
        "Good try!", ask(double, "choice", ["one", "three"], ["three"]))))
    d, meta = decide(session(challenge=COUNT, level=2), "seven")
    assert meta["source"] == "agent"
    assert d["challenge"]["prompt"] == "Was it one or three?"


def test_repeated_was_it_falls_back_to_the_frame(monkeypatch):
    monkeypatch.setattr(tutor, "call_model", fake(*miss_calls(
        "Good try!", ask("Was it one, or was it three?", "choice", ["one", "three"], ["three"]))))
    d, _ = decide(session(challenge=COUNT, level=2), "seven")
    assert d["challenge"]["prompt"] == "Was it one or three?"


def test_double_say_question_falls_back_to_the_say_frame():
    ch = {"prompt": "Can you say it? Can you say 'three'?", "question_type": "say", "target_words": ["three"]}
    assert tutor.one_question(ch, retry=True)["prompt"] == "Listen: 'three'. Now you try!"
    assert tutor.one_question(ch)["prompt"] == "Can you say 'three'?"


def test_double_question_without_a_frame_is_rejected():
    ch = {"prompt": "What did Mia tie? What colour was it?", "question_type": "colour", "target_words": ["red"]}
    with pytest.raises(tutor.InvalidAgentOutput, match="more than one thing"):
        tutor.one_question(ch)


def test_single_questions_are_unchanged():
    ch = {"prompt": "Was it one or three?", "question_type": "choice", "target_words": ["one", "three"]}
    assert tutor.one_question(ch) is ch
