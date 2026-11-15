"""FastAPI app with the contract from CLAUDE.md. Turns go through the tutor agent (agent/tutor.py),
which falls back to the fallback rule (agent/fallback.py) when slow or invalid.
The story (scenes, order, branches, decisions, endings) comes from data/story.json.

Run locally:  uvicorn agent.main:app --reload
"""
import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv

load_dotenv()  # ANTHROPIC_API_KEY for the tutor agent (never committed)

from agent import adventure, fallback, questions, tutor  # noqa: E402
from tools import paint_avatar  # noqa: E402
from tools import voice as voice_tools  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("turn")

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
(STATIC / "audio").mkdir(parents=True, exist_ok=True)
(STATIC / "scenes").mkdir(parents=True, exist_ok=True)
(STATIC / "avatars").mkdir(parents=True, exist_ok=True)

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


def scene_of(sess: dict, scene_id: str) -> dict:
    """A scene of this session's story: its own adventure pages, or the Pip story's SCENES."""
    if sess.get("story") == "adventure":
        return sess["scenes"][scene_id]
    return SCENES[scene_id]


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
# Every word in the story file: the agent may say these even if the child said them too.
STORY_VOCAB = set(fallback.words(json.dumps(STORY)))

VOICE_TIMEOUT = 5  # seconds; a slower voice call returns no audio instead of failing the request
NARRATION_TIMEOUT = 15  # seconds; narration and challenge audio are longer (first scene on /session/start)
NARRATION: dict[str, asyncio.Task] = {}  # scene id + narration text -> task giving /static/... path
CHALLENGE: dict[str, asyncio.Task] = {}  # challenge prompt text -> task giving /static/... path
BACKGROUND: set[asyncio.Task] = set()   # keeps background tasks alive until they finish


async def voice(fn, *args, timeout: float | None = None):
    """Run a blocking voice call with a time limit (default VOICE_TIMEOUT, read at call time).
    Returns None on any failure or timeout."""
    timeout = VOICE_TIMEOUT if timeout is None else timeout
    started = time.perf_counter()
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)
    except Exception as e:
        log.warning("voice %s failed after %.1fs: %r", fn.__name__, time.perf_counter() - started, e)
        return None


def in_background(coro) -> None:
    task = asyncio.create_task(coro)
    BACKGROUND.add(task)
    task.add_done_callback(BACKGROUND.discard)


@asynccontextmanager
async def lifespan(app):
    in_background(voice(voice_tools.speak, "Hello!"))  # warm up the TTS connection
    yield


app = FastAPI(title="Story-time mock backend", lifespan=lifespan)
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


# Words before {PET} that already say whose pet it is: no extra "her" / "the".
DETERMINERS = {"{their}", "his", "her", "their", "the", "a", "an", "my", "your", "our", "this", "that"}


def narration_for(sess: dict, scene: dict) -> str:
    """Fill the story's placeholders: {CHILD_NAME}, {PET}, {THEY}, {THEM}, {THEIR}.
    {PET} reads naturally: "her fox" the first time in a narration, "the fox" after that.
    After a word that already determines it ("{THEIR} {PET}", "the {PET}") it is just "fox"."""
    child = sess["child"]
    they, them, their = PRONOUNS.get(str(child.get("pronouns", "")).lower(), PRONOUNS["they"])
    pet = pet_of(sess)
    values = {"CHILD_NAME": child["child_name"], "THEY": they, "THEM": them, "THEIR": their}
    pets_seen = 0

    def fill(m: re.Match) -> str:
        nonlocal pets_seen
        if m.group(1) == "PET":
            before = scene["narration"][:m.start()].split()
            if before and before[-1].lower() in DETERMINERS:
                value = pet
            else:
                value = f"{their} {pet}" if pets_seen == 0 else f"the {pet}"
            pets_seen += 1
        else:
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


def audio_url(request: Request, path: str | None) -> str | None:
    return f"{base_url(request)}{path}" if path else None


