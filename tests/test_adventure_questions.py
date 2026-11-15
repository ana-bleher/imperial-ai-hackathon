"""Adventure pages 1-3: a learning question (phase "question"), then the choice (phase "choice").
The page writer and the tutor are mocked; nothing goes over the network.
Run:  pytest tests/test_adventure_questions.py -v"""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import adventure, tutor
from agent.main import SESSIONS, app
from tools import voice
from test_adventure import GOOD, FakeWriter, answer, page_input, start, turn, wait_for

CONTRACT = json.loads(open("contract/turn_response.json").read())


def opening(c):
    sess = start(c)
    assert sess["scene"]["phase"] == "question"
    return sess


# ---------- question, then choice, on the same page ----------

def test_question_then_choice_on_the_same_page(monkeypatch):
    monkeypatch.setattr(voice, "speak", lambda text: f"/static/audio/{abs(hash(text))}.mp3")
    with TestClient(app) as c:
        sess = opening(c)
        assert sess["scene"]["challenge"]["prompt"] == "How many little paths were there?"
        r = turn(c, sess, "two")
        assert r["result"] == "hit" and r["retry"] is False and r["stars"] == 2  # first try: 1 + 1
        scene = r["scene"]
        assert scene["id"] == "a1" and scene["phase"] == "choice" and scene["index"] == 1
        assert [{k: ch[k] for k in ("word", "label", "icon")} for ch in scene["choices"]] == [
            {"word": "garden", "label": "Visit the flower garden", "icon": None},
            {"word": "forest", "label": "Follow the forest trail", "icon": None}]
        assert scene["challenge"]["prompt"] == "Visit the flower garden or follow the forest trail?"
        assert scene["narration_audio_url"] is None and scene["challenge_audio_url"].endswith(".mp3")
        r = turn(c, sess, "garden")
        assert r["scene"]["id"] == "a2-garden" and r["scene"]["phase"] == "question"
        assert r["scene"]["narration_audio_url"] is not None and r["scene"]["choices"] is None


def test_digit_answer_also_counts():
    with TestClient(app) as c:
        sess = opening(c)
        assert turn(c, sess, "2")["scene"]["phase"] == "choice"


def test_miss_steps_down_and_stays_on_the_question():
    with TestClient(app) as c:
        sess = opening(c)
        r = turn(c, sess, "seven")
        assert r["result"] == "miss" and r["retry"] and r["scene"]["phase"] == "question"
        assert r["scene"]["challenge"]["prompt"] == "Was it one or two?"
        r = turn(c, sess, "five")
        assert r["retry"] and r["scene"]["challenge"]["prompt"] == "Listen: 'two'. Now you try!"
        r = turn(c, sess, "two")
        assert r["result"] == "hit" and r["scene"]["phase"] == "choice"


def test_max_tries_moves_on_to_the_choice():
    with TestClient(app) as c:
        sess = opening(c)
        for _ in range(2):
            assert turn(c, sess, "seven")["retry"]
        r = turn(c, sess, "seven")
        assert r["result"] == "miss" and r["retry"] is False and r["stars"] == 0
        assert r["scene"]["id"] == "a1" and r["scene"]["phase"] == "choice" and r["scene"]["choices"]
        assert "'two'" in r["feedback"]  # the answer is modelled
        entry = SESSIONS[sess["session_id"]]["log"][-1]
        assert entry["action"] == "move_on" and entry["parent_note"]


def test_skip_on_the_question_goes_to_the_choice():
    with TestClient(app) as c:
        sess = opening(c)
        r = c.post("/turn", json={"session_id": sess["session_id"], "skip": True}).json()
        assert r["scene"]["id"] == "a1" and r["scene"]["phase"] == "choice"


def test_question_turns_are_logged_like_pip(monkeypatch):
    monkeypatch.setattr(adventure, "call_model", FakeWriter())
    with TestClient(app) as c:
        sess = start(c, child_name="Quinn")
        answer(c, sess)
        log = c.get(f"/progress/{sess['child_id']}").json()
    entry = log["agent_log"][-1]
    assert entry["scene"] == "a1" and entry["action"] == "advance" and entry["source"] == "rule"
    assert entry["story"] == "adventure" and entry["background"] == "sunrise-meadow"
    assert entry["question_type"] == "choice"  # what the child hears next: the story choice
    assert log["target_words_hit"] == 1 and "two" in log["new_words"]


# ---------- the agent asks the next page's question ----------

