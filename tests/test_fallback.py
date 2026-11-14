"""Fallback rule tests (no AI). Run:  pytest tests/test_fallback.py -v"""
from fastapi.testclient import TestClient

from agent import fallback as fb
from agent.main import SCENES, STORY, app, validate_story

NARRATION = "Mia steps into a quiet forest. Tall trees whisper hello."
SCENE = {"id": "s1", "narration": NARRATION, "next": "s2"}
QUESTION = {"id": "q", "narration": "A sun and a moon.", "next": "s3", "decision": {
    "type": "single_correct", "prompt": "Which one shines in the day: sun or moon?",
    "options": [{"word": "sun", "label": "Sun", "icon": "sun"}, {"word": "moon", "label": "Moon", "icon": "moon"}],
    "correct_word": "sun", "incorrect_words": ["moon"], "on_correct": "advance",
    "on_incorrect": "retry_with_hint", "max_attempts": 3, "on_max_attempts": "reveal_correct_and_advance",
    "hint": "The sun shines in the daytime. Can you say sun?"}}
BRANCH = {"id": "s2", "narration": "A bridge and a boat.",
          "decision": {"type": "branch_choice", "prompt": "Bridge or boat?"}, "branches": [
    {"word": "bridge", "label": "Cross the bridge", "icon": "bridge", "next": "s3a"},
    {"word": "boat", "label": "Take the boat", "icon": "boat", "next": "s3b"}]}


def fresh(scene=SCENE, level=1):
    state = fb.new_session_state()
    state["level"] = level
    fb.enter_scene(state, scene, scene["narration"], exclude={"mia"})
    return state


def say(state, text, scene=SCENE):
    return fb.turn(state, scene, scene["narration"], text)


# ---------- target words and levels ----------

def test_level1_target_is_one_word_from_narration():
    ch = fresh()["challenge"]
    assert ch["level"] == 1 and len(ch["target_words"]) == 1
    assert ch["target_words"][0] in fb.words(NARRATION)
    assert ch["target_words"][0] != "mia"  # never the child's name


def test_level2_is_short_phrase_level3_is_longer():
    l2 = fresh(level=2)["challenge"]["target_words"]
    l3 = fresh(level=3)["challenge"]["target_words"]
    assert 2 <= len(l2) <= 4
    assert len(l3) > len(l2)
    assert all(w in fb.words(NARRATION) for w in l2 + l3)


def test_skips_already_practised_words():
    s = fb.new_session_state()
    s["practised"] = ["steps"]
    fb.enter_scene(s, SCENE, NARRATION, exclude={"mia"})
    assert s["key_word"] != "steps"


# ---------- assessment ----------

def test_target_word_is_hit_and_praise_names_it():
    s = fresh()
    word = s["challenge"]["target_words"][0]
    d = say(s, f"{word}!")
    assert d["result"] == "hit" and d["action"] == "advance" and d["next_id"] == "s2"
    assert word in d["feedback"]
    assert "wrong" not in d["feedback"].lower()


def test_near_miss_counts_as_hit():
    assert fb.is_hit("fowest", ["forest"])
    assert not fb.is_hit("banana", ["forest"])


def test_phrase_hit_needs_most_words():
    assert fb.is_hit("a quiet forest", ["a", "quiet", "forest"])
    assert fb.is_hit("quiet fowest", ["a", "quiet", "forest"])
    assert not fb.is_hit("forest", ["a", "quiet", "forest"])


# ---------- adaptation ----------

def test_two_hits_in_a_row_level_up():
    s = fresh()
    say(s, " ".join(s["challenge"]["target_words"]))
    assert s["level"] == 1
    fb.enter_scene(s, SCENE, NARRATION)
    say(s, " ".join(s["challenge"]["target_words"]))
    assert s["level"] == 2


def test_level_never_above_3():
    s = fresh(level=3)
    for _ in range(4):
        fb.enter_scene(s, SCENE, NARRATION)
        say(s, " ".join(s["challenge"]["target_words"]))
    assert s["level"] == 3


def test_miss_retries_with_model_of_word():
    s = fresh()
    word = s["challenge"]["target_words"][0]
    d = say(s, "banana")
    assert d["result"] == "miss" and d["retry"] and d["action"] == "retry"
    assert word in d["feedback"] and "wrong" not in d["feedback"].lower()


def test_two_misses_level_down_with_hint():
    s = fresh(level=2)
    say(s, "banana")
    d = say(s, "banana")
    assert s["level"] == 1
    assert d["action"] == "retry_with_hint" and d["retry"]
    assert d["challenge"]["level"] == 1 and len(d["challenge"]["target_words"]) == 1
    assert d["challenge"]["target_words"][0] == s["key_word"]  # same word, easier


