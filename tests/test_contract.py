"""Checks every endpoint returns every field in contract/*.json.

Run:  pytest tests/
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent.main import app

CONTRACT = Path(__file__).resolve().parent.parent / "contract"
client = TestClient(app)


def load(name):
    return json.loads((CONTRACT / name).read_text())


def assert_same_keys(expected, actual, path="root"):
    """Every key in the example must exist in the response, recursively."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected object, got {actual!r}"
        for key, value in expected.items():
            assert key in actual, f"{path}.{key} missing"
            if value is not None and actual[key] is not None:
                assert_same_keys(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list) and expected:
        assert isinstance(actual, list), f"{path}: expected list, got {actual!r}"
        for i, item in enumerate(actual):
            assert_same_keys(expected[0], item, f"{path}[{i}]")


def start():
    r = client.post("/session/start", json=load("session_start_request.json"))
    assert r.status_code == 200
    return r.json()


def test_session_start():
    body = start()
    assert_same_keys(load("session_start_response.json"), body)
    assert body["avatar_url"] is None


def test_scene_shape():
    scene = start()["scene"]
    expected = load("session_start_response.json")["scene"]
    assert set(expected) <= set(scene)
    assert set(expected["challenge"]) <= set(scene["challenge"])
    assert set(expected["avatar_position"]) <= set(scene["avatar_position"])
    if scene["choices"] is not None:
        for choice in scene["choices"]:
            assert {"word", "label", "icon"} <= set(choice)


def test_turn_json():
    sess = start()
    word = sess["scene"]["challenge"]["target_words"][0]
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": word})
    assert r.status_code == 200
    body = r.json()
    assert_same_keys(load("turn_response.json"), body)
    assert body["result"] == "hit"


def test_turn_multipart_audio():
    sess = start()
    r = client.post("/turn", data={"session_id": sess["session_id"]},
                    files={"audio": ("clip.webm", b"fake-audio", "audio/webm")})
    assert r.status_code == 200
    assert_same_keys(load("turn_response.json"), r.json())


def test_turn_miss_retries():
    sess = start()
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": "banana"}).json()
    assert r["retry"] is True
    assert r["scene"]["id"] == sess["scene"]["id"]


def test_progress():
    sess = start()
    client.post("/turn", json={"session_id": sess["session_id"],
                               "transcript": sess["scene"]["challenge"]["target_words"][0]})
    r = client.get(f"/progress/{sess['child_id']}")
    assert r.status_code == 200
    assert_same_keys(load("progress_response.json"), r.json())


def test_challenge_audio_null_when_voice_fails():
    sess = start()
    assert sess["scene"]["challenge_audio_url"] is None
    word = sess["scene"]["challenge"]["target_words"][0]
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": word}).json()
    assert r["scene"]["challenge_audio_url"] is None


def test_challenge_audio_url_and_cache(monkeypatch):
    from agent import main
    from tools import voice

    spoken = []

    def fake_speak(text):
        spoken.append(text)
        return f"/static/audio/{len(spoken)}.mp3"
    monkeypatch.setattr(voice, "speak", fake_speak)
    monkeypatch.setattr(main, "CHALLENGE", {})

    sess = start()
    prompt = sess["scene"]["challenge"]["prompt"]
    assert sess["scene"]["challenge_audio_url"].startswith("http")
    assert sess["scene"]["challenge_audio_url"].endswith(".mp3")
    assert spoken.count(prompt) == 1

    # A miss keeps the scene; the retry challenge gets its own audio, and repeats come from the cache.
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": "banana"}).json()
    assert r["retry"] is True
    assert r["scene"]["challenge_audio_url"] is not None
    assert r["feedback_audio_url"] is not None


def test_challenge_audio_cached_per_prompt(monkeypatch):
    import asyncio
    from agent import main
    from tools import voice

    spoken = []

    def fake_speak(text):
        spoken.append(text)
        return "/static/audio/c.mp3"
    monkeypatch.setattr(voice, "speak", fake_speak)
    monkeypatch.setattr(main, "CHALLENGE", {})

    async def run():
        sess = {"challenge": {"level": 1, "prompt": "Can you say 'moon'?", "target_words": ["moon"]}}
        paths = [await main.challenge_path(sess), await main.challenge_path(dict(sess))]
        sess["challenge"] = None
        return paths, await main.challenge_path(sess)
    paths, none_path = asyncio.run(run())
    assert paths == ["/static/audio/c.mp3"] * 2
    assert spoken == ["Can you say 'moon'?"]  # spoken once, then served from the cache
    assert none_path is None


def test_turn_does_not_wait_for_slow_narration_but_keeps_generating(monkeypatch):
    import asyncio
    from agent import main

    async def run():
        sess = {"child": {"child_name": "Mia", "avatar": {}}}
        sid = next(iter(main.SCENES))
        slow = asyncio.get_running_loop().create_future()
        monkeypatch.setattr(main, "narration_task", lambda s, i: slow)
        assert await main.narration_path(sess, sid, wait=0.01) is None  # gave up waiting
        assert not slow.cancelled()                                       # still running
        slow.set_result("/static/audio/n.mp3")
        assert await main.narration_path(sess, sid, wait=0.01) == "/static/audio/n.mp3"
    asyncio.run(run())


def test_voice_timeout_argument():
    import asyncio
    import time
    from agent import main

    def slow():
        time.sleep(0.2)
        return "done"
    assert asyncio.run(main.voice(slow, timeout=0.01)) is None
    assert asyncio.run(main.voice(slow, timeout=1)) == "done"
