"""Backend fixes from REVIEW.md. No network: the agent, voice and fal are mocked.
Run:  pytest tests/test_review_fixes.py -v"""
import asyncio
import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import fallback as fb
from agent import main, tutor
from agent.main import SESSIONS, app
from tools import paint_avatar, voice
from tools.get_child_state import get_child_state

client = TestClient(app)
REAL_CALL_MODEL = tutor.call_model  # captured at import, before conftest's fixture replaces it
START = {"child_name": "Ravi", "age": 5, "pronouns": "he", "avatar": {"pet": "owl"}}


def start(**extra):
    return client.post("/session/start", json={**START, **extra}).json()


def turn(sess, transcript):
    return client.post("/turn", json={"session_id": sess["session_id"], "transcript": transcript}).json()


def skip(sess):
    return client.post("/turn", json={"session_id": sess["session_id"], "skip": True}).json()


# ---------- agent call ----------

def test_anthropic_call_has_no_thinking(monkeypatch):
    seen = {}

    class Messages:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace()
    monkeypatch.setattr(tutor, "client", lambda: SimpleNamespace(messages=Messages()))
    asyncio.run(REAL_CALL_MODEL([]))  # conftest replaces tutor.call_model during tests
    assert "thinking" not in seen and seen["output_config"] == {"effort": "low"}


# ---------- progress ----------

def test_progress_unknown_child_is_404():
    r = client.get("/progress/nobody-1")
    assert r.status_code == 404
    assert not hasattr(main, "MOCK_PROGRESS")


def test_agent_log_source_rule_and_agent(monkeypatch):
    main.CHILDREN.pop("ravi-1", None)
    sess = start()
    turn(sess, "lantern")  # agent offline: the rule decides
    word = "sun"

    async def agent(messages):
        return SimpleNamespace(stop_reason="tool_use", usage=None, content=[
            SimpleNamespace(type="tool_use", name="next_step",
                            input={"action": "advance", "say": "Yes, the sun, well done!"})])
    monkeypatch.setattr(tutor, "call_model", agent)
    turn(sess, word)
    log = client.get(f"/progress/{sess['child_id']}").json()["agent_log"]
    assert [e["source"] for e in log[-2:]] == ["rule", "agent"]


# ---------- avatar traits ----------

def test_hex_traits_become_words():
    sentence = paint_avatar.traits_sentence({"skin_tone": "#B97450", "hair_colour": "#a94d31",
                                             "hair_style": "curly", "outfit": "raincoat"})
    assert sentence.startswith("The child has warm tan skin, red curly hair, and wears a raincoat.")
    for hex_, word in {**paint_avatar.SKIN_TONES, **paint_avatar.HAIR_COLOURS}.items():
        assert paint_avatar.colour_word(hex_.upper(), {**paint_avatar.SKIN_TONES, **paint_avatar.HAIR_COLOURS}) == word


def test_unknown_hex_by_brightness_and_words_pass_through():
    clean = paint_avatar.clean_traits
    assert clean({"skin_tone": "#FFEEDD"})["skin_tone"] == "light"
    assert clean({"skin_tone": "#8A6A50"})["skin_tone"] == "medium"
    assert clean({"hair_colour": "#101010"})["hair_colour"] == "deep"
    assert clean({"skin_tone": "medium", "hair_colour": "dark brown"}) == {"skin_tone": "medium",
                                                                          "hair_colour": "dark brown"}
    assert paint_avatar.cache_key(b"x", {"skin_tone": "#B97450"}) == paint_avatar.cache_key(b"x", {"skin_tone": "warm tan"})


# ---------- turn timeout ----------

def test_slow_challenge_audio_never_holds_the_turn(monkeypatch):
    monkeypatch.setattr(main, "VOICE_TIMEOUT", 0.2)
    monkeypatch.setattr(main, "CHALLENGE", {})

    def slow_speak(text):
        time.sleep(1.5)
        return "/static/audio/slow.mp3"
    with TestClient(app) as c:  # one event loop, as under uvicorn
        sess = c.post("/session/start", json=START).json()
        monkeypatch.setattr(voice, "speak", slow_speak)
        began = time.perf_counter()
        r = c.post("/turn", json={"session_id": sess["session_id"], "transcript": "lantern"}).json()
        took = time.perf_counter() - began
    assert took < 1.0
    assert r["scene"]["challenge_audio_url"] is None
    assert main.CHALLENGE  # the speech task was started and kept for the next request


