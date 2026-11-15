"""Every choice card has image_url: the background of the page or scene it leads to.
The page writer is mocked; nothing goes over the network.  Run:  pytest tests/test_choice_images.py -v"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agent import adventure
from agent.main import SESSIONS, app
from test_adventure import FakeWriter, answer, page_input, start, turn, wait_for

BASE = "http://testserver"


def bg_url(bg_id):
    return f"{BASE}{adventure.BACKGROUNDS[bg_id]['url']}"


# ---------- Pip ----------

def test_pip_branches_show_their_target_scene_and_quiz_options_are_null():
    with TestClient(app) as c:
        sess = c.post("/session/start", json={"child_name": "Pia", "pronouns": "she"}).json()
        r = turn(c, sess, "lantern")
        assert [ch["image_url"] for ch in r["scene"]["choices"]] == [None, None]  # sun / moon
        r = turn(c, sess, "sun")
    assert r["scene"]["id"] == "s3"
    assert {ch["word"]: ch["image_url"] for ch in r["scene"]["choices"]} == {
        "bridge": f"{BASE}/static/scenes/s4a.jpg", "boat": f"{BASE}/static/scenes/s4b.jpg"}


# ---------- adventure ----------

def test_opening_choices_have_fixed_backgrounds():
    with TestClient(app) as c:
        sess = start(c)
        r = answer(c, sess)
    assert {ch["word"]: ch["image_url"] for ch in r["scene"]["choices"]} == {
        "garden": bg_url("wildflower-garden"), "forest": bg_url("golden-forest-trail")}


def test_chosen_page_uses_the_card_background(monkeypatch):
    monkeypatch.setattr(adventure, "call_model", FakeWriter())
    with TestClient(app) as c:
        sess = start(c)
        s = SESSIONS[sess["session_id"]]
        assert wait_for(lambda: {"a2-garden", "a2-forest"} <= set(s["scenes"]))
        card = {ch["word"]: ch["image_url"] for ch in answer(c, sess)["scene"]["choices"]}
        r = turn(c, sess, "forest")
    assert r["scene"]["image_url"] == card["forest"] == bg_url("golden-forest-trail")
    assert not s["scenes"]["a2-forest"]["fallback"]


def test_page_message_names_the_promised_background():
    msg = adventure.page_message(2, [], "bunny", {"word": "forest", "label": "Forest",
                                                  "background_id": "golden-forest-trail"})
    assert "THIS PAGE MUST USE background_id: golden-forest-trail" in msg


@pytest.mark.parametrize("page,choice_bg,why", [
    (1, "space-station", "unknown choice background"),
    (1, "cozy-cottage", "ending background"),        # page 2 is not the ending
    (3, "riverside", "ending background"),           # page 3's choices lead to the goodnight page
    (2, None, "unknown choice background"),
])
def test_choice_background_is_validated(page, choice_bg, why):
    data = page_input(page)
    data["choices"][0]["background_id"] = choice_bg
    with pytest.raises(ValueError, match=why):
        adventure.validate_page(data, page)


def test_page_with_a_different_background_falls_back_to_the_promised_one(monkeypatch):
    monkeypatch.setattr(adventure, "call_model", FakeWriter(override={2: {"background_id": "riverside"}}))
    choice = {"word": "forest", "label": "Forest", "background_id": "golden-forest-trail"}
    data, why = asyncio.run(adventure.generate_page(2, [], "bunny", choice))
    assert "leads to golden-forest-trail" in why
    assert data["background_id"] == "golden-forest-trail" and data["narration"].startswith("The path led on")


def test_fallback_ending_uses_the_promised_ending_background():
    data = adventure.fallback_page(4, {"word": "lake", "background_id": "cozy-cottage"})
    assert data["background_id"] == "cozy-cottage"
    for page, choice in [(1, None), (2, {"word": "lake"}), (3, {"word": "zzz"})]:
        for ch in adventure.fallback_page(page, choice)["choices"]:
            assert adventure.check_background(ch["background_id"], page + 1, "choice background")


def test_contract_choices_have_image_url():
    contract = json.loads(open("contract/turn_response.json").read())
    assert all("image_url" in ch for ch in contract["scene"]["choices"])
