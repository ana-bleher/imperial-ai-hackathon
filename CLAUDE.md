# CLAUDE.md — project plan (read this first)

## What we're building
**[APP NAME]**: an interactive story-time web app for children aged **4–6**. The child creates their
own avatar, becomes the hero of a short illustrated story, and **speaks** to move the story forward.
Core goal: **speaking and vocabulary practice** (not speech therapy). One chapter per night,
max ~15 minutes, calm wind-down ending. Parents log in, set up the child and see progress.

- **Main track:** 02 Voice, Vision & Generative Media
- **Sub-bounties (max 2):** ElevenLabs (real-time voice agent) + fal (generative images)
- **Cross-cutting:** Figma Best-Designed AI Product (frontend built with Figma Make) · Adaption (stretch)
- **Deadline:** Devpost **Sun 12:00** (write-up + public GitHub link + 2-min video).
  Building closes Sat 21:00, reopens Sun 10:00. Feature freeze Sun ~09:30.

## Vision
Long term: an online archive of real (physical) children's books, each turned into an interactive
story the child lives through. For the hackathon: ONE original story we write ourselves.

## Core principles
- **Ownership:** the child is the hero (own avatar, own name, chosen pronouns she/he/they) and makes
  real choices at 2 decision points that change what happens next.
- **Adaptive language, fixed plot:** the plot stays the same, but the agent adapts the LANGUAGE to the
  child's level: narration complexity (level 1 short simple sentences → level 3 richer sentences and
  new words) and the speaking challenge (1 word → short phrase → full sentence). It always nudges
  one step above what the child just managed, to encourage learning.

## Priorities (in this order)
1. **Speaking loop (must):** scene → narration → child speaks → agent evaluates → feedback → story adapts.
2. **Parent progress page (must, small).**
3. **Avatar + AI backgrounds (should):** drawn avatar (frontend) on fal-painted scene backgrounds.
4. **Stretch:** real-time ElevenLabs voice agent, Adaption fine-tune, per-scene generated images, art styles.

## MVP scope
- Demo parent login (any input works) → create child (name, age 4/5/6, 4 avatar traits). No photo uploads.
- ONE story, 5 scenes, 2 branch points (data/story.json).
- Each scene: narration audio → speaking challenge at difficulty level 1–3 → feedback → next scene.
- Agent adapts within restricted options: branch from the child's word, difficulty up/down, hint, retry.
- Progress metrics stored per session; parent dashboard.

## Architecture
```
Figma Make app (hosted)  ──HTTPS──▶  FastAPI backend (deployed on Render)  ──▶  Story agent (Claude)
 mic recording (MediaRecorder)          /session/start  /turn  /progress           tools below
 audio playback, images                 ElevenLabs STT + TTS · fal images · /static audio + images
```
- Backend must allow CORS from any origin and be reachable over HTTPS (Figma Make can't call localhost).
- Audio: backend saves TTS mp3 files to `static/` and returns their URLs.
- Narration audio for all scenes is generated right after /session/start (in the background), so the
  story never waits.

### Avatar + images (DECIDED)
- The child's avatar is DRAWN IN THE FRONTEND (Figma Make) from the chosen traits (pronouns, skin tone,
  hair style, hair colour, outfit, animal friend). It is instant and identical in every scene.
  No AI generation for the avatar. Backend just stores the traits; `avatar_url` may be null.
- AI (fal) paints only the STORY BACKGROUNDS: one per scene, same picture-book style, no characters,
  pre-made and stored in `static/scenes/`. The frontend places the avatar on top at `avatar_position`.

### Turn-taking (DECIDED)
- The child taps "Start the story" once (unlocks mic + audio). After that it is hands-free:
  narration ends → "Your turn!" → mic opens automatically → stops after ~1.5 s silence (max 8 s)
  → audio sent to /turn → feedback → next scene.
- At decision points the child SAYS the option ("boat"). If no answer within 4 s, the two choice
  cards fade in so the child can tap instead (voice still works). Silence on normal challenges →
  one gentle re-prompt.
- Stretch (ElevenLabs bounty): fully real-time conversation via an ElevenLabs agent.

### Agent tools (tools/, one file per tool)
- `get_scene(scene_id)` → scene text, challenge per level, allowed branches (from data/story.json)
- `evaluate_answer(transcript, target_words)` → plain Python: hit/miss, matched words, word count
- `choose_next(scene_id, transcript)` → next scene id, ONLY from allowed branches
- `set_difficulty(session_id, level)` → 1 = one word, 2 = short phrase, 3 = full sentence
- `log_progress(session_id, metrics)` → attempts, hits, new words, answer length
- `notify_parent(session_id, note)` → human-in-the-loop note (e.g. 3 misses on one scene)
- `voice.transcribe(audio)` / `voice.speak(text)` → ElevenLabs

Difficulty rule: 2 hits in a row → level up (max 3); 2 misses → level down (min 1) + hint;
3 misses on the same scene → praise the effort, move on, notify_parent.

