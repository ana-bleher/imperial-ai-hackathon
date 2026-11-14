"""FastAPI app with the contract from CLAUDE.md. Turns use the fallback rule (no AI yet).
The story (scenes, order, branches, decisions, endings) comes from data/story.json.

Run locally:  uvicorn agent.main:app --reload
"""
import json
import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent import fallback

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
(STATIC / "audio").mkdir(parents=True, exist_ok=True)
(STATIC / "scenes").mkdir(parents=True, exist_ok=True)

STORY_PATH = ROOT / "data" / "story.json"


def validate_story(story: dict) -> None:
    """Fail at startup, not mid-demo: every reference exists, every decision is one we implement,
    every path reaches an ending."""
    scenes = {s["id"]: s for s in story["scenes"]}
    assert len(scenes) == len(story["scenes"]), "duplicate scene ids"
    assert story.get("start_scene", story["scenes"][0]["id"]) in scenes, "start_scene not found"
    for s in story["scenes"]:
        kind = fallback.decision_type(s)
        dec = s.get("decision") or {}
        dests = [b["next"] for b in s.get("branches", [])] or [s.get("next")]
        for d in dests:
            assert d is None or d in scenes, f"{s['id']}: unknown scene '{d}'"
        assert kind in (None, fallback.SINGLE_CORRECT, fallback.BRANCH_CHOICE), \
            f"{s['id']}: unsupported decision type '{kind}'"
        if kind == fallback.BRANCH_CHOICE:
            assert len(s.get("branches", [])) >= 2, f"{s['id']}: branch_choice needs 2+ branches"
        if kind == fallback.SINGLE_CORRECT:
            assert dec["correct_word"] in [o["word"] for o in dec["options"]], \
                f"{s['id']}: correct_word is not an option"
        for key, allowed in fallback.SUPPORTED_ACTIONS.items():
            assert dec.get(key) in (None, *allowed), f"{s['id']}: unsupported {key} '{dec.get(key)}'"

    def reaches_end(sid, seen=()):
        if sid is None:
            return True
        if sid in seen:
            return False
        sc = scenes[sid]
        dests = [b["next"] for b in sc.get("branches", [])] or [sc.get("next")]
        return all(reaches_end(d, (*seen, sid)) for d in dests)
    assert reaches_end(story.get("start_scene", story["scenes"][0]["id"])), "a path never ends"


def load_story() -> dict:
    story = json.loads(STORY_PATH.read_text())
    validate_story(story)
    return story


STORY = load_story()
SCENES = {s["id"]: s for s in STORY["scenes"]}
START = STORY.get("start_scene") or STORY["scenes"][0]["id"]
DEFAULT_AVATAR_POSITION = {"x": 0.3, "y": 0.62, "scale": 0.35}


def next_ids(scene: dict) -> list[str | None]:
    """Declared destinations: the branches, or `next` (None = an ending)."""
    return [b["next"] for b in scene.get("branches", [])] or [scene.get("next")]


def path_depth(scene_id: str) -> int:
    """1-based position of a scene on the path from the start scene."""
    depth, frontier, seen = 1, [START], set()
    while frontier:
        if scene_id in frontier:
            return depth
        nxt = []
        for sid in frontier:
            if sid not in seen:
                seen.add(sid)
                nxt += [n for n in next_ids(SCENES[sid]) if n]
        frontier, depth = nxt, depth + 1
    return 1


TOTAL = max(path_depth(sid) for sid in SCENES)