def narration_task(sess: dict, scene_id: str) -> asyncio.Task:
    """The (cached) task speaking this child's narration of a scene. Failed tasks are retried."""
    text = narration_for(sess, scene_of(sess, scene_id))
    key = f"{scene_id}:{hashlib.sha1(text.encode()).hexdigest()[:12]}"
    task = NARRATION.get(key)
    if (task is None or task.get_loop() is not asyncio.get_running_loop()
            or (task.done() and (task.cancelled() or task.result() is None))):
        task = NARRATION[key] = asyncio.create_task(voice(voice_tools.speak, text, timeout=NARRATION_TIMEOUT))
    return task


async def narration_path(sess: dict, scene_id: str, wait: float | None = None) -> str | None:
    """Audio of a scene's narration. With `wait`, give up after that many seconds and return None,
    while the (shielded) task keeps running so a later request finds it cached."""
    try:
        task = narration_task(sess, scene_id)  # bounded by NARRATION_TIMEOUT inside voice()
        if wait is None:
            return await task
        return await asyncio.wait_for(asyncio.shield(task), wait)
    except Exception:  # includes the timeout
        return None


def challenge_task(text: str) -> asyncio.Task:
    """The (cached) task speaking a challenge prompt. Failed tasks are retried."""
    key = hashlib.sha1(text.encode()).hexdigest()[:12]
    task = CHALLENGE.get(key)
    if (task is None or task.get_loop() is not asyncio.get_running_loop()
            or (task.done() and (task.cancelled() or task.result() is None))):
        task = CHALLENGE[key] = asyncio.create_task(voice(voice_tools.speak, text, timeout=NARRATION_TIMEOUT))
    return task


async def challenge_path_within(sess: dict, wait: float) -> str | None:
    """Like challenge_path, but gives up waiting after `wait` seconds (null audio); the speech
    task keeps running and is cached for the next request."""
    try:
        return await asyncio.wait_for(asyncio.shield(challenge_path(sess)), wait)
    except asyncio.TimeoutError:
        return None


async def challenge_path(sess: dict) -> str | None:
    """Audio of the current challenge prompt, or None when there is no challenge or voice fails."""
    prompt = (sess.get("challenge") or {}).get("prompt")
    if not prompt:
        return None
    try:
        return await challenge_task(prompt)  # bounded by NARRATION_TIMEOUT inside voice()
    except Exception:
        return None


async def speak_all_narration(sess: dict) -> None:
    """One scene at a time, so we stay within ElevenLabs' concurrency limit."""
    for sid in SCENES:
        await narration_path(sess, sid)


PUBLIC_CHALLENGE_KEYS = ("level", "prompt", "target_words")  # the contract; accept stays private


def scene_payload(sess: dict, request: Request, narration_audio: str | None = None,
                  challenge_audio: str | None = None) -> dict:
    scene = scene_of(sess, sess["scene_id"])
    base = base_url(request)
    is_page = sess.get("story") == "adventure"
    return {
        "id": scene["id"],
        "index": scene["page"] if is_page else path_depth(scene["id"]),
        "total": adventure.PAGES if is_page else TOTAL,
        "narration": narration_for(sess, scene),
        "narration_audio_url": audio_url(request, narration_audio),
        "image_url": f"{base}{scene['image_path']}" if is_page else f"{base}/static/scenes/{scene['id']}.jpg",
        "avatar_position": scene.get("avatar_position") or DEFAULT_AVATAR_POSITION,
        "challenge": {k: sess["challenge"][k] for k in PUBLIC_CHALLENGE_KEYS},
        "challenge_audio_url": audio_url(request, challenge_audio),
        "choices": fallback.scene_choices(scene),
        "avatar_url": audio_url(request, sess.get("avatar_path")),  # null until the painting is ready
    }


def decode_avatar_png(value) -> bytes | None:
    """The child's drawn avatar as PNG bytes, from base64 (a data: URL prefix is allowed). None if invalid."""
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("data:"):
        value = value.partition(",")[2]
    try:
        png = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return png if png.startswith(b"\x89PNG\r\n\x1a\n") else None


def painting_enabled() -> bool:
    """PAINT_AVATAR=0 turns avatar painting off; avatar_url then stays null."""
    return os.getenv("PAINT_AVATAR", "1").strip() != "0"