def test_level_never_below_1():
    s = fresh(level=1)
    say(s, "banana")
    say(s, "banana")
    assert s["level"] == 1


def test_three_misses_move_on_with_parent_note():
    s = fresh(level=2)
    say(s, "banana")
    say(s, "banana")
    d = say(s, "banana")
    assert d["action"] == "move_on" and not d["retry"] and d["next_id"] == "s2"
    assert d["parent_note"] and s["key_word"] in d["parent_note"]
    assert s["level"] == 1  # easier level first, then moved on


def test_first_silence_is_not_a_miss():
    s = fresh()
    d = say(s, "")
    assert d["result"] == "silence" and d["retry"] and "together" in d["feedback"]
    assert s["tries"] == 0 and s["miss_streak"] == 0
    d = say(s, "")
    assert d["result"] == "miss" and s["tries"] == 1


# ---------- branches ----------

def test_branch_word_chooses_path():
    s = fresh(BRANCH)
    d = say(s, "the boat please", BRANCH)
    assert d["result"] == "hit" and d["next_id"] == "s3b"
    s = fresh(BRANCH)
    assert say(s, "bwidge", BRANCH)["next_id"] == "s3a"


def test_branch_neither_first_time_repeats_options():
    s = fresh(BRANCH)
    d = say(s, "dinosaur", BRANCH)
    assert d["retry"] and "Bridge or boat?" in d["feedback"]  # the authored prompt
    assert d["log_result"] == "no_choice"  # never counted as a miss


def test_branch_neither_twice_proposes_then_yes_accepts():
    s = fresh(BRANCH)
    say(s, "dinosaur", BRANCH)
    d = say(s, "dinosaur", BRANCH)
    assert d["retry"] and d["feedback"] == "Shall we cross the bridge?"
    d = say(s, "yes", BRANCH)
    assert not d["retry"] and d["next_id"] == "s3a"


def test_branch_proposal_no_takes_other_and_anything_else_takes_proposed():
    s = fresh(BRANCH)
    say(s, "x", BRANCH), say(s, "x", BRANCH)
    assert say(s, "no", BRANCH)["next_id"] == "s3b"
    s = fresh(BRANCH)
    say(s, "x", BRANCH), say(s, "x", BRANCH)
    assert say(s, "pizza", BRANCH)["next_id"] == "s3a"


def test_branch_does_not_change_level_or_streaks():
    s = fresh(BRANCH, level=2)
    s["miss_streak"] = 1
    for _ in range(3):
        say(s, "x", BRANCH)
    assert s["level"] == 2 and s["miss_streak"] == 1


def test_branch_scene_without_decision_is_still_a_branch_choice():
    plain = {k: v for k, v in BRANCH.items() if k != "decision"}
    s = fresh(plain)
    assert s["challenge"]["prompt"] == "Shall we go to the bridge or the boat?"
    assert say(s, "boat", plain)["next_id"] == "s3b"


# ---------- single_correct questions ----------

def test_question_correct_word_is_hit_and_advances():
    s = fresh(QUESTION)
    assert s["challenge"]["prompt"] == QUESTION["decision"]["prompt"]
    d = say(s, "the sun!", QUESTION)
    assert d["result"] == "hit" and d["next_id"] == "s3" and "sun" in d["feedback"]


def test_question_other_option_is_a_miss():
    assert say(fresh(QUESTION), "moon", QUESTION)["result"] == "miss"


def test_question_wrong_answer_gives_authored_hint_and_retries():
    s = fresh(QUESTION)
    d = say(s, "moon", QUESTION)
    assert d["result"] == "miss" and d["retry"] and d["action"] == "retry_with_hint"
    assert QUESTION["decision"]["hint"] in d["feedback"]
    assert "wrong" not in d["feedback"].lower()


def test_question_reveals_and_advances_at_max_attempts_with_parent_note():
    s = fresh(QUESTION)
    say(s, "moon", QUESTION)
    say(s, "moon", QUESTION)
    d = say(s, "moon", QUESTION)
    assert d["action"] == "move_on" and not d["retry"] and d["next_id"] == "s3"
    assert "sun" in d["feedback"] and d["parent_note"] and "sun" in d["parent_note"]


def test_question_respects_authored_max_attempts():
    scene = {**QUESTION, "decision": {**QUESTION["decision"], "max_attempts": 1}}
    s = fresh(scene)
    assert not say(s, "moon", scene)["retry"]


