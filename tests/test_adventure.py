"""'Your own adventure' mode. The page generator is mocked (adventure.call_model); Claude is never called.
Run:  pytest tests/test_adventure.py -v"""
import asyncio
import re
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import adventure, main
from agent.main import SCENES, SESSIONS, app

START = {"child_name": "Lila", "age": 5, "pronouns": "she", "avatar": {"pet": "bunny"}}
CHOICES = {1: ["garden", "beach"], 2: ["lake", "forest"], 3: ["cottage", "bedroom"]}
BACKGROUND = {1: "sunrise-meadow", 2: "wildflower-garden", 3: "lighthouse-cliff", 4: "bedtime-bedroom"}
GOOD = ("{CHILD_NAME} and {PET} walked along a soft green path. The sun was warm and the birds sang "
        "sweetly in the trees. They smiled at the flowers and listened to the gentle breeze. "
        "What a lovely, cosy day it was for a little adventure together.")


def page_input(page: int, **override) -> dict:
    data = {"narration": GOOD + (" Goodnight." if page == 4 else ""), "background_id": BACKGROUND[page],
            "choices": [] if page == 4 else [{"word": w, "label": f"Go to the {w}"} for w in CHOICES[page]],
            "ending": page == 4}
    return {**data, **override}


class FakeWriter:
    """Writes a valid page for whatever page the message asks for. Optional delay per page."""

    def __init__(self, delay: dict | None = None, override: dict | None = None):
        self.delay, self.override, self.messages = delay or {}, override or {}, []

    async def __call__(self, message: str):
        self.messages.append(message)
        page = int(re.search(r"PAGE: (\d)", message).group(1))
        if self.delay.get(page):
            await asyncio.sleep(self.delay[page])
        return SimpleNamespace(content=[SimpleNamespace(
            type="tool_use", name="write_page", input=page_input(page, **self.override.get(page, {})))])


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def start(c, **extra):
    return c.post("/session/start", json={**START, "story": "adventure", **extra}).json()


def turn(c, sess, transcript):
    return c.post("/turn", json={"session_id": sess["session_id"], "transcript": transcript}).json()


# ---------- validation ----------

def test_valid_page_is_accepted():
    for page in (1, 2, 3, 4):
        data = adventure.validate_page(page_input(page), page)
        assert data["background_id"] == BACKGROUND[page]
        assert len(data["choices"]) == (0 if page == 4 else 2)


@pytest.mark.parametrize("page,override,why", [
    (1, {"background_id": "space-station"}, "unknown background"),
    (1, {"narration": GOOD.replace("{CHILD_NAME}", "Lila")}, "CHILD_NAME"),
    (1, {"narration": GOOD.replace("gentle breeze", "scary monster")}, "scary"),
    (1, {"choices": [{"word": w, "label": w} for w in ("lake", "hill", "cave")]}, "exactly 2"),
    (1, {"choices": [{"word": "lake", "label": "Lake"}, {"word": "lake", "label": "Lake again"}]}, "different"),
    (1, {"choices": [{"word": "Lake", "label": "Lake"}, {"word": "hill", "label": "Hill"}]}, "lowercase"),
    (1, {"choices": [{"word": "lake", "label": "x" * 31}, {"word": "hill", "label": "Hill"}]}, "1-30"),
    (1, {"narration": "{CHILD_NAME} and {PET} smiled."}, "words, needs"),
    (2, {"background_id": "cozy-cottage", "ending": False}, "ending background"),
    (4, {"background_id": "riverside"}, "ending background"),
    (4, {"choices": [{"word": "lake", "label": "Lake"}, {"word": "hill", "label": "Hill"}]}, "no choices"),
])
def test_bad_pages_are_rejected_and_fall_back(monkeypatch, page, override, why):
    with pytest.raises(ValueError, match=why):
        adventure.validate_page(page_input(page, **override), page)
    monkeypatch.setattr(adventure, "call_model", FakeWriter(override={page: override}))
    data, reason = asyncio.run(adventure.generate_page(page, [], "bunny", {"word": "lake", "label": "Lake"}))
    assert reason and "invalid page" in reason
    assert data == adventure.fallback_page(page, {"word": "lake", "label": "Lake"})