def avatar_traits(avatar: dict) -> dict:
    return {k: avatar[k] for k in paint_avatar.TRAIT_KEYS if k in avatar}


def cached_avatar(png: bytes, traits: dict) -> str | None:
    """The /static path of an already painted avatar for this drawing and traits, without calling fal."""
    path = paint_avatar.AVATAR_DIR / f"{paint_avatar.cache_key(png, traits)}.png"
    return f"/static/avatars/{path.name}" if path.exists() else None


async def paint_avatar_for(sess: dict, png: bytes, traits: dict) -> None:
    """Paint in a worker thread; the PNG lives only in this task and is dropped when it ends.
    paint() returns None when FAL_KEY is missing or painting fails, so avatar_url stays null."""
    sess["avatar_path"] = await asyncio.to_thread(paint_avatar.paint, png, traits)


def enter_scene(sess: dict, scene_id: str, challenge: dict | None = None) -> None:
    """Enter a scene. `challenge` is the agent's first question for it (checked in agent/tutor.py).
    Without one (session start, or the agent was slow, invalid or did not ask) the fallback rule
    uses the scene's authored question, or a say challenge from the narration."""
    scene = scene_of(sess, scene_id)
    sess["scene_attempts"] = 0  # non-silent answers in this scene, for the first-try star
    fallback.enter_scene(sess, scene, narration_for(sess, scene), exclude=name_words(sess))
    if challenge and fallback.decision_type(scene) is None:
        sess["challenge"] = challenge
        sess["key_word"] = questions.key_word(challenge) or sess["key_word"]
        sess["question_types"][-1] = questions.qtype(challenge)


def next_speaking_narrations(sess: dict, scene: dict) -> dict[str, str]:
    """Narration of each possible next scene whose question the agent sets (no authored decision),
    including every branch destination. None for adventures: their pages are written as the
    child chooses, and page 4 has its authored goodnight challenge."""
    if sess.get("story") == "adventure":
        return {}
    return {nid: narration_for(sess, SCENES[nid]) for nid in next_ids(scene)
            if nid and fallback.decision_type(SCENES[nid]) is None}


def pet_of(sess: dict) -> str:
    return (sess["child"].get("avatar") or {}).get("pet") or "puppy"


def goodnight(sess: dict) -> str:
    """The final feedback when the story completes: one short goodnight with the child's name and pet."""
    return f"Goodnight, {sess['child']['child_name']}, sweet dreams to you and your {pet_of(sess)}."


def challenge_word(sess: dict, scene: dict) -> str | None:
    """The learning word of the current challenge (None on a branch choice: that is a preference)."""
    kind = fallback.decision_type(scene)
    if kind == fallback.SINGLE_CORRECT:
        return scene["decision"]["correct_word"]
    if kind == fallback.BRANCH_CHOICE:
        return None
    return sess["key_word"] or questions.key_word(sess["challenge"])


# ---------- endpoints ----------

def clean_name(value) -> str:
    """At most 20 characters: letters, spaces and hyphens only. Anything else -> "Friend"."""
    if not isinstance(value, str):
        return "Friend"
    name = "".join(ch for ch in value if ch.isalpha() or ch in " -")
    name = " ".join(name.split())[:20].strip(" -")
    return name or "Friend"


def clean_practice_words(value) -> list[str]:
    """Parent focus words and recent tricky words: letters only, lowercased, at most 5."""
    if not isinstance(value, list):
        return []
    words = [w.strip().lower() for w in value if isinstance(w, str)]
    return list(dict.fromkeys(w for w in words if w.isalpha() and len(w) <= 30))[:5]


def adventure_enabled() -> bool:
    """ADVENTURE=0 turns the adventure mode off: "story": "adventure" then starts the Pip story."""
    return os.getenv("ADVENTURE", "1").strip() != "0"


PAGE_WAIT = 8.0  # seconds a choice waits for a page still being written, then a fallback page


def story_so_far(sess: dict, scene_id: str | None) -> list[dict]:
    pages = []
    while scene_id:
        scene = sess["scenes"][scene_id]
        pages.append(scene)
        scene_id = scene["parent"]
    return pages[::-1]


