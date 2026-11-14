# CLAUDE.md — project brief (read this first)

This is the single source of truth. Where PROMPTS.md disagrees with this file, this file wins
(PROMPTS.md sections C and D describe an older tool set: ignore those parts).

## What we're building

An interactive story-time web app for children aged 4–6. The child hears a short illustrated
story, and speaks to move it forward. The goal is speaking and vocabulary practice. It is not
speech therapy and we never claim it is.

An AI agent acts as the child's tutor inside the story. It decides what to ask the child, judges
the answer, and adapts the difficulty. Parents set the child up and see a progress page.

- Hackathon track: Voice, Vision & Generative Media
- Sponsor bounties: ElevenLabs (voice) and fal (images). Frontend is built in Figma Make.
- Submission: Devpost, Sunday 12:00. Needs a write-up, a public GitHub repo and a 2-minute video.

## Right now: MVP by 18:40 Saturday

We have three hours. Build only this:

- ONE fixed story: 5 scenes on the main path, 2 branch points, 7 scenes in total (`data/story.json`).
- The speaking loop, end to end, on the real frontend with real voice.
- The agent asking, assessing and adapting on every turn.

Not in the MVP. Do not build these until a clean full run has been recorded:

| Cut | Use instead |
|---|---|
| Live story generation | The fixed story |
| Avatar generation | One default character image |
| Real dashboard data | Mock data in the frontend |
| Auto-listening | Hold-to-talk button |
| Real-time ElevenLabs agent | Speech-to-text and text-to-speech calls |

## Architecture

```
Figma Make frontend  --HTTPS-->  FastAPI app agent/main.py (Render)  -->  Tutor agent (claude-sonnet-5-5)
 mic recording, audio playback     /session/start  /turn  /progress
 scene images                      ElevenLabs speech-to-text + text-to-speech
                                   /static audio + images (fal backgrounds)
```

- The backend allows CORS from any origin and must be reachable over HTTPS.
- The backend accepts whatever audio format the browser sends, not only webm.
- TTS audio is saved under `static/audio/` and returned as URLs; scene backgrounds live in `static/scenes/`.

## Who decides what

The backend code runs a fixed loop. It is the orchestrator. There is no orchestrator agent.
The agent owns the child's learning. Code enforces limits around it.

**The agent decides:**
1. Ask: which word or question to put to the child in this scene, at which level.
2. Assess: whether the answer is a hit or a miss. Be generous: "fowest" counts for "forest".
3. Adapt: level up or down, retry with a hint, or move on. Whether to leave a parent note.

**Code enforces:**
- Level stays between 1 and 3. Levels apply to ordinary scenes only:
  1 = say one word, 2 = repeat a short phrase from the narration (2-4 words),
  3 = repeat a longer phrase or full sentence from the narration.
  The phrase is shown on screen and spoken by the narrator first, so children who cannot read
  yet can repeat it. A hit means most of the phrase's words are in the transcript.
- At most 3 tries per scene, then the story moves on.
- Target words are chosen by the agent and must appear in the scene's narration (on branch
  scenes, they are the two branch words).
- Next scene must be one of the scene's allowed branches.
- Every decision is logged for the dashboard.
- Fallback: if the model takes over 6 seconds or returns something invalid, use the simple rule
  (2 hits in a row = level up, 2 misses = level down plus a hint) and a template line.

Build the fallback rule first. It takes minutes and the demo must never stall.

## Agent tools (`tools/`, one file per tool)

- `get_child_state(session_id)` → level, words practised, recent hits and misses
- `ask(prompt, target_words, level)` → sets the challenge for the scene
- `assess(result, reason)` → records "hit" or "miss" and why
- `set_difficulty(level)` → 1, 2 or 3
- `next_step(action)` → "advance", "retry_with_hint" or "move_on"
- `notify_parent(note)` → short note for the parent dashboard

One model call per turn. Everything the agent says to the child is ONE short, warm sentence.

Not agent tools (code calls these every turn): `voice.transcribe(audio)`, `voice.speak(text)`, in `tools/voice.py`.

## One turn

1. Frontend shows the scene and plays the narration, then the challenge.
2. Child holds the button and speaks. Frontend posts the audio to `/turn`.
3. Code transcribes it with ElevenLabs.
4. Agent assesses the answer, sets the difficulty and picks the next step.
5. Code checks the agent's choices against the limits above.
6. Code turns the agent's line into speech and returns the response.

After each result:
- Hit: praise that names the word ("You said 'lantern'!"), then the next scene. Never comment
  on pronunciation quality, because we cannot measure it.
- Miss: never say "wrong". Model the word and invite another try. Replay only the challenge,
  not the narration.
- Third miss: praise the effort, move on, leave a parent note.
- Silence: a gentle "shall we try together?" and do not count it as a miss the first time.

Branch scenes:
- The branch word is the challenge. Saying either option is a hit and chooses the path.
  This is always one word, whatever the child's level.
- Neither word, first time: an encouraging repeat of the two options.
- Neither word, second time: the agent proposes one ("Shall we take the bridge?").
  "Yes" takes it, "no" takes the other, anything else takes the proposed one.
- No miss is counted during this flow.

## Story file (`data/story.json`)

```json
{ "title": "", "scenes": [ {
  "id": "s1", "narration": "60-90 words", "image_prompt": "background only, no characters",
  "next": "s2"
} ] }
```
Branch scenes use `"branches": [{"word": "bridge", "next": "s3a"}, {"word": "boat", "next": "s3b"}]`
in place of `"next"`. There is no pre-written word list: the agent picks each scene's target
words from the narration.
Branches follow scene 2 (s3a/s3b) and scene 4 (s5a/s5b). Both final scenes end calmly with the
hero getting ready for sleep.

