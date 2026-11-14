"""Mock backend: FastAPI app with the contract from CLAUDE.md. No AI yet.

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

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
(STATIC / "audio").mkdir(parents=True, exist_ok=True)
(STATIC / "scenes").mkdir(parents=True, exist_ok=True)

MAX_TRIES = 3

PLACEHOLDER_STORY = {
    "title": "Placeholder story",
    "scenes": [
        {
            "id": "s1",
            "narration": "The hero walks into a quiet forest. A little path splits in two. "
                         "One way leads to a wooden bridge, the other to a small boat.",
            "image_prompt": "quiet forest path splitting in two, background only",
            "branches": [
                {"word": "bridge", "label": "Cross the bridge", "icon": "bridge", "next": "s2a"},
                {"word": "boat", "label": "Take the boat", "icon": "boat", "next": "s2b"},
            ],
        },
        {
            "id": "s2a",
            "narration": "Over the bridge, the hero finds a cosy cottage with a glowing lantern. "
                         "It is time to get ready for sleep.",
            "image_prompt": "cosy cottage with a lantern at dusk, background only",
            "next": None,
        },
        {
            "id": "s2b",
            "narration": "The boat drifts to a sandy shore under the moon. "
                         "The hero yawns and gets ready for sleep.",
            "image_prompt": "moonlit sandy shore with a small boat, background only",
            "next": None,
        },
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


# ---------- mock challenge / assessment (replaced by the agent later) ----------

def words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def mock_challenge(scene: dict, level: int) -> dict:
    if "branches" in scene:
        a, b = (br["word"] for br in scene["branches"])
        return {"level": 1, "prompt": f"Shall we go to the {a} or the {b}?", "target_words": [a, b]}
    ws = [w for w in words(scene["narration"]) if len(w) >= 5 and w != "hero"]
    if level == 1:
        target = ws[0] if ws else words(scene["narration"])[0]
        return {"level": 1, "prompt": f"Can you say '{target}'?", "target_words": [target]}
    first_sentence = scene["narration"].split(".")[0].split()
    phrase = " ".join(first_sentence[-3:] if level == 2 else first_sentence).strip(",")
    return {"level": level, "prompt": f"Can you say '{phrase}'?", "target_words": words(phrase)}


def is_hit(transcript: str, targets: list[str]) -> bool:
    said = set(words(transcript))
    return sum(t in said for t in targets) * 2 > len(targets) or (len(targets) <= 2 and bool(said & set(targets)))


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
        "narration": scene["narration"].replace("The hero", sess["child"]["child_name"])
                                       .replace("the hero", sess["child"]["child_name"]),
        "narration_audio_url": f"{base}/static/audio/{scene['id']}.mp3",
        "image_url": f"{base}/static/scenes/{scene['id']}.png",
        "avatar_position": {"x": 0.3, "y": 0.62, "scale": 0.35},
        "challenge": sess["challenge"],
        "choices": choices,
    }


def enter_scene(sess: dict, scene_id: str) -> None:
    sess["scene_id"] = scene_id
    sess["tries"] = 0
    sess["silences"] = 0
    sess["challenge"] = mock_challenge(SCENES[scene_id], sess["level"])


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
        "scene_id": None, "level": 1, "hit_streak": 0, "miss_streak": 0,
        "tries": 0, "silences": 0, "challenge": None, "log": [],
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
        # Mock: audio is ignored (never stored) and treated as saying the first target word.
        sess = SESSIONS.get(session_id)
        transcript = sess["challenge"]["target_words"][0] if sess else ""

    sess = SESSIONS.get(session_id)
    if not sess:
        raise HTTPException(404, "Unknown session_id")

    scene = SCENES[sess["scene_id"]]
    challenge = sess["challenge"]
    targets = challenge["target_words"]
    branch = "branches" in scene
    said = set(words(transcript))
    next_id, retry = None, False

    if not said:
        result = "silence"
        sess["silences"] += 1
        feedback = "Shall we try together?"
        retry = True
        if sess["silences"] > 1 and not branch:
            sess["tries"] += 1
    elif branch:
        chosen = next((br for br in scene["branches"] if br["word"] in said), None)
        result = "hit" if chosen else "miss"
        sess["tries"] += 1
        if chosen:
            feedback, next_id = f"You said {chosen['word']}!", chosen["next"]
        elif sess["tries"] >= MAX_TRIES:
            chosen = scene["branches"][0]
            feedback, next_id = f"Let's take the {chosen['word']}!", chosen["next"]
        else:
            feedback, retry = f"Shall we go to the {targets[0]} or the {targets[1]}?", True
    else:
        sess["tries"] += 1
        hit = is_hit(transcript, targets)
        result = "hit" if hit else "miss"
        # Fallback rule: 2 hits in a row = level up, 2 misses = level down.
        sess["hit_streak"] = sess["hit_streak"] + 1 if hit else 0
        sess["miss_streak"] = 0 if hit else sess["miss_streak"] + 1
        if sess["hit_streak"] >= 2:
            sess["level"], sess["hit_streak"] = min(3, sess["level"] + 1), 0
        if sess["miss_streak"] >= 2:
            sess["level"], sess["miss_streak"] = max(1, sess["level"] - 1), 0
        if hit:
            feedback, next_id = f"You said {' '.join(targets)}!", scene.get("next")
        elif sess["tries"] >= MAX_TRIES:
            feedback, next_id = "Great trying! Let's see what happens next.", scene.get("next")
        else:
            feedback, retry = f"Listen: {' '.join(targets)}. Your turn!", True

    sess["log"].append({
        # Branch flow never counts a miss.
        "result": "no_choice" if branch and result == "miss" else result,
        "date": date.today().isoformat(), "scene_id": scene["id"], "transcript": transcript,
        "targets": [chosen["word"]] if branch and result == "hit" else targets, "level": challenge["level"], "tries": sess["tries"],
        "parent_note": (f"Struggled with '{' '.join(targets)}' - practise together"
                        if result == "miss" and not retry and not branch else None),
    })

    story_complete = not retry and next_id is None
    if retry:
        sess["challenge"] = mock_challenge(scene, sess["level"]) if not branch else challenge
    elif next_id:
        enter_scene(sess, next_id)

    return {
        "transcript": transcript, "result": result, "feedback": feedback,
        "feedback_audio_url": f"{base_url(request)}/static/audio/feedback.mp3",
        "retry": retry,
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
        "avg_answer_length": round(sum(len(words(e["transcript"])) for e in attempts) / len(attempts), 1)
                             if attempts else 0,
        "nightly": list(nightly.values()),
        "parent_notes": [e["parent_note"] for e in logs if e["parent_note"]],
    }