app = FastAPI(title="Story-time mock backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SESSIONS: dict[str, dict] = {}   # session_id -> session state
CHILDREN: dict[str, dict] = {}   # child_id -> profile


# ---------- challenge / assessment: fallback rule (the agent plugs in here later) ----------

PRONOUNS = {  # {THEY} / {THEM} / {THEIR}
    "she": ("she", "her", "her"),
    "he": ("he", "him", "his"),
    "they": ("they", "them", "their"),
}


def narration_for(sess: dict, scene: dict) -> str:
    """Fill the story's placeholders: {CHILD_NAME}, {PET}, {THEY}, {THEM}, {THEIR}."""
    child = sess["child"]
    they, them, their = PRONOUNS.get(str(child.get("pronouns", "")).lower(), PRONOUNS["they"])
    pet = (child.get("avatar") or {}).get("pet") or "puppy"
    values = {"CHILD_NAME": child["child_name"], "PET": pet, "THEY": they, "THEM": them, "THEIR": their}

    def fill(m: re.Match) -> str:
        value = values.get(m.group(1), m.group(0))
        before = scene["narration"][:m.start()].rstrip()
        if not before or before[-1] in ".!?'\"":  # start of a sentence
            value = value[:1].upper() + value[1:]
        return value

    return re.sub(r"\{([A-Z_]+)\}", fill, scene["narration"])


def name_words(sess: dict) -> set[str]:
    return set(fallback.words(sess["child"]["child_name"]))


# ---------- response builders ----------

def base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def scene_payload(sess: dict, request: Request) -> dict:
    scene = SCENES[sess["scene_id"]]
    base = base_url(request)
    return {
        "id": scene["id"],
        "index": path_depth(scene["id"]),
        "total": TOTAL,
        "narration": narration_for(sess, scene),
        "narration_audio_url": None,  # until real narration audio exists
        "image_url": f"{base}/static/scenes/{scene['id']}.png",
        "avatar_position": scene.get("avatar_position") or DEFAULT_AVATAR_POSITION,
        "challenge": sess["challenge"],
        "choices": fallback.scene_choices(scene),
    }


def enter_scene(sess: dict, scene_id: str) -> None:
    scene = SCENES[scene_id]
    fallback.enter_scene(sess, scene, narration_for(sess, scene), exclude=name_words(sess))


# ---------- endpoints ----------

@app.post("/session/start")
async def session_start(request: Request):
    body = await request.json()
    name = body.get("child_name", "Friend")
    child_id = f"{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'child'}-1"
    child = {
        "child_name": name,
        "age": body.get("age"),
        "pronouns": body.get("pronouns", "they"),
        "avatar": body.get("avatar", {}),
    }
    CHILDREN.setdefault(child_id, {**child, "sessions": 0})
    CHILDREN[child_id]["sessions"] += 1

    session_id = uuid.uuid4().hex[:12]
    sess = {
        "session_id": session_id, "child_id": child_id, "child": child,
        "log": [], **fallback.new_session_state(),
    }
    enter_scene(sess, START)
    SESSIONS[session_id] = sess
    return {"session_id": session_id, "child_id": child_id, "avatar_url": None,
            "scene": scene_payload(sess, request)}


def mock_answer(sess: dict) -> str:
    """Until voice is wired in: a right answer for the current scene."""
    scene = SCENES[sess["scene_id"]]
    targets = sess["challenge"]["target_words"]
    kind = fallback.decision_type(scene)
    if kind == fallback.SINGLE_CORRECT:
        return scene["decision"]["correct_word"]
    if kind == fallback.BRANCH_CHOICE:
        return targets[0]
    return " ".join(targets)


@app.post("/turn")
async def turn(request: Request):
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        session_id, transcript = body.get("session_id"), body.get("transcript", "")
    else:
        form = await request.form()
        session_id = form.get("session_id")
        # Mock: audio is ignored (never stored) and treated as saying the target words.
        sess = SESSIONS.get(session_id)
        transcript = mock_answer(sess) if sess else ""

    sess = SESSIONS.get(session_id)
    if not sess:
        raise HTTPException(404, "Unknown session_id")

    scene = SCENES[sess["scene_id"]]
    challenge = sess["challenge"]
    d = fallback.turn(sess, scene, narration_for(sess, scene), transcript)

    # Code-enforced limits (also guards the agent's choices later).
    sess["level"] = max(fallback.MIN_LEVEL, min(fallback.MAX_LEVEL, sess["level"]))
    allowed = next_ids(scene)
    if not d["retry"] and d["next_id"] not in allowed:
        d["next_id"] = allowed[0]

    sess["log"].append({
        "result": d["log_result"], "action": d["action"],
        "date": date.today().isoformat(), "scene_id": scene["id"], "transcript": transcript,
        "targets": [d["chosen"]] if d.get("chosen") else d["targets"] or challenge["target_words"],
        "level": challenge["level"], "new_level": sess["level"], "tries": sess["tries"],
        "parent_note": d["parent_note"], "reason": d["reason"], "source": "fallback",
    })

    story_complete = not d["retry"] and d["next_id"] is None
    if d["retry"]:
        sess["challenge"] = d["challenge"]
    elif d["next_id"]:
        enter_scene(sess, d["next_id"])

    return {
        "transcript": transcript, "result": d["result"], "feedback": d["feedback"],
        "feedback_audio_url": None,  # until real feedback audio exists
        "retry": d["retry"],
        "scene": None if story_complete else scene_payload(sess, request),
        "story_complete": story_complete,
    }


MOCK_PROGRESS = {
    "child_name": "Mia", "sessions": 3, "target_words_hit": 14, "attempts": 20,
    "new_words": ["forest", "brave"], "avg_answer_length": 2.4,
    "nightly": [{"date": "2026-11-14", "hits": 5, "attempts": 7}],
    "parent_notes": ["Struggled with 'lantern' - practise together"],
    "agent_log": [{"scene": "s2", "action": "retry_with_hint",
                   "reason": "Answer was not 'sun' (try 1 of 3); gave the authored hint"}],
}


@app.get("/progress/{child_id}")
def progress(child_id: str):
    child = CHILDREN.get(child_id)
    if not child:
        return MOCK_PROGRESS
    logs = [e for s in SESSIONS.values() if s["child_id"] == child_id for e in s["log"]]
    attempts = [e for e in logs if e["result"] in ("hit", "miss")]
    hits = [e for e in attempts if e["result"] == "hit"]
    nightly: dict[str, dict] = {}
    for e in attempts:
        n = nightly.setdefault(e["date"], {"date": e["date"], "hits": 0, "attempts": 0})
        n["attempts"] += 1
        n["hits"] += e["result"] == "hit"
    return {
        "child_name": child["child_name"],
        "sessions": child["sessions"],
        "target_words_hit": len(hits),
        "attempts": len(attempts),
        "new_words": sorted({w for e in hits for w in e["targets"]}),
        "avg_answer_length": round(sum(len(fallback.words(e["transcript"])) for e in attempts) / len(attempts), 1)
                             if attempts else 0,
        "nightly": list(nightly.values()),
        "parent_notes": [e["parent_note"] for e in logs if e["parent_note"]],
        "agent_log": [{"scene": e["scene_id"], "action": e["action"], "reason": e["reason"]} for e in logs],
    }
