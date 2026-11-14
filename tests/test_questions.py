"""Question types, the level ladder and step-down hints. The agent is mocked; nothing goes over the network.
Run:  pytest tests/test_questions.py -v"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import fallback as fb
from agent import questions as q
from agent import tutor
from agent.main import SCENES, SESSIONS, app

client = TestClient(app)
START = {"child_name": "Noor", "age": 5, "pronouns": "she", "avatar": {"pet": "fox"}}

NARRATION = "The tiny bells rang three times: ting, ting, ting! Noor tied a red ribbon to the rail."
SCENE = {"id": "x", "narration": NARRATION, "next": "y"}


def start():
    return client.post("/session/start", json=START).json()


def turn(sess, transcript):
    return client.post("/turn", json={"session_id": sess["session_id"], "transcript": transcript}).json()


def to_bridge(sess):
    """s1 -> s2 -> s3 -> s4a by typed answers."""
    for answer in ("lantern", "sun", "bridge"):
        r = turn(sess, answer)
        assert not r["retry"], (answer, r)
    assert r["scene"]["id"] == "s4a"
    return r


def state_with(ch, level=2):
    s = {"child": {"child_name": "Noor", "pronouns": "she", "avatar": {}}, "log": [], **fb.new_session_state()}
    s["level"] = level
    fb.enter_scene(s, SCENE, NARRATION, exclude={"noor"})
    s["challenge"] = q.normalise(ch)
    s["key_word"] = q.key_word(s["challenge"])
    return s


COUNT = {"level": 2, "prompt": "How many times did the bells ring?", "target_words": ["three", "3"],
         "question_type": "count"}


# ---------- story ----------

def test_story_counting_details():
    assert "Pip's lantern blinked three times to say hello." in SCENES["s1"]["narration"]
    assert "The tiny bells rang three times: ting, ting, ting!" in SCENES["s4a"]["narration"]
    assert "A silver fish swam past. It splashed two times: splish, splash!" in SCENES["s4b"]["narration"]
    for sid in ("s5a", "s5b"):
        assert "the first stars came out, one, two, three." in SCENES[sid]["narration"]
    assert SCENES["s4a"]["challenge"] == {"prompt": "How many times did the bells ring?", "target_words": ["three", "3"]}
    assert SCENES["s4b"]["challenge"] == {"prompt": "How many times did the fish splash?", "target_words": ["two", "2"]}


# ---------- authored questions ----------

def test_authored_s1_question_at_session_start():
    sess = start()
    ch = sess["scene"]["challenge"]
    assert ch["prompt"] == SCENES["s1"]["challenge"]["prompt"]
    assert ch["target_words"] == ["lantern"]
    assert set(ch) == {"level", "prompt", "target_words"}  # accept and question_type stay private
    assert SESSIONS[sess["session_id"]]["challenge"]["question_type"] == "say"


def test_authored_types_are_inferred():
    assert q.authored_challenge(SCENES["s1"], 1)["question_type"] == "say"
    s4a = q.authored_challenge(SCENES["s4a"], 1)
    assert s4a["question_type"] == "count" and set(s4a["accept"]) == {"three", "3"}
    assert q.authored_challenge(SCENES["s2"], 1) is None  # authored decision: handled elsewhere


@pytest.mark.parametrize("answer", ["three", "3", "Three times!", "it rang 3 times"])
def test_count_question_over_http(answer):
    sess = start()
    r = to_bridge(sess)
    assert r["scene"]["challenge"]["prompt"] == "How many times did the bells ring?"
    r = turn(sess, answer)
    assert r["result"] == "hit" and r["scene"]["id"] == "s5a"
    assert "three" in r["feedback"].lower()


def test_count_wrong_steps_down_to_choice_then_say_over_http():
    sess = start()
    to_bridge(sess)
    r = turn(sess, "seven")
    assert r["result"] == "miss" and r["retry"]
    ch = r["scene"]["challenge"]
    assert ch["prompt"] == "Was it two or three?" and ch["target_words"] == ["two", "three"]
    r = turn(sess, "two")  # the wrong option
    assert r["retry"] and r["scene"]["challenge"]["prompt"] == "Say it with me: 'three'"
    r = turn(sess, "three")
    assert r["result"] == "hit" and r["scene"]["id"] == "s5a"


def test_attempts_used_up_models_the_answer():
    s = state_with(COUNT)
    fb.turn(s, SCENE, NARRATION, "seven")
    fb.turn(s, SCENE, NARRATION, "seven")
    d = fb.turn(s, SCENE, NARRATION, "seven")
    # count -> choice -> say it, then attempts are used up: the answer is modelled
    assert d["action"] == "move_on" and "'three'" in d["feedback"] and d["parent_note"]
    s = state_with(COUNT)
    s["tries"] = 2  # last attempt still on the count question itself
    d = fb.turn(s, SCENE, NARRATION, "seven")
    assert d["action"] == "move_on" and "It was three" in d["feedback"]


def test_agent_slow_uses_authored_question_rule(monkeypatch):
    monkeypatch.setattr(tutor, "TIMEOUT_S", 0.01)

    async def slow(messages):
        await asyncio.sleep(1)
    monkeypatch.setattr(tutor, "call_model", slow)
    sess = start()
    to_bridge(sess)
    r = turn(sess, "3")
    assert r["result"] == "hit" and r["feedback"] == "Yes, three! Well done!"


# ---------- fallback judging per type ----------

def test_choice_step_down_after_a_miss():
    s = state_with(COUNT)
    d = fb.turn(s, SCENE, NARRATION, "ten")
    assert d["action"] == "retry_with_hint" and d["challenge"]["question_type"] == "choice"
    assert "three" in d["challenge"]["target_words"] and len(d["challenge"]["target_words"]) == 2
    assert "three" in d["challenge"]["prompt"]
    assert fb.turn(s, SCENE, NARRATION, "two or three")["result"] == "miss"  # both options is not an answer


def test_choice_steps_down_to_say_it():
    ch = {"level": 1, "prompt": "Was it the bells or the ribbon?", "target_words": ["bells", "ribbon"],
          "question_type": "choice", "accept": ["bells"]}
    s = state_with(ch, level=1)
    d = fb.turn(s, SCENE, NARRATION, "ribbon")
    assert d["challenge"]["question_type"] == "say"
    assert d["challenge"]["prompt"] == "Say it with me: 'bells'"
    assert fb.turn(s, SCENE, NARRATION, "bells")["result"] == "hit"


def test_recall_and_colour_step_down_to_choice_from_the_story():
    recall = state_with({"level": 2, "prompt": "What rang on the bridge?", "target_words": ["bells"],
                         "question_type": "recall"})
    d = fb.turn(recall, SCENE, NARRATION, "dogs")
    assert d["challenge"]["question_type"] == "choice" and "bells" in d["challenge"]["target_words"]
    other = [w for w in d["challenge"]["target_words"] if w != "bells"][0]
    assert other in fb.words(NARRATION)

    colour = state_with({"level": 2, "prompt": "What colour was the ribbon?", "target_words": ["red"],
                         "question_type": "colour"})
    assert fb.turn(colour, SCENE, NARRATION, "red one")["result"] == "hit"


def test_open_answer_of_two_words_is_a_hit_one_word_is_not():
    ch = {"level": 3, "prompt": "Why do you think Pip was happy?", "target_words": [], "question_type": "open"}
    assert fb.turn(state_with(ch, 3), SCENE, NARRATION, "going home")["result"] == "hit"
    d = fb.turn(state_with(ch, 3), SCENE, NARRATION, "home")
    assert d["result"] == "miss" and d["retry"] and d["challenge"]["question_type"] == "say"


# ---------- the agent's ask, checked per type ----------

def ask(**kw):
    return q.parse_ask({"accept": [], **kw})


@pytest.mark.parametrize("raw,level,why", [
    (dict(prompt="How many times did the bells ring? Three?", target_words=["three"], level=2,
          question_type="count"), 2, "gives the answer away"),
    (dict(prompt="How many times did it ring?", target_words=["four"], level=2, question_type="count"),
     2, "not in narration"),
    (dict(prompt="What colour was the ribbon?", target_words=["blue"], level=2, question_type="colour"),
     2, "not in narration"),
    (dict(prompt="How many times did it ring?", target_words=["three"], level=1, question_type="count"),
     1, "above level 1"),
    (dict(prompt="Bells or ribbon?", target_words=["bells", "ribbon"], level=1, question_type="choice"),
     1, "accept must name"),
    (dict(prompt="Which one?", target_words=["bells", "ribbon"], level=1, question_type="choice",
          accept=["bells"]), 1, "contain both options"),
])
def test_invalid_questions_are_rejected(raw, level, why):
    with pytest.raises(tutor.InvalidAgentOutput, match=why):
        tutor.check_challenge(ask(**raw), NARRATION, level, {"noor"})


def test_valid_questions_per_type():
    ok = [
        (dict(prompt="Can you say 'bells'?", target_words=["bells"], level=1, question_type="say"), 1),
        (dict(prompt="Was it the bells or the drum?", target_words=["bells", "drum"], level=1,
              question_type="choice", accept=["bells"]), 1),
        (dict(prompt="What rang on the bridge?", target_words=["bells"], level=2, question_type="recall"), 2),
        (dict(prompt="How many times did they ring?", target_words=["3"], level=2, question_type="count"), 2),
        (dict(prompt="What colour was the ribbon?", target_words=["red"], level=2, question_type="colour"), 2),
        (dict(prompt="Why did Noor tie a ribbon?", target_words=[], level=3, question_type="open"), 3),
    ]
    for raw, level in ok:
        ch = tutor.check_challenge(ask(**raw), NARRATION, level, {"noor"})
        assert ch["question_type"] == raw["question_type"]
    count = ask(**ok[3][0])
    assert set(count["accept"]) == {"three", "3"}  # digit and word both accepted


def test_retry_must_step_down():
    current = q.normalise(COUNT)
    same = ask(prompt="How many bells rang?", target_words=["three"], level=2, question_type="count")
    with pytest.raises(tutor.InvalidAgentOutput, match="step down"):
        tutor.check_challenge(same, NARRATION, 2, set(), retry_from=current)
    wrong_answer = ask(prompt="Was it one or two?", target_words=["one", "two"], level=2,
                       question_type="choice", accept=["two"])
    with pytest.raises(tutor.InvalidAgentOutput):
        tutor.check_challenge(wrong_answer, NARRATION, 2, set(), retry_from=current)
    good = ask(prompt="Was it two or three?", target_words=["two", "three"], level=2,
               question_type="choice", accept=["three"])
    assert tutor.check_challenge(good, NARRATION, 2, set(), retry_from=current)["question_type"] == "choice"


# ---------- the agent on typed questions ----------

class FakeModel:
    def __init__(self, *calls):
        self.calls = calls

    async def __call__(self, messages):
        self.message = messages[0]["content"]
        return SimpleNamespace(stop_reason="tool_use", usage=None, content=[
            SimpleNamespace(type="tool_use", name=n, input=i) for n, i in self.calls])


def decide(s, transcript, monkeypatch, *calls):
    model = FakeModel(*calls)
    monkeypatch.setattr(tutor, "call_model", model)
    vocab = set(fb.words(NARRATION)) | {"noor"}
    d, meta = asyncio.run(tutor.decide(s, SCENE, NARRATION, transcript, next_narration=None,
                                       name_words={"noor"}, vocab=vocab))
    return d, meta, model


def test_agent_count_miss_steps_down_with_its_choice(monkeypatch):
    s = state_with(COUNT)
    d, meta, model = decide(s, "five", monkeypatch,
                            ("assess", {"result": "miss", "reason": "Not the count"}),
                            ("set_difficulty", {"level": 2}),
                            ("next_step", {"action": "retry_with_hint", "say": "Good counting, let's listen again!"}),
                            ("ask", {"prompt": "Was it two or three?", "target_words": ["two", "three"],
                                     "level": 2, "question_type": "choice", "accept": ["three"]}))
    assert meta["source"] == "agent" and d["challenge"]["question_type"] == "choice"
    assert "question_type count" in model.message and "step down to: ['choice']" in model.message


def test_agent_retry_without_ask_uses_the_fallback_step_down(monkeypatch):
    s = state_with(COUNT)
    d, meta, _ = decide(s, "five", monkeypatch,
                        ("assess", {"result": "miss", "reason": "Not the count"}),
                        ("set_difficulty", {"level": 2}),
                        ("next_step", {"action": "retry_with_hint", "say": "Good counting, let's listen again!"}))
    assert meta["source"] == "agent" and d["challenge"]["prompt"] == "Was it two or three?"


def test_agent_open_hit_needs_two_words(monkeypatch):
    ch = {"level": 3, "prompt": "Why did the bells ring?", "target_words": [], "question_type": "open"}
    hit = [("assess", {"result": "hit", "reason": "Sensible idea"}), ("set_difficulty", {"level": 3}),
           ("next_step", {"action": "advance", "say": "What a lovely idea!"})]
    d, meta, _ = decide(state_with(ch, 3), "the wind blew", monkeypatch, *hit)
    assert meta["source"] == "agent" and d["result"] == "hit"
    d, meta, _ = decide(state_with(ch, 3), "wind", monkeypatch, *hit)
    assert meta["source"] == "fallback" and "two or more words" in meta["fallback_reason"]


def test_agent_count_praise_must_name_the_answer(monkeypatch):
    calls = [("assess", {"result": "hit", "reason": "Right count"}), ("set_difficulty", {"level": 2})]
    d, meta, _ = decide(state_with(COUNT), "3", monkeypatch, *calls,
                        ("next_step", {"action": "advance", "say": "Yes, three rings, well done!"}))
    assert meta["source"] == "agent" and d["result"] == "hit"
    d, meta, _ = decide(state_with(COUNT), "3", monkeypatch, *calls,
                        ("next_step", {"action": "advance", "say": "Well done!"}))
    assert meta["source"] == "fallback" and d["feedback"] == "Yes, three! Well done!"


def test_payload_never_shows_accept():
    sess = start()
    to_bridge(sess)
    assert "accept" not in json.dumps(client.get(f"/progress/noor-1").json())


# ---------- who picks the question: the agent, authored only at start or on fallback ----------

ROPE = {"prompt": "Was it a ribbon or a rope?", "target_words": ["ribbon", "rope"], "level": 1,
        "question_type": "choice", "accept": ["ribbon"],
        "reason": "Level one, so a choice; the ribbon is in the story"}


def agent_turn(monkeypatch, sess, transcript, *calls):
    model = FakeModel(*calls)
    monkeypatch.setattr(tutor, "call_model", model)
    return turn(sess, transcript), model


def to_branch(sess):
    for answer in ("lantern", "sun"):  # agent offline (conftest): fallback
        turn(sess, answer)
    assert SESSIONS[sess["session_id"]]["scene_id"] == "s3"


def test_agent_ask_after_branch_sets_the_next_question_and_is_logged(monkeypatch):
    sess = start()
    to_branch(sess)
    r, model = agent_turn(monkeypatch, sess, "bridge",
                          ("next_step", {"action": "advance", "say": "The bridge, how exciting!"}),
                          ("ask", ROPE))
    assert r["scene"]["id"] == "s4a"
    assert r["scene"]["challenge"] == {"level": 1, "prompt": ROPE["prompt"], "target_words": ["ribbon", "rope"]}
    assert "NEXT SCENE NARRATION (call ask for it at level 1)" in model.message
    assert "CHILD STATE" in model.message and "STREAKS" in model.message
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert entry["question_type"] == "choice" and entry["question_reason"] == ROPE["reason"]
    log = client.get(f"/progress/{sess['child_id']}").json()["agent_log"]
    assert log[-1]["question_type"] == "choice" and log[-1]["question_reason"] == ROPE["reason"]


def test_invalid_agent_question_falls_back_to_authored(monkeypatch):
    sess = start()
    to_branch(sess)
    bad = {**ROPE, "prompt": "Was it a ribbon or a rope? It was the ribbon!", "question_type": "recall",
           "target_words": ["ribbon"], "accept": []}  # recall at level 1, and gives the answer away
    r, _ = agent_turn(monkeypatch, sess, "bridge",
                      ("next_step", {"action": "advance", "say": "The bridge, how exciting!"}), ("ask", bad))
    assert r["feedback"] == "The bridge, how exciting!"  # the agent's line is still used
    assert r["scene"]["challenge"]["prompt"] == "How many times did the bells ring?"
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert "invalid agent question" in entry["fallback_reason"]
    assert entry["question_type"] == "count" and "fallback" in entry["question_reason"].lower()


def test_agent_not_asking_falls_back_to_authored(monkeypatch):
    sess = start()
    to_branch(sess)
    r, _ = agent_turn(monkeypatch, sess, "bridge",
                      ("next_step", {"action": "advance", "say": "The bridge, how exciting!"}))
    assert r["scene"]["challenge"]["prompt"] == "How many times did the bells ring?"


def test_agent_question_replaces_authored_on_speaking_advance(monkeypatch):
    sess = start()
    to_branch(sess)
    turn(sess, "bridge")  # offline: authored count question on s4a
    goodnight_scene = {"prompt": "Can you say 'first stars'?", "target_words": ["first", "stars"], "level": 2,
                       "question_type": "say", "accept": [], "reason": "Two hits in a row, so a phrase"}
    r, model = agent_turn(monkeypatch, sess, "three",
                          ("assess", {"result": "hit", "reason": "Counted the bells"}),
                          ("set_difficulty", {"level": 2}),
                          ("next_step", {"action": "advance", "say": "Yes, three bells, well done!"}),
                          ("ask", goodnight_scene))
    assert "NEXT SCENE NARRATION" in model.message
    assert r["scene"]["id"] == "s5a" and r["scene"]["challenge"]["prompt"] == "Can you say 'first stars'?"


def test_reason_quoting_the_child_is_replaced(monkeypatch):
    sess = start()
    to_branch(sess)
    agent_turn(monkeypatch, sess, "bridge please zorblax",
               ("next_step", {"action": "advance", "say": "The bridge, how exciting!"}),
               ("ask", {**ROPE, "reason": "Child said zorblax so a choice"}))
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert "zorblax" not in entry["question_reason"]
    assert entry["question_reason"] == "Agent chose a choice question at level 1"