## Data contract (fixed; examples in `contract/`)

`POST /session/start`
```json
{ "child_name": "Mia", "age": 5, "avatar": {"hair": "curly red", "outfit": "yellow raincoat", "pet": "fox", "fav_colour": "green"} }
```
returns
```json
{ "session_id": "abc", "child_id": "mia-1", "avatar_url": "https://.../avatar.png",
  "scene": { "id": "s1", "index": 1, "total": 5, "narration": "...", "narration_audio_url": "https://...",
             "image_url": "https://.../s1.png", "avatar_position": {"x": 0.3, "y": 0.62, "scale": 0.35},
             "challenge": { "level": 1, "prompt": "Can you say 'forest'?", "target_words": ["forest"] } } }
```
`POST /turn`: multipart form with `session_id` and `audio`, OR JSON
`{ "session_id": "abc", "transcript": "forest!" }` for testing. Returns
```json
{ "transcript": "forest", "result": "hit", "feedback": "You said forest!",
  "feedback_audio_url": "https://...", "retry": false, "scene": { "...same shape as above..." },
  "story_complete": false }
```
`retry: true` means stay on the same scene; `scene` repeats with the new challenge.

`GET /progress/{child_id}`
```json
{ "child_name": "Mia", "sessions": 3, "target_words_hit": 14, "attempts": 20,
  "new_words": ["forest", "brave"], "avg_answer_length": 2.4,
  "nightly": [{"date": "2026-11-14", "hits": 5, "attempts": 7}],
  "parent_notes": ["Struggled with 'lantern' - practise together"] }
```
For the MVP, `avatar_url` is the default character image. Change field names only by team
agreement, then update `contract/` and tell Ana.

## Audio

- Narration for all scenes is generated in the background right after `/session/start`.
- The agent's challenge, hint and feedback lines are generated during the turn, so keep them short.
- Feedback is spoken AND shown as text. Children this age mostly cannot read.

## Safety rules (non-negotiable)

- Never ask the child for personal information and never repeat it back.
- Stay inside the story. Off-topic or upsetting input gets a gentle redirect, and a parent note
  if the child seems distressed.
- Nothing scary or violent. Illustrated styles only. No photos of children.
- Our server does not store the child's audio. It is sent to ElevenLabs for transcription. Only
  metrics are stored.

## Owners and the three hours

| Hour | Anvay (backend, agent) | Ines (voice) | Kiko (content, testing) |
|---|---|---|---|
| 1, to 16:40 | Mock backend, deployed. Send Ana the link. | Transcribe and speak working in a test script. Pick the voice. | `story.json` committed (narration and branches only). One test background on fal. |
| 2, to 17:40 | Real `/turn`: fallback rule, then the agent with its tools and limits. | Voice wired into the backend. | Seven backgrounds. Agent system prompt with Anvay. |
| 3, to 18:40 | Fix integration bugs. Measure turn delay. | Test real speech on Ana's page. | Run the tests and the full story. Record one clean run. |

Ana: Figma Make frontend (all screens, mic, audio playback, mock dashboard), video, lead presenter.

Checkpoints:
- 16:40: Ana has a live link returning mock data; story committed; one clip transcribed and spoken.
- 17:40: a full story runs by typed transcript with the agent asking, assessing and adapting.
- 18:40: a full story runs by voice on the frontend, and one clean run is recorded.

## Tests (JSON transcripts against `/turn`)

| Child says | Expected |
|---|---|
| The target word | hit, praise names the word, next scene |
| A near miss ("fowest") | agent accepts it as a hit |
| A branch word | story follows that branch |
| Neither branch word, twice | agent proposes one; "yes" accepts it |
| Three misses on one scene | easier level, then moves on with a parent note |
| Off-topic or personal | gentle redirect, nothing personal repeated |

## After the MVP, in this order

1. Live story generation: the agent writes each next scene behind the same contract, choosing a
   background from a pre-made library, with both options generated while the current scene plays.
   The fixed story stays as the fallback.
2. Avatar: generate once on fal, remove the background, overlay on scenes at `avatar_position`.
3. Real-time ElevenLabs agent that calls `/turn` with the transcript, so no button is needed.

## Repo layout

| Path | What goes in it | Owner |
|---|---|---|
| `agent/` | `agent/main.py` FastAPI app and endpoints, the agent call, the fallback rule, session store | Anvay |
| `tools/` | One file per agent tool; `tools/voice.py` (transcribe, speak) | Anvay (agent tools), Ines (voice) |
| `prompts/` | `story_agent.md` system prompt | Anvay, Kiko |
| `data/` | `story.json` | Kiko |
| `static/` | `audio/` generated speech, `scenes/` fal backgrounds, default avatar; served at `/static` | Ines (audio), Kiko (scenes) |
| `contract/` | Example request/response JSON | Both teams, by agreement only |
| `tests/` | Contract test, fallback-rule tests, transcript tests | Anvay, Kiko |
| `frontend/` | Exported Figma Make code + mock JSON | Ana |
| `notebooks/` | Experiments, never imported by the app | Anyone |

Run locally: `uvicorn agent.main:app --reload`. Render start command: `uvicorn agent.main:app --host 0.0.0.0 --port $PORT`.

## Working rules

- Pull before working. Small commits with clear messages. Never commit `.env`. `main` always runs.
- Keep it minimal. Do not add features that are not listed here.
- If behind, cut features and protect the speaking loop.

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
