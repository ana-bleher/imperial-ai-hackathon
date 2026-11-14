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
