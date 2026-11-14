"""The child's drawn avatar is painted in the background and shown once ready. fal is never called.
Run:  pytest tests/test_avatar.py -v"""
import base64
import json
import threading

from fastapi.testclient import TestClient

from agent import main
from agent.main import SESSIONS, app
from tools import paint_avatar

client = TestClient(app)
PNG = b"\x89PNG\r\n\x1a\n" + b"fake drawing"
B64 = base64.b64encode(PNG).decode()
START = {"child_name": "Avi", "age": 5, "pronouns": "she",
         "avatar": {"hair_colour": "red", "pet": "fox", "image_png": B64}}


def start(c=client, **avatar):
    return c.post("/session/start", json={**START, "avatar": {**START["avatar"], **avatar}}).json()


def turn(sess, transcript="banana", c=client):
    return c.post("/turn", json={"session_id": sess["session_id"], "transcript": transcript}).json()


def test_no_drawing_means_no_avatar():
    sess = client.post("/session/start", json={"child_name": "Avi", "avatar": {"pet": "fox"}}).json()
    assert sess["avatar_url"] is None and sess["scene"]["avatar_url"] is None
    assert turn(sess)["scene"]["avatar_url"] is None


def test_painting_never_blocks_and_appears_on_the_next_turn(monkeypatch):
    release, calls = threading.Event(), []

    def slow_paint(png):
        calls.append(png)
        release.wait(5)
        return "/static/avatars/abc.png"
    monkeypatch.setattr(paint_avatar, "paint", slow_paint)

    with TestClient(app) as c:  # one event loop for all requests, as under uvicorn
        sess = start(c)  # returns while paint is still blocked
        assert sess["avatar_url"] is None and sess["scene"]["avatar_url"] is None
        assert turn(sess, c=c)["scene"]["avatar_url"] is None  # not ready yet
        release.set()
        for _ in range(100):  # let the worker thread finish
            if SESSIONS[sess["session_id"]]["avatar_path"]:
                break
            threading.Event().wait(0.02)
        url = turn(sess, c=c)["scene"]["avatar_url"]
    assert calls == [PNG]
    assert url.startswith("http") and url.endswith("/static/avatars/abc.png")


def test_cached_avatar_is_in_the_start_response(monkeypatch):
    paint_avatar.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    (paint_avatar.AVATAR_DIR / f"{paint_avatar.cache_key(PNG)}.png").write_bytes(PNG)
    monkeypatch.setattr(paint_avatar, "paint", lambda png: (_ for _ in ()).throw(AssertionError("not cached")))
    sess = start()
    expected = f"/static/avatars/{paint_avatar.cache_key(PNG)}.png"
    assert sess["avatar_url"].endswith(expected)
    assert sess["scene"]["avatar_url"].endswith(expected)


def test_data_url_prefix_is_accepted(monkeypatch):
    seen = []
    monkeypatch.setattr(paint_avatar, "paint", lambda png: seen.append(png) or None)
    with TestClient(app) as c:
        start(c, image_png=f"data:image/png;base64,{B64}")
        for _ in range(100):
            if seen:
                break
            threading.Event().wait(0.02)
    assert seen == [PNG]


def test_failed_painting_or_bad_input_keeps_avatar_null(monkeypatch):
    seen = []
    monkeypatch.setattr(paint_avatar, "paint", lambda png: seen.append(png) or None)  # e.g. no FAL_KEY
    with TestClient(app) as c:
        sess = start(c)
        for _ in range(100):
            if seen:
                break
            threading.Event().wait(0.02)
        assert turn(sess, c=c)["scene"]["avatar_url"] is None
        for bad in ["not base64!!", base64.b64encode(b"GIF89a").decode(), 123]:
            sess = start(c, image_png=bad)
            assert sess["avatar_url"] is None
    assert seen == [PNG]  # invalid drawings are never sent to paint


def test_drawing_is_not_stored(caplog):
    main.CHILDREN.pop("avi-1", None)
    with caplog.at_level("INFO"):
        sess = start()
        turn(sess)
    stored = json.dumps({"session": SESSIONS[sess["session_id"]], "child": main.CHILDREN[sess["child_id"]]},
                        default=str)
    assert B64 not in stored and "image_png" not in stored
    assert B64 not in caplog.text
    assert main.CHILDREN[sess["child_id"]]["avatar"] == {"hair_colour": "red", "pet": "fox"}