def test_challenge_path_within_keeps_the_task_running(monkeypatch):
    async def run():
        release = asyncio.Event()

        async def slow(_):
            await release.wait()
            return "/static/audio/c.mp3"
        monkeypatch.setattr(main, "challenge_path", slow)
        got = await main.challenge_path_within({}, 0.05)
        release.set()
        return got
    assert asyncio.run(run()) is None


# ---------- practice words ----------

def test_practice_words_cleaned_stored_and_in_child_state():
    sess = start(practice_words=["Lantern", "river!", "x2", "River", "moon", "sun", "fish", "bells"])
    s = SESSIONS[sess["session_id"]]
    assert s["practice_words"] == ["lantern", "river", "moon", "sun", "fish"]  # "river!" and "x2" dropped
    assert get_child_state(s)["practice_words"] == s["practice_words"]
    assert start(practice_words="lantern")["session_id"]  # not a list: ignored


def test_key_word_prefers_practice_words_in_the_narration():
    narration = "Mia steps into a quiet forest. A sleepy owl hoots hello."
    assert fb.pick_key_word(narration) == "forest"
    assert fb.pick_key_word(narration, prefer=["moon", "owl"]) == "owl"  # moon is not in this scene
    state = {**fb.new_session_state(), "practice_words": ["sleepy"]}
    fb.enter_scene(state, {"id": "x", "narration": narration, "next": None}, narration)
    assert state["key_word"] == "sleepy" and state["challenge"]["target_words"] == ["sleepy"]


# ---------- safety ----------

def test_child_name_is_capped_and_cleaned():
    for raw, expected in [("Mia<script>alert(1)</script>", "Miascriptalertscript"),
                          ("Anne-Marie   O'Neil", "Anne-Marie ONeil"),
                          ("A" * 40, "A" * 20), ("", "Friend"), (123, "Friend"), ("!!!", "Friend")]:
        sess = client.post("/session/start", json={**START, "child_name": raw}).json()
        assert SESSIONS[sess["session_id"]]["child"]["child_name"] == expected


def test_agent_question_repeating_child_words_is_rejected(monkeypatch):
    scene = {"id": "x", "narration": "Mia steps into a quiet forest. A sleepy owl hoots hello.", "next": "y"}
    s = {"child": {"child_name": "Mia", "pronouns": "she", "avatar": {}}, "log": [], **fb.new_session_state()}
    fb.enter_scene(s, scene, scene["narration"], exclude={"mia"})

    async def agent(messages):
        return SimpleNamespace(stop_reason="tool_use", usage=None, content=[
            SimpleNamespace(type="tool_use", name=n, input=i) for n, i in [
                ("assess", {"result": "miss", "reason": "Not heard"}), ("set_difficulty", {"level": 1}),
                ("next_step", {"action": "retry_with_hint", "say": "Let's find the owl!"}),
                ("ask", {"prompt": "Zorblax, can you say 'owl'?", "target_words": ["owl"], "level": 1,
                         "question_type": "say", "accept": [], "reason": "Easier word"})]])
    monkeypatch.setattr(tutor, "call_model", agent)
    vocab = set(fb.words(json.dumps(scene))) | {"mia"}
    d, meta = asyncio.run(tutor.decide(s, scene, scene["narration"], "zorblax",
                                       next_narration=None, name_words={"mia"}, vocab=vocab))
    assert meta["source"] == "fallback" and "question repeats" in meta["fallback_reason"]
    assert "zorblax" not in json.dumps(d).lower()


# ---------- skip ----------

def test_skip_moves_on_without_assessment_or_stars():
    sess = start(child_name="Skipper")
    r = skip(sess)
    assert r["result"] == "skipped" and not r["retry"] and r["stars"] == 0
    assert r["scene"]["id"] == "s2"
    entry = SESSIONS[sess["session_id"]]["log"][-1]
    assert entry["action"] == "skipped" and entry["result"] == "skipped" and entry["matched_word"] is None
    p = client.get(f"/progress/{sess['child_id']}").json()
    assert p["attempts"] == 0 and p["target_words_hit"] == 0
    assert p["agent_log"][-1]["action"] == "skipped" and p["agent_log"][-1]["source"] == "rule"


def test_skip_through_the_whole_story():
    sess = start()
    seen = []
    r = {"scene": sess["scene"]}
    while r["scene"]:
        seen.append(r["scene"]["id"])
        r = skip(sess)
    assert seen == ["s1", "s2", "s3", "s4a", "s5a"]  # a branch skip takes the first branch
    assert r["story_complete"] and r["feedback"].startswith("Goodnight, Ravi")
    assert SESSIONS[sess["session_id"]]["stars"] == 0