def test_fallback_pages_pass_validation():
    pages = [(1, None), (2, {"word": "beach"}), (2, {"word": "zzz"}), (3, {"word": "lake"}),
             (4, {"word": "cottage"}), (4, {"word": "home"})]
    for page, choice in pages:
        adventure.validate_page({**adventure.fallback_page(page, choice), "ending": page == 4}, page)
    assert adventure.fallback_page(2, {"word": "beach"})["background_id"] == "sandy-beach"
    assert adventure.fallback_page(4, {"word": "cottage"})["background_id"] == "cozy-cottage"


def test_slow_generation_falls_back(monkeypatch):
    monkeypatch.setattr(adventure, "GENERATE_TIMEOUT", 0.05)
    monkeypatch.setattr(adventure, "call_model", FakeWriter(delay={1: 1}))
    data, reason = asyncio.run(adventure.generate_page(1, [], "bunny", None))
    assert "took over" in reason and data["background_id"] == "sunrise-meadow"


# ---------- the mode over HTTP ----------

def test_start_writes_page_one_in_the_scene_shape(monkeypatch):
    writer = FakeWriter()
    monkeypatch.setattr(adventure, "call_model", writer)
    with TestClient(app) as c:
        sess = start(c)
    scene = sess["scene"]
    assert scene["id"] == "a1" and scene["index"] == 1 and scene["total"] == 4
    assert scene["narration"].startswith("Lila and her bunny walked")
    assert scene["image_url"].endswith("/static/backgrounds/01-sunrise-meadow-watercolour-bg.jpg")
    assert scene["avatar_position"] == adventure.BACKGROUNDS["sunrise-meadow"]["avatar_position"]
    assert scene["choices"] == [{"word": "garden", "label": "Go to the garden", "icon": None},
                                {"word": "beach", "label": "Go to the beach", "icon": None}]
    assert sess["intro"]["text"].startswith("Your own adventure. Hello Lila!")
    assert "Lila" not in writer.messages[0]  # the child's name never goes to the model
    assert "PAGE: 1 of 4" in writer.messages[0] and "sunrise-meadow" in writer.messages[0]


def test_start_falls_back_to_the_meadow_opening():
    with TestClient(app) as c:  # conftest: the generator fails
        sess = start(c)
    assert sess["scene"]["id"] == "a1" and "sunny meadow" in sess["scene"]["narration"]
    assert SESSIONS[sess["session_id"]]["scenes"]["a1"]["fallback"]


def test_prefetched_page_is_used_instantly(monkeypatch):
    writer = FakeWriter()
    monkeypatch.setattr(adventure, "call_model", writer)
    with TestClient(app) as c:
        sess = start(c)
        s = SESSIONS[sess["session_id"]]
        assert wait_for(lambda: {"a2-garden", "a2-beach"} <= set(s["scenes"]))  # both written in parallel
        assert sum("THE CHILD JUST CHOSE: garden" in m for m in writer.messages) == 1
        writer.delay = {2: 5}  # any new page-2 writing now would be slow
        began = time.perf_counter()
        r = turn(c, sess, "garden")
        assert time.perf_counter() - began < 1
    assert r["scene"]["id"] == "a2-garden" and r["scene"]["index"] == 2
    assert not s["scenes"]["a2-garden"]["fallback"]
    assert r["scene"]["image_url"].endswith("02-wildflower-garden-watercolour-bg.jpg")


def test_slow_page_uses_a_fallback_page(monkeypatch):
    monkeypatch.setattr(main, "PAGE_WAIT", 0.1)
    monkeypatch.setattr(adventure, "call_model", FakeWriter(delay={2: 1}))
    with TestClient(app) as c:
        sess = start(c)
        r = turn(c, sess, "beach")
        s = SESSIONS[sess["session_id"]]
        assert r["scene"]["id"] == "a2-beach" and s["scenes"]["a2-beach"]["fallback"]
        assert r["scene"]["narration"].startswith("The path led on")
        assert s["scenes"]["a2-beach"]["background_id"] == "sandy-beach"  # matches the chosen word
        assert r["scene"]["image_url"].endswith(adventure.BACKGROUNDS["sandy-beach"]["url"])
        time.sleep(1.2)  # the late page does not replace the one already shown
        assert s["scenes"]["a2-beach"]["fallback"]