### Data contract (fixed — example files in `contract/`)
`POST /session/start`
```json
{ "child_name": "Mia", "age": 5, "pronouns": "she", "avatar": {"skin_tone": "medium", "hair_style": "curly", "hair_colour": "red", "outfit": "dress", "pet": "fox", "fav_colour": "green"} }
```
→
```json
{ "session_id": "abc", "child_id": "mia-1", "avatar_url": "https://.../avatar.png",
  "scene": { "id": "s1", "index": 1, "total": 5, "narration": "...", "narration_audio_url": "https://...",
             "image_url": "https://.../s1.png", "avatar_position": {"x": 0.3, "y": 0.62, "scale": 0.35},
             "challenge": { "level": 1, "prompt": "Can you say 'forest'?", "target_words": ["forest"] },
             "choices": null } }
```
`choices` is null, or at a decision point: `[{"word": "bridge", "label": "Cross the bridge", "icon": "bridge"}, {"word": "boat", "label": "Take the boat", "icon": "boat"}]`
```json
```
`POST /turn` — multipart form: `session_id`, `audio` (webm) — OR JSON `{ "session_id": "abc", "transcript": "forest!" }` for testing
→
```json
{ "transcript": "forest", "result": "hit", "feedback": "Brilliant! You said forest!",
  "feedback_audio_url": "https://...", "retry": false, "scene": { ...same shape as above... },
  "story_complete": false }
```
(`retry: true` → stay on the same scene, `scene` repeats with an easier challenge.)

`GET /progress/{child_id}`
```json
{ "child_name": "Mia", "sessions": 3, "target_words_hit": 14, "attempts": 20,
  "new_words": ["forest", "brave"], "avg_answer_length": 2.4,
  "nightly": [{"date": "2026-11-14", "hits": 5, "attempts": 7}],
  "parent_notes": ["Struggled with 'lantern' — practise together"] }
```
Change field names only by team agreement; update `contract/` and tell the frontend.

## Models & services
- Story agent (feedback + decisions): `claude-sonnet-5-5`. Keep replies ≤ 2 short sentences for the child.
- Building: Claude Code with Opus 5.5; switch to `claude-fable-5-2` for hard bugs/design.
- Speech-to-text + text-to-speech: ElevenLabs (keys in .env). Images: fal. Frontend: Figma Make.

## Safety rules (non-negotiable)
- Never ask the child for personal information; never repeat personal info back.
- Stay inside the story; off-topic/upsetting input → gentle redirect; notify_parent if distressed.
- No scary or violent content; illustrated styles only; no photos of children.
- Audio is processed per turn and not stored; only metrics are stored.

## Owners
- **Anvay:** backend (FastAPI, agent loop, tools, deployment, contract), CLAUDE.md, check-ins
- **Ines:** voice (ElevenLabs STT/TTS), turn-taking support on the backend, real-time voice + Adaption stretch (remote after 19:30)
- **Kiko (Francisco):** story.json + scene illustrations, tests, integration checks, Devpost, write-up, deck, demo
- **Ana:** Figma Make frontend (all screens, mic, audio, dashboard), UX, video, lead presenter

## Repo layout (matches the existing repo)
| Path | What goes in it | Owner |
|---|---|---|
| `agent/` | FastAPI app (`agent/main.py`), agent loop, `/session/start` `/turn` `/progress` | Back-end (Anvay, Ines) |
| `tools/` | One file per tool: the function and its description | Back-end (Anvay, Ines) |
| `prompts/` | `story_agent.md` system prompt | Back-end |
| `data/` | `story.json` and other small data files | Kiko (story), Back-end |
| `static/` | Generated audio, avatars, pre-made scene images (served at /static) | Back-end, Kiko (scenes) |
| `tests/` | 5 test inputs + expected outputs, rerun after every change | Anvay, Kiko |
| `contract/` | Example request/response JSON shared by both teams | Both, by agreement only |
| `frontend/` | Exported Figma Make code + mock JSON | Front-end (Ana, Kiko) |
| `notebooks/` | Experiments, not imported by the app | Anyone |

## Working rules
- Pull before working, small commits with clear messages, never commit `.env`, `main` always runs.
- Behind at 18:00? Cut features, protect the speaking loop.

## Rules for AI assistants

- Make small, focused changes. One feature or fix per request.
- Only edit files in the current team's folders (see Repo layout). Ask before touching the other team's folders or `contract/`.
- Never read, print, create or commit `.env` or any API key. Use `os.getenv` with names from `.env.example`.
- Do not change the API contract above without flagging it explicitly.
- Do not add dependencies without saying so; if you add one, update `requirements.txt`.
- Prefer fake data in `data/` over live services until the walking skeleton works end to end.
- After a change, say how to run or test it.
- Do not run git commands (commit, push, pull, branch). Humans do that in GitHub Desktop.

## Rules for humans

- Each team works on its own branch: `backend` (Anvay, Ines) and `frontend` (Ana, Kiko).
- Merge a team branch into `main` by Pull Request at every working milestone; after the other team merges, update your branch from `main`.
- Name every commit for what it does ("Add lookup_order tool", not "update").
- Pull before you start working.
- Commit and push small and often; commit every time something works.
- Work in your own folder where possible.
- `main` must always run: the demo deploys from it.
- Merge conflict or strange error? Ask the team; never force-push.
- When a decision is made out loud, update this file.