def test_question_first_silence_is_not_a_miss():
    s = fresh(QUESTION)
    d = say(s, "", QUESTION)
    assert d["result"] == "silence" and d["retry"] and s["tries"] == 0


def test_question_does_not_change_level():
    s = fresh(QUESTION, level=2)
    for _ in range(3):
        say(s, "moon", QUESTION)
    assert s["level"] == 2


def test_choices_per_decision_type():
    assert [c["word"] for c in fb.scene_choices(QUESTION)] == ["sun", "moon"]
    assert [c["word"] for c in fb.scene_choices(BRANCH)] == ["bridge", "boat"]
    assert fb.scene_choices(SCENE) is None


# ---------- story validation ----------

def test_story_file_is_valid():
    validate_story(STORY)


def test_story_validation_rejects_unknown_scene_and_action():
    import pytest
    bad = {"scenes": [{"id": "s1", "narration": "x", "next": "nowhere"}]}
    with pytest.raises(AssertionError):
        validate_story(bad)
    bad = {"scenes": [{**QUESTION, "id": "s1", "next": None,
                       "decision": {**QUESTION["decision"], "on_incorrect": "launch_rocket"}}]}
    with pytest.raises(AssertionError):
        validate_story(bad)


# ---------- full story over HTTP with typed transcripts ----------

client = TestClient(app)


def start(pronouns="she", pet="fox"):
    return client.post("/session/start", json={"child_name": "Mia", "age": 5, "pronouns": pronouns,
                                               "avatar": {"pet": pet}}).json()


def right_answer(scene):
    dec = SCENES[scene["id"]].get("decision") or {}
    if dec.get("correct_word"):
        return dec["correct_word"]
    if scene["choices"]:
        return scene["choices"][-1]["word"]
    return " ".join(scene["challenge"]["target_words"])


def test_start_scene_and_placeholders_filled():
    scene = start()["scene"]
    assert scene["id"] == STORY["start_scene"]
    assert "{" not in scene["narration"] and "Mia" in scene["narration"] and "fox" in scene["narration"]
    assert scene["narration_audio_url"] is None
    assert scene["avatar_position"] == SCENES[scene["id"]]["avatar_position"]


def test_pronoun_placeholders():
    from agent.main import narration_for
    scene = {"narration": "{CHILD_NAME} waved. {THEY} smiled at {THEIR} {PET}."}
    sess = {"child": {"child_name": "Sam", "pronouns": "he", "avatar": {"pet": "cat"}}}
    assert narration_for(sess, scene) == "Sam waved. He smiled at his cat."
    sess["child"]["pronouns"] = "they"
    assert narration_for(sess, scene) == "Sam waved. They smiled at their cat."


def test_full_story_runs_on_typed_transcripts():
    sess = start()
    scene, seen = sess["scene"], []
    for _ in range(40):
        seen.append(scene["id"])
        transcript = right_answer(scene)
        r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": transcript}).json()
        assert r["result"] == "hit" and not r["retry"]
        assert r["feedback_audio_url"] is None
        if r["story_complete"]:
            break
        scene = r["scene"]
    else:
        raise AssertionError("story never completed")
    assert SCENES[seen[-1]].get("next") is None
    assert len(seen) >= 3
    assert seen[0] == STORY["start_scene"] and len(seen) == 5
    progress = client.get(f"/progress/{sess['child_id']}").json()
    assert progress["target_words_hit"] >= len(seen)
    assert [e["scene"] for e in progress["agent_log"]][-len(seen):] == seen
    assert all(e["action"] == "advance" and e["reason"] for e in progress["agent_log"][-len(seen):])


def test_question_scene_over_http_shows_options_as_choices():
    sess = start()
    r = client.post("/turn", json={"session_id": sess["session_id"],
                                   "transcript": right_answer(sess["scene"])}).json()
    assert r["scene"]["id"] == "s2"
    assert [c["word"] for c in r["scene"]["choices"]] == ["sun", "moon"]
    r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": "moon"}).json()
    assert r["retry"] and r["scene"]["id"] == "s2"


def test_full_story_completes_even_if_child_never_answers_right():
    sess = start()
    for _ in range(60):
        r = client.post("/turn", json={"session_id": sess["session_id"], "transcript": "pizza"}).json()
        if r["story_complete"]:
            break
    else:
        raise AssertionError("story stalled")
    notes = client.get(f"/progress/{sess['child_id']}").json()["parent_notes"]
    assert notes
