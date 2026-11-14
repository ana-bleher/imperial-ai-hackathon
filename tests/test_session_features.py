"""Privacy of the turn log, stars, goodnight, progress summary, resume and warm-up.
Run:  pytest tests/test_session_features.py -v"""
import json

from fastapi.testclient import TestClient

from agent import main, tutor
from agent.main import SCENES, SESSIONS, STORY, app

client = TestClient(app)
START = {"child_name": "Zoe", "age": 5, "pronouns": "she", "avatar": {"pet": "owl"}}


def start(**extra):
    return client.post("/session/start", json={**START, **extra}).json()


def turn(sess, transcript):
    return client.post("/turn", json={"session_id": sess["session_id"], "transcript": transcript}).json()


def right_answer(scene):
    dec = SCENES[scene["id"]].get("decision") or {}
    if dec.get("correct_word"):
        return dec["correct_word"]
    if scene["choices"]:
        return scene["choices"][-1]["word"]
    return " ".join(scene["challenge"]["target_words"])


# ---------- privacy ----------

def test_log_never_stores_the_transcript(caplog):
    sess = start()
    word = sess["scene"]["challenge"]["target_words"][0]
    with caplog.at_level("INFO"):
        r = turn(sess, f"{word} my secret password")
    assert r["transcript"] == f"{word} my secret password"  # still shown to the frontend
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert "transcript" not in entry
    assert entry["matched_word"] == word and entry["word_count"] == 4
    assert "secret" not in json.dumps(SESSIONS[sess["session_id"]]["log"])
    assert "secret" not in caplog.text
    assert "secret" not in json.dumps(client.get(f"/progress/{sess['child_id']}").json())


def test_miss_has_no_matched_word_and_avg_length_uses_word_count():
    main.CHILDREN.pop("ana-1", None)
    sess = client.post("/session/start", json={**START, "child_name": "Ana"}).json()
    turn(sess, "banana banana")
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert entry["matched_word"] is None and entry["word_count"] == 2
    assert client.get(f"/progress/{sess['child_id']}").json()["avg_answer_length"] == 2


# ---------- stars ----------

def test_stars_first_try_bonus_and_retry():
    sess = start()
    assert sess["stars"] == 0
    r = turn(sess, right_answer(sess["scene"]))
    assert r["stars"] == 2  # completed on the first try: 1 + bonus
    r = turn(sess, "pizza")  # quiz miss: no star yet
    assert r["retry"] and r["stars"] == 2
    r = turn(sess, right_answer(r["scene"]))
    assert r["stars"] == 3  # completed, but not on the first try


def test_silence_does_not_cost_the_first_try_bonus():
    sess = start()
    assert turn(sess, "")["stars"] == 0
    assert turn(sess, right_answer(sess["scene"]))["stars"] == 2


# ---------- goodnight ----------

def test_story_complete_ends_with_named_goodnight():
    sess = start()
    scene = sess["scene"]
    for _ in range(40):
        r = turn(sess, right_answer(scene))
        if r["story_complete"]:
            break
        scene = r["scene"]
    assert r["story_complete"]
    fb = r["feedback"]
    assert "Goodnight" in fb and "Zoe" in fb and "owl" in fb
    assert fb.count(".") + fb.count("!") + fb.count("?") == 1  # one sentence
    assert r["stars"] >= 2 * 5 - 1


# ---------- dashboard summary ----------

def test_progress_summary():
    main.CHILDREN.pop("lou-1", None)
    sess = client.post("/session/start", json={**START, "child_name": "Lou"}).json()
    first_word = sess["scene"]["challenge"]["target_words"][0]
    turn(sess, right_answer(sess["scene"]))   # s1 first try
    turn(sess, "moon")                         # s2 quiz miss
    turn(sess, "sun")                          # s2 hit on try 2
    p = client.get(f"/progress/{sess['child_id']}").json()
    s = p["summary"]
    assert s["stars_tonight"] == 3
    assert s["words_practised"] == [first_word, "sun"]
    assert s["needed_help"] == ["sun"]
    assert "Lou" in s["agent_note"] and "3 stars" in s["agent_note"]
    assert {"sessions", "attempts", "new_words", "agent_log"} <= set(p)  # existing fields kept


def test_summary_agent_note_is_latest_parent_note():
    main.CHILDREN.pop("kai-1", None)
    sess = client.post("/session/start", json={**START, "child_name": "Kai"}).json()
    for _ in range(3):
        turn(sess, "pizza")  # attempts used up on s1: moved on with a parent note
    s = client.get(f"/progress/{sess['child_id']}").json()["summary"]
    assert s["agent_note"].startswith("Struggled with")
    assert s["needed_help"] and s["stars_tonight"] == 0


# ---------- resume ----------

def test_resume_valid_scene():
    target = next(s for s in STORY["scenes"] if s["id"] != STORY["start_scene"])
    sess = start(resume_scene_id=target["id"])
    assert sess["scene"]["id"] == target["id"]
    assert sess["scene"]["challenge"]["prompt"]


def test_resume_invalid_is_ignored():
    for bad in ("nope", None, 7):
        assert start(resume_scene_id=bad)["scene"]["id"] == STORY["start_scene"]


# ---------- warm-up ----------

def test_session_start_fires_warm_up(monkeypatch):
    calls = []

    async def fake():
        calls.append(1)
    monkeypatch.setattr(tutor, "warm_up", fake)
    start()
    assert calls == [1]