async def write_page(sess: dict, parent_id: str, branch: dict) -> dict:
    """Write the page behind one choice, store it, then speak its narration (one call per page)."""
    parent = sess["scenes"][parent_id]
    page, scene_id = parent["page"] + 1, branch["next"]
    data, why = await adventure.generate_page(page, story_so_far(sess, parent_id), pet_of(sess), branch)
    scene = sess["scenes"].setdefault(  # a fallback page already used wins over a late one
        scene_id, adventure.build_scene(page, scene_id, data, parent=parent_id, fallback=why is not None))
    await narration_path(sess, scene_id)
    return scene


def prefetch_pages(sess: dict, scene_id: str) -> None:
    """When a page is shown, start writing BOTH next pages in parallel."""
    scene = sess["scenes"][scene_id]
    for branch in scene.get("branches", []):
        if branch["next"] not in sess["scenes"]:
            task = asyncio.create_task(write_page(sess, scene_id, branch))
            sess["page_tasks"][branch["next"]] = task
            BACKGROUND.add(task)
            task.add_done_callback(BACKGROUND.discard)


async def ensure_page(sess: dict, parent: dict, next_id: str) -> None:
    """The chosen page: ready (prefetched), or wait up to PAGE_WAIT, then a fallback page."""
    if next_id in sess["scenes"]:
        return
    branch = next(b for b in parent["branches"] if b["next"] == next_id)
    task = sess["page_tasks"].get(next_id)
    if task is None or task.get_loop() is not asyncio.get_running_loop():
        task = sess["page_tasks"][next_id] = asyncio.create_task(write_page(sess, parent["id"], branch))
        BACKGROUND.add(task)
        task.add_done_callback(BACKGROUND.discard)
    try:
        await asyncio.wait_for(asyncio.shield(task), PAGE_WAIT)
    except Exception:  # includes the timeout; the task may still finish, but this page is set now
        pass
    if next_id not in sess["scenes"]:
        page = parent["page"] + 1
        sess["scenes"][next_id] = adventure.build_scene(
            page, next_id, adventure.fallback_page(page, branch), parent=parent["id"], fallback=True)


@app.post("/session/start")
async def session_start(request: Request):
    try:
        body = await request.json()
    except Exception:  # empty or non-JSON body: start with defaults instead of a 500
        body = {}
    if not isinstance(body, dict):
        body = {}
    name = clean_name(body.get("child_name"))
    practice = clean_practice_words(body.get("practice_words"))
    avatar = body.get("avatar") if isinstance(body.get("avatar"), dict) else {}
    avatar_png = decode_avatar_png(avatar.get("image_png"))
    avatar = {k: v for k, v in avatar.items() if k != "image_png"}  # never stored, only painted
    child_id = f"{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'child'}-1"
    child = {
        "child_name": name,
        "age": body.get("age"),
        "pronouns": body.get("pronouns", "they"),
        "avatar": avatar,
    }
    CHILDREN.setdefault(child_id, {**child, "sessions": 0})
    CHILDREN[child_id]["sessions"] += 1

    session_id = uuid.uuid4().hex[:12]
    sess = {
        "session_id": session_id, "child_id": child_id, "child": child,
        "date": date.today().isoformat(), "stars": 0, "scene_attempts": 0,
        "log": [], "avatar_path": None, **fallback.new_session_state(),
        "practice_words": practice,
    }
    if avatar_png and painting_enabled():
        traits = avatar_traits(avatar)  # the drawing goes to paint(), never into the session
        sess["avatar_path"] = cached_avatar(avatar_png, traits)
        if sess["avatar_path"] is None:
            in_background(paint_avatar_for(sess, avatar_png, traits))  # never blocks the response
    in_background(tutor.warm_up())  # so the first /turn does not pay for a cold Anthropic connection
    is_adventure = body.get("story") == "adventure" and adventure_enabled()
    sess["story"] = "adventure" if is_adventure else "pip"
    if is_adventure:  # page 1 is the pre-written opening (instant)
        sess["scenes"], sess["page_tasks"] = {}, {}
        data, why = await adventure.generate_page(1, [], pet_of(sess), None)
        first = "a1"
        sess["scenes"][first] = adventure.build_scene(1, first, data, fallback=why is not None)
        title = adventure.TITLE
    else:
        resume = body.get("resume_scene_id")
        first = resume if isinstance(resume, str) and resume in SCENES else START  # invalid: ignored
        title = STORY["title"]
    enter_scene(sess, first)
    SESSIONS[session_id] = sess
    if is_adventure:
        prefetch_pages(sess, first)                  # both page 2s start now, before any audio
    intro_text = (f"{title}. Hello {name}! Are you ready for tonight's bedtime story? "
                  "Snuggle in, and when you're ready, open the book.")  # read on the book cover
    first_audio, first_challenge_audio, intro_audio = await asyncio.gather(  # ready in the response
        narration_path(sess, first), challenge_path(sess),
        voice(voice_tools.speak, intro_text, timeout=NARRATION_TIMEOUT))
    if not is_adventure:
        in_background(speak_all_narration(sess))     # the rest is generated while the child listens
    return {"session_id": session_id, "child_id": child_id, "stars": 0,
            "avatar_url": audio_url(request, sess["avatar_path"]),  # set now only if already painted
            "intro": {"text": intro_text, "audio_url": audio_url(request, intro_audio)},
            "scene": scene_payload(sess, request, first_audio, first_challenge_audio)}