def test_page_four_is_a_goodnight_ending(monkeypatch):
    monkeypatch.setattr(adventure, "call_model", FakeWriter())
    with TestClient(app) as c:
        sess = start(c)
        for word in ("garden", "lake", "cottage"):
            r = turn(c, sess, word)
            assert not r["retry"], r
        scene = r["scene"]
        assert scene["id"] == "a4-cottage" and scene["index"] == 4 and scene["total"] == 4
        assert scene["choices"] is None and scene["narration"].endswith("Goodnight.")
        assert scene["challenge"]["prompt"] == "Can you whisper 'goodnight'?"
        assert scene["challenge"]["target_words"] == ["goodnight"]
        r = turn(c, sess, "goodnight")
        assert r["story_complete"] and r["scene"] is None and r["feedback"].startswith("Goodnight, Lila")
        log = c.get(f"/progress/{sess['child_id']}").json()["agent_log"]
    assert [e["story"] for e in log[-4:]] == ["adventure"] * 4
    assert [e["background"] for e in log[-4:]] == [BACKGROUND[p] for p in (1, 2, 3, 4)]
    s = SESSIONS[sess["session_id"]]
    assert [p["id"] for p in main.story_so_far(s, "a4-cottage")] == ["a1", "a2-garden", "a3-lake", "a4-cottage"]


def test_story_so_far_and_choice_go_to_the_writer(monkeypatch):
    writer = FakeWriter()
    monkeypatch.setattr(adventure, "call_model", writer)
    with TestClient(app) as c:
        sess = start(c)
        turn(c, sess, "garden")
        s = SESSIONS[sess["session_id"]]
        assert wait_for(lambda: "a3-lake" in s["scenes"])
    page3 = next(m for m in writer.messages if "PAGE: 3" in m and "CHOSE: lake" in m)
    assert "page 1 at sunrise-meadow" in page3 and "page 2 at wildflower-garden" in page3


def test_adventure_switch_off_starts_pip(monkeypatch):
    monkeypatch.setenv("ADVENTURE", "0")
    with TestClient(app) as c:
        sess = start(c)
    assert sess["scene"]["id"] == "s1" and SESSIONS[sess["session_id"]]["story"] == "pip"


def test_pip_story_is_unchanged():
    with TestClient(app) as c:
        sess = c.post("/session/start", json=START).json()
        assert sess["scene"]["id"] == "s1" and sess["scene"]["total"] == main.TOTAL
        assert sess["scene"]["image_url"].endswith("/static/scenes/s1.jpg")
        assert sess["intro"]["text"].startswith("Pip's Gentle Journey Home.")
        turn(c, sess, "lantern")
        entry = c.get(f"/progress/{sess['child_id']}").json()["agent_log"][-1]
    assert entry["story"] == "pip" and entry["background"] is None
    s = SESSIONS[sess["session_id"]]
    assert "scenes" not in s and main.scene_of(s, "s2") is SCENES["s2"]
    assert all(not k.startswith("a") or k == "a" for k in SCENES)  # no adventure page leaked into SCENES


# ---------- the Claude call ----------

REAL_CALL_MODEL = adventure.call_model  # captured at import, before conftest replaces it


def test_page_call_uses_auto_tool_choice_and_low_effort(monkeypatch):
    seen = {}

    class Messages:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(content=[])
    monkeypatch.setattr(adventure, "client", lambda: SimpleNamespace(messages=Messages()))
    asyncio.run(REAL_CALL_MODEL("PAGE: 1 of 4"))
    assert seen["tool_choice"] == {"type": "auto"}
    assert seen["output_config"] == {"effort": "low"}
    assert [t["name"] for t in seen["tools"]] == ["write_page"]
    assert "ONLY by calling the `write_page` tool, exactly once" in adventure.SYSTEM_PROMPT


def test_reply_without_write_page_is_an_invalid_page(monkeypatch):
    async def text_only(message):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Once upon a time...")])
    monkeypatch.setattr(adventure, "call_model", text_only)
    data, why = asyncio.run(adventure.generate_page(1, [], "bunny", None))
    assert why == "invalid page: write_page not called"
    assert data["background_id"] == "sunrise-meadow"


def test_api_error_message_is_logged(monkeypatch, caplog):
    async def bad_request(message):
        raise RuntimeError("Error code: 400 - tool_choice: type \"tool\" is not supported")
    monkeypatch.setattr(adventure, "call_model", bad_request)
    with caplog.at_level("WARNING", logger="adventure"):
        _, why = asyncio.run(adventure.generate_page(2, [], "bunny", {"word": "lake", "label": "Lake"}))
    assert why.startswith("generation error: RuntimeError: Error code: 400")
    assert "tool_choice" in caplog.text