def test_agent_question_for_the_chosen_page(monkeypatch):
    monkeypatch.setattr(adventure, "call_model", FakeWriter())
    with TestClient(app) as c:
        sess = opening(c)
        s = SESSIONS[sess["session_id"]]
        assert wait_for(lambda: "a2-garden" in s["scenes"])
        answer(c, sess)
        ask = {"prompt": "Was it birds or bees?", "target_words": ["birds", "bees"], "level": 1,
               "question_type": "choice", "accept": ["birds"], "reason": "Level one, birds are in the page"}

        async def agent(messages):
            assert "NEXT SCENE NARRATION" in messages[0]["content"]
            return SimpleNamespace(stop_reason="tool_use", usage=None, content=[
                SimpleNamespace(type="tool_use", name="next_step",
                                input={"action": "advance", "say": "The garden it is!"}),
                SimpleNamespace(type="tool_use", name="ask", input=ask)])
        monkeypatch.setattr(tutor, "call_model", agent)
        r = turn(c, sess, "garden")
    assert r["scene"]["id"] == "a2-garden" and r["scene"]["phase"] == "question"
    assert r["scene"]["challenge"]["prompt"] == "Was it birds or bees?"
    assert s["log"][-1]["question_reason"] == ask["reason"]


def test_without_the_agent_the_page_question_is_the_backup(monkeypatch):
    monkeypatch.setattr(adventure, "call_model", FakeWriter())
    with TestClient(app) as c:
        sess = opening(c)
        answer(c, sess)
        r = turn(c, sess, "garden")  # conftest: the tutor agent fails
    assert r["scene"]["challenge"]["prompt"] == "What sang sweetly in the trees?"


# ---------- the generated question ----------

def test_valid_generated_question_is_kept():
    data = adventure.validate_page(page_input(2), 2)
    assert data["question"] == {"prompt": "What sang sweetly in the trees?", "target_words": ["birds"],
                                "question_type": "recall", "accept": ["birds", "bird"]}
    count = {"prompt": "How many times did the birds sing?", "question_type": "count", "accept": ["three"],
             "options": []}
    text = GOOD.replace("sang sweetly", "sang three times")
    q, why = adventure.clean_question(count, text)
    assert why is None and set(q["accept"]) == {"three", "3"}


def test_invalid_generated_question_falls_back_to_say_it(monkeypatch):
    bad = [
        {"prompt": "Did the birds sing? Yes, the birds!", "question_type": "recall", "accept": ["birds"], "options": []},
        {"prompt": "How many dragons were there?", "question_type": "count", "accept": ["nine"], "options": []},
        {"prompt": "What colour was the sky?", "question_type": "colour", "accept": ["purple"], "options": []},
        {"prompt": "Birds or bees?", "question_type": "choice", "accept": ["birds"], "options": ["birds"]},
        {"prompt": "Sing!", "question_type": "dance", "accept": [], "options": []},
        None,
    ]
    for raw in bad:
        q, why = adventure.clean_question(raw, GOOD)
        assert why and q["question_type"] == "say", raw
        assert q["target_words"][0] in GOOD.lower() and q["prompt"] == f"Can you say '{q['target_words'][0]}'?"
        assert q["target_words"][0] not in ("child", "name", "pet")  # placeholders are never targets

    monkeypatch.setattr(adventure, "call_model", FakeWriter(override={2: {"question": bad[0]}}))
    with TestClient(app) as c:
        sess = opening(c)
        answer(c, sess)
        r = turn(c, sess, "garden")
    assert r["scene"]["challenge"]["prompt"].startswith("Can you say '")


def test_fallback_pages_have_valid_questions():
    for page, choice in [(1, None), (2, {"word": "lake"}), (3, {"word": "zzz"})]:
        data = adventure.fallback_page(page, choice)
        q, why = adventure.clean_question({**data["question"], "options": []}, data["narration"])
        assert why is None and q["question_type"] in ("count", "recall")


# ---------- contract and Pip ----------

def test_phase_is_in_the_contract_and_null_for_pip():
    assert "phase" in CONTRACT["scene"]
    start_contract = json.loads(open("contract/session_start_response.json").read())
    assert "phase" in start_contract["scene"]
    with TestClient(app) as c:
        sess = c.post("/session/start", json={"child_name": "Pia", "pronouns": "she"}).json()
        assert sess["scene"]["phase"] is None and sess["scene"]["id"] == "s1"
        r = turn(c, sess, "lantern")
    assert r["scene"]["id"] == "s2" and r["scene"]["phase"] is None
    assert r["scene"]["choices"] == [{"word": "sun", "label": "Sun", "icon": "sun", "image_url": None},
                                     {"word": "moon", "label": "Moon", "icon": "moon", "image_url": None}]