@app.post("/turn")
async def turn(request: Request):
    started = time.perf_counter()
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Body must be JSON: {\"session_id\": ..., \"transcript\": ...}")
        session_id, transcript = body.get("session_id"), body.get("transcript", "")
        skip = body.get("skip") is True
    else:
        form = await request.form()
        session_id = form.get("session_id")
        skip = False
        audio = form.get("audio")
        transcript = ""  # no audio, a failed or slow transcription, or nothing said = silence
        if audio is not None and hasattr(audio, "read"):
            # Kept in memory only: the child's audio is never stored on our server.
            transcript = await voice(voice_tools.transcribe, await audio.read(),
                                     audio.content_type or "audio/webm") or ""

    sess = SESSIONS.get(session_id)
    if not sess:
        raise HTTPException(404, "Unknown session_id")

    scene = scene_of(sess, sess["scene_id"])
    challenge = sess["challenge"]
    word = challenge_word(sess, scene)
    if skip:  # move on with no assessment, no stars and no hit/miss in the log
        transcript = ""
        d = fallback._decision(result="skipped", action="skipped", next_id=next_ids(scene)[0],
                               feedback="Let's see what happens next.", reason="Skipped; moved on without an answer")
        d["next_challenge"] = None
        meta = {"source": "rule", "agent_ms": None, "fallback_reason": None,
                **dict.fromkeys(tutor.USAGE_FIELDS)}
    else:
        d, meta = await tutor.decide(
            sess, scene, narration_for(sess, scene), transcript,
            next_narration=next_speaking_narrations(sess, scene),
            name_words=name_words(sess),
            vocab=STORY_VOCAB | name_words(sess) | set(fallback.words(json.dumps(sess["child"])))
            | set(fallback.words(json.dumps(list(sess.get("scenes", {}).values())))),
        )

    # Code-enforced limits (last line of defence; tutor.py has already checked the agent).
    sess["level"] = max(fallback.MIN_LEVEL, min(fallback.MAX_LEVEL, sess["level"]))
    allowed = next_ids(scene)
    if not d["retry"] and d["next_id"] not in allowed:
        d["next_id"] = allowed[0]

    # Stars: 1 for each challenge completed (a hit), +1 if it was the first try in this scene.
    if d["result"] not in ("silence", "skipped"):
        sess["scene_attempts"] += 1
    hit = d["result"] == "hit" and not d["retry"]
    if hit:
        sess["stars"] += 1 + (sess["scene_attempts"] == 1)

    # Privacy: the child's words are never stored or logged, only which target matched and a count.
    entry = {
        "result": d["log_result"], "action": d["action"],
        "date": date.today().isoformat(), "scene_id": scene["id"], "word": word,
        "matched_word": (d.get("chosen") or word) if hit else None,
        "word_count": len(fallback.words(transcript)),
        "targets": [d["chosen"]] if d.get("chosen") else d["targets"] or challenge["target_words"],
        "level": challenge["level"], "new_level": sess["level"], "tries": sess["tries"],
        "parent_note": d["parent_note"], "reason": d["reason"], **meta,
        "story": sess["story"], "background": scene.get("background_id"),
    }

    story_complete = not d["retry"] and d["next_id"] is None
    if story_complete:
        d["feedback"] = goodnight(sess)
    if d["retry"]:
        sess["challenge"] = d["challenge"]
    elif d["next_id"]:
        if sess["story"] == "adventure":
            await ensure_page(sess, scene, d["next_id"])
        enter_scene(sess, d["next_id"], d.get("next_challenge"))
        if sess["story"] == "adventure":
            prefetch_pages(sess, d["next_id"])

    # Feedback speech, the next scene's narration (usually cached already) and the challenge in parallel.
    feedback_audio, narration_audio, challenge_audio = await asyncio.gather(
        voice(voice_tools.speak, d["feedback"]),
        narration_path(sess, sess["scene_id"], wait=VOICE_TIMEOUT) if not story_complete else asyncio.sleep(0),
        challenge_path_within(sess, VOICE_TIMEOUT) if not story_complete else asyncio.sleep(0),
    )

    asked = None if story_complete else sess["challenge"]  # the question the child hears next
    entry["question_type"] = asked and questions.qtype(asked)
    entry["question_reason"] = asked and asked.get("reason")
    entry["turn_ms"] = round((time.perf_counter() - started) * 1000)
    sess["log"].append(entry)
    log.info("turn %s scene=%s result=%s action=%s source=%s agent_ms=%s turn_ms=%s%s",
             session_id, scene["id"], d["result"], d["action"], meta["source"], meta["agent_ms"],
             entry["turn_ms"], f" fallback_reason={meta['fallback_reason']}" if meta["fallback_reason"] else "")

    return {
        "transcript": transcript, "result": d["result"], "feedback": d["feedback"],
        "feedback_audio_url": audio_url(request, feedback_audio),
        "retry": d["retry"], "stars": sess["stars"],
        "scene": None if story_complete else scene_payload(sess, request, narration_audio, challenge_audio),
        "story_complete": story_complete,
    }


