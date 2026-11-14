"""FastAPI app with the contract from CLAUDE.md. Turns use the fallback rule (no AI yet).

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

# Same shape as the real story (CLAUDE.md): s1 -> s2 (branch) -> s3a|s3b -> s4 (branch) -> s5a|s5b.
# Used only until Kiko commits data/story.json.
PLACEHOLDER_STORY = {
    "title": "Placeholder story",
    "scenes": [
        {"id": "s1", "next": "s2",
         "narration": "The hero steps into a quiet forest. Tall trees whisper hello. "
                      "A friendly squirrel waves from a branch.",
         "image_prompt": "quiet friendly forest at dusk, background only"},
        {"id": "s2",
         "narration": "The path reaches a sparkling river. There is a wooden bridge "
                      "and a little red boat.",
         "image_prompt": "sparkling river with a wooden bridge and a small boat, background only",
         "branches": [
             {"word": "bridge", "label": "Cross the bridge", "icon": "bridge", "next": "s3a"},
             {"word": "boat", "label": "Take the boat", "icon": "boat", "next": "s3b"}]},
        {"id": "s3a", "next": "s4",
         "narration": "The hero crosses the bridge. Below, happy fish splash and play.",
         "image_prompt": "view from a wooden bridge over a river with fish, background only"},
        {"id": "s3b", "next": "s4",
         "narration": "The hero rows the boat. Gentle ducks paddle alongside.",
         "image_prompt": "small red boat on a calm river with ducks, background only"},
        {"id": "s4",
         "narration": "On the other side is a garden. A glowing lantern sits by the gate "
                      "and a sleepy owl blinks.",
         "image_prompt": "moonlit garden gate with a lantern and an owl, background only",
         "branches": [
             {"word": "lantern", "label": "Lift the lantern", "icon": "lantern", "next": "s5a"},
             {"word": "owl", "label": "Ask the owl", "icon": "owl", "next": "s5b"}]},
        {"id": "s5a", "next": None,
         "narration": "The lantern lights the way to a cosy cottage. The hero yawns, "
                      "snuggles into bed and gets ready for sleep.",
         "image_prompt": "cosy cottage bedroom lit by a lantern, background only"},
        {"id": "s5b", "next": None,
         "narration": "The owl hoots softly and shows the way home. The hero yawns, "
                      "snuggles into bed and gets ready for sleep.",
         "image_prompt": "cosy bedroom with a window and an owl outside, background only"},
    ],
}


def load_story() -> dict:
    path = ROOT / "data" / "story.json"
    if path.exists():
        return json.loads(path.read_text())
    return PLACEHOLDER_STORY


STORY = load_story()
SCENES = {s["id"]: s for s in STORY["scenes"]}


def path_depth(scene_id: str) -> int:
    """1-based position of a scene on the path from the first scene."""
    depth, sid = 1, STORY["scenes"][0]["id"]
    frontier = [sid]
    seen = set()
    while frontier:
        if scene_id in frontier:
            return depth
        nxt = []
        for sid in frontier:
            if sid in seen:
                continue
            seen.add(sid)
            s = SCENES[sid]
            nxt += [b["next"] for b in s.get("branches", [])] or ([s["next"]] if s.get("next") else [])
        frontier, depth = [n for n in nxt if n], depth + 1
    return 1


TOTAL = max(path_depth(sid) for sid in SCENES)

app = FastAPI(title="Story-time mock backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SESSIONS: dict[str, dict] = {}   # session_id -> session state
CHILDREN: dict[str, dict] = {}   # child_id -> profile


# ---------- challenge / assessment: fallback rule (the agent plugs in here later) ----------

def narration_for(sess: dict, scene: dict) -> str:
    name = sess["child"]["child_name"]
    return scene["narration"].replace("The hero", name).replace("the hero", name)


def name_words(sess: dict) -> set[str]:
    return set(fallback.words(sess["child"]["child_name"]))


# ---------- response builders ----------

def base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def scene_payload(sess: dict, request: Request) -> dict:
    scene = SCENES[sess["scene_id"]]
    base = base_url(request)
    choices = None
    if "branches" in scene:
        choices = [{k: br[k] for k in ("word", "label", "icon")} for br in scene["branches"]]
    return {
        "id": scene["id"],
        "index": path_depth(scene["id"]),
        "total": TOTAL,
        "narration": narration_for(sess, scene),
        "narration_audio_url": f"{base}/static/audio/{scene['id']}.mp3",
        "image_url": f"{base}/static/scenes/{scene['id']}.png",
        "avatar_position": {"x": 0.3, "y": 0.62, "scale": 0.35},
        "challenge": sess["challenge"],
        "choices": choices,
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
    enter_scene(sess, STORY["scenes"][0]["id"])
    SESSIONS[session_id] = sess
    return {"session_id": session_id, "child_id": child_id, "avatar_url": None,
            "scene": scene_payload(sess, request)}


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
        transcript = " ".join(sess["challenge"]["target_words"]) if sess else ""

    sess = SESSIONS.get(session_id)
    if not sess:
        raise HTTPException(404, "Unknown session_id")

    scene = SCENES[sess["scene_id"]]
    challenge = sess["challenge"]
    d = fallback.turn(sess, scene, narration_for(sess, scene), transcript)

    # Code-enforced limits (also guards the agent's choices later).
    sess["level"] = max(fallback.MIN_LEVEL, min(fallback.MAX_LEVEL, sess["level"]))
    allowed = {br["next"] for br in scene.get("branches", [])} or {scene.get("next")}
    if not d["retry"] and d["next_id"] not in allowed:
        d["next_id"] = next(iter(allowed))

    sess["log"].append({
        "result": d["log_result"], "action": d["action"],
        "date": date.today().isoformat(), "scene_id": scene["id"], "transcript": transcript,
        "targets": [d["chosen"]] if d.get("chosen") else challenge["target_words"],
        "level": challenge["level"], "new_level": sess["level"], "tries": sess["tries"],
        "parent_note": d["parent_note"], "source": "fallback",
    })

    story_complete = not d["retry"] and d["next_id"] is None
    if d["retry"]:
        sess["challenge"] = d["challenge"]
    elif d["next_id"]:
        enter_scene(sess, d["next_id"])

    return {
        "transcript": transcript, "result": d["result"], "feedback": d["feedback"],
        "feedback_audio_url": f"{base_url(request)}/static/audio/feedback.mp3",
        "retry": d["retry"],
        "scene": None if story_complete else scene_payload(sess, request),
        "story_complete": story_complete,
    }


MOCK_PROGRESS = {
    "child_name": "Mia", "sessions": 3, "target_words_hit": 14, "attempts": 20,
    "new_words": ["forest", "brave"], "avg_answer_length": 2.4,
    "nightly": [{"date": "2026-11-14", "hits": 5, "attempts": 7}],
    "parent_notes": ["Struggled with 'lantern' - practise together"],
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
    }
