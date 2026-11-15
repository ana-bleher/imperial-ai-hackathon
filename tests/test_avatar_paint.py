"""POST /avatar/paint: pre-paint the avatar on the profile screen. fal is never called (paint is mocked).
Run:  pytest tests/test_avatar_paint.py -v"""
import base64
import json
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from agent import main
from agent.main import SESSIONS, app
from tools import paint_avatar

CONTRACT = Path(__file__).resolve().parent.parent / "contract"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake drawing"
B64 = base64.b64encode(PNG).decode()
TRAITS = {"skin_tone": "medium", "hair_style": "curly", "hair_colour": "red", "outfit": "raincoat"}
AVATAR = {**TRAITS, "pet": "fox", "image_png": B64}


def paint(c, **avatar):
    return c.post("/avatar/paint", json={"avatar": {**AVATAR, **avatar}}).json()


def blocked_paint(monkeypatch):
    """A fake paint() that waits until released; records each call."""
    release, calls = threading.Event(), []

    def slow(png, traits=None):
        calls.append(traits)
        release.wait(5)
        return "/static/avatars/painted.png"
    monkeypatch.setattr(paint_avatar, "paint", slow)
    return release, calls


def wait_until(check):
    for _ in range(200):
        if check():
            return True
        threading.Event().wait(0.02)
    return False


def cache(png=PNG, traits=TRAITS):
    paint_avatar.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    key = paint_avatar.cache_key(png, traits)
    (paint_avatar.AVATAR_DIR / f"{key}.png").write_bytes(PNG)
    return f"/static/avatars/{key}.png"


def test_ready_when_cached(monkeypatch):
    path = cache()
    monkeypatch.setattr(paint_avatar, "paint", lambda *a: (_ for _ in ()).throw(AssertionError("not cached")))
    body = paint(TestClient(app))
    assert body["status"] == "ready"
    assert body["avatar_url"].startswith("http") and body["avatar_url"].endswith(path)


def test_painting_starts_once_even_if_called_twice(monkeypatch):
    release, calls = blocked_paint(monkeypatch)
    with TestClient(app) as c:
        assert paint(c) == {"status": "painting", "avatar_url": None}
        assert paint(c) == {"status": "painting", "avatar_url": None}  # already running
        assert wait_until(lambda: calls)
        release.set()
        assert wait_until(lambda: not main.AVATAR_TASKS)
    assert calls == [TRAITS]  # one painting, traits only (never the drawing)


def test_session_start_reuses_the_running_task_and_gets_the_url(monkeypatch):
    release, calls = blocked_paint(monkeypatch)
    with TestClient(app) as c:
        assert paint(c)["status"] == "painting"
        sess = c.post("/session/start", json={"child_name": "Avi", "avatar": AVATAR}).json()
        assert sess["avatar_url"] is None  # still painting
        release.set()
        assert wait_until(lambda: SESSIONS[sess["session_id"]]["avatar_path"])
        url = c.post("/turn", json={"session_id": sess["session_id"], "transcript": "banana"}
                     ).json()["scene"]["avatar_url"]
    assert calls == [TRAITS]  # /session/start did not start a second painting
    assert url.endswith("/static/avatars/painted.png")


def test_same_traits_with_different_png_bytes_hit_the_same_cache(monkeypatch):
    path = cache()
    monkeypatch.setattr(paint_avatar, "paint", lambda *a: (_ for _ in ()).throw(AssertionError("not cached")))
    other = base64.b64encode(PNG + b" rendered slightly differently").decode()
    c = TestClient(app)
    assert paint(c, image_png=other) == {"status": "ready", "avatar_url": paint(c)["avatar_url"]}
    sess = c.post("/session/start", json={"child_name": "Avi", "avatar": {**AVATAR, "image_png": other}}).json()
    assert sess["avatar_url"].endswith(path)


def test_skipped_when_paint_avatar_0(monkeypatch):
    monkeypatch.setenv("PAINT_AVATAR", "0")
    cache()  # even a cached avatar is not used
    monkeypatch.setattr(paint_avatar, "paint", lambda *a: (_ for _ in ()).throw(AssertionError("painted")))
    assert paint(TestClient(app)) == {"status": "skipped", "avatar_url": None}


def test_skipped_without_fal_key_or_with_a_bad_drawing(monkeypatch):
    monkeypatch.setattr(paint_avatar, "paint", lambda *a: (_ for _ in ()).throw(AssertionError("painted")))
    c = TestClient(app)
    for bad in ["not base64!!", base64.b64encode(b"GIF89a").decode(), 123, None]:
        assert paint(c, image_png=bad) == {"status": "skipped", "avatar_url": None}
    assert c.post("/avatar/paint", json={}).json()["status"] == "skipped"
    monkeypatch.setattr(paint_avatar, "has_fal_key", lambda: False)
    assert paint(c) == {"status": "skipped", "avatar_url": None}


def test_drawing_is_never_logged(monkeypatch, caplog):
    release, _ = blocked_paint(monkeypatch)
    with caplog.at_level("DEBUG"), TestClient(app) as c:
        paint(c)
        release.set()
        wait_until(lambda: not main.AVATAR_TASKS)
    assert B64 not in caplog.text


def test_contract_examples():
    request = json.loads((CONTRACT / "avatar_paint_request.json").read_text())
    expected = json.loads((CONTRACT / "avatar_paint_response.json").read_text())
    body = TestClient(app).post("/avatar/paint", json=request).json()
    assert set(expected) <= set(body)
    assert body["status"] in ("ready", "painting", "skipped")