def summary(child: dict, child_id: str, logs: list[dict]) -> dict:
    today = date.today().isoformat()
    tonight = [e for e in logs if e["date"] == today and e["result"] in ("hit", "miss") and e.get("word")]
    stars = sum(s["stars"] for s in SESSIONS.values() if s["child_id"] == child_id and s["date"] == today)
    practised = list(dict.fromkeys(e["word"] for e in tonight))
    needed_help = list(dict.fromkeys(e["word"] for e in tonight if e["result"] == "miss"))
    notes = [e["parent_note"] for e in logs if e["parent_note"]]
    if notes:
        note = notes[-1]
    else:
        note = (f"{child['child_name']} practised {len(practised)} "
                f"word{'s' if len(practised) != 1 else ''} tonight and earned {stars} "
                f"star{'s' if stars != 1 else ''}"
                + (f", needing a little help with {len(needed_help)}." if needed_help else ", all without help."))
    return {"stars_tonight": stars, "words_practised": practised,
            "needed_help": needed_help, "agent_note": note}


@app.get("/progress/{child_id}")
def progress(child_id: str):
    child = CHILDREN.get(child_id)
    if not child:
        raise HTTPException(404, "Unknown child_id")
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
        "avg_answer_length": round(sum(e["word_count"] for e in attempts) / len(attempts), 1)
                             if attempts else 0,
        "nightly": list(nightly.values()),
        "parent_notes": [e["parent_note"] for e in logs if e["parent_note"]],
        "agent_log": [{"scene": e["scene_id"], "action": e["action"], "reason": e["reason"],
                       "source": "agent" if e.get("source") == "agent" else "rule",
                       "story": e.get("story", "pip"), "background": e.get("background"),
                       "question_type": e.get("question_type"), "question_reason": e.get("question_reason")}
                      for e in logs],
        "summary": summary(child, child_id, logs),
    }
