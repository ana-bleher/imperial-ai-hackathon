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

- ONE fixed story loaded from `data/story.json`. The JSON defines the scene count, order, branch points and endings.
- The speaking loop, end to end, on the real frontend with real voice.
- The agent asking, assessing and adapting on every turn.

Not in the MVP. Do not build these until a clean full run has been recorded:

| Cut | Use instead |
|---|---|
| Live story generation | The fixed story |
| Avatar generation | Avatar drawn in the frontend from the child's traits; `avatar_url` is null |
| Real dashboard data | Mock data in the frontend |
| Adaptive narration (story text easier or harder by level) | Fixed narration; optional add-on after the MVP |
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
- Listening: the frontend opens the mic after narration and stops on silence, with hold-to-talk as a
  fallback. It sends the same audio to `/turn` either way.
- TTS audio is saved under `static/audio/` and returned as URLs; scene backgrounds live in `static/scenes/`.

## Who decides what

The backend code runs a fixed loop. It is the orchestrator. There is no orchestrator agent.
The agent owns the child's learning. Code enforces limits around it.

**The agent decides:**
1. Ask: use the scene's authored decision when present; otherwise choose a speaking challenge from the narration.
2. Assess: follow the decision type and any authored answer rules. Accept reasonable pronunciation approximations.
3. Adapt: provide encouragement, hints and appropriate difficulty within the story's rules. Leave a parent note when useful.

**Code enforces:**
- Level stays between 1 and 3. Levels apply to agent-generated speaking challenges only:
  1 = say one word, 2 = repeat a short phrase from the narration (2-4 words),
  3 = repeat a longer phrase or full sentence from the narration.
  The phrase is shown on screen and spoken by the narrator first, so children who cannot read
  yet can repeat it. A hit means most of the phrase's words are in the transcript.
- Use the scene's `decision.max_attempts` when provided; otherwise default to 3 attempts.
- For agent-generated speaking challenges, choose target words from the narration.
- For authored decisions, use the supplied prompt, options, correct answer and hint.
- Follow only the scene's declared `next` or branch destinations. Never invent a scene.
- Every decision is logged for the dashboard.
- If the model takes over 6 seconds or returns something invalid, use a deterministic fallback
  that respects the current decision type, answer rules and retry limit.

Build the fallback rule first. It takes minutes and the demo must never stall.

## Agent tools (`tools/`, one file per tool)

- `get_child_state(session_id)` → level, words practised, recent hits and misses
- `ask(prompt, target_words, level)` → sets the challenge for the scene
- `assess(result, reason)` → records "hit" or "miss" and why
- `set_difficulty(level)` → 1, 2 or 3
- `next_step(action)` → "advance", "retry_with_hint" or "move_on"
- `notify_parent(note)` → short note for the parent dashboard

One model call per turn. Everything the agent says to the child is ONE short, warm sentence. When narration or agent lines
mention the hero, use the child's name and chosen pronouns (she/he/they).

Not agent tools (code calls these every turn): `voice.transcribe(audio)`, `voice.speak(text)`, in `tools/voice.py`.

## One turn

1. Frontend shows the scene and plays the narration, then the challenge.
2. The mic opens after the challenge (or the child holds the button) and the child speaks. Frontend posts the audio to `/turn`.
3. Code transcribes it with ElevenLabs.
4. Agent assesses the answer, sets the difficulty and picks the next step.
5. Code checks the agent's choices against the limits above.
6. Code turns the agent's line into speech and returns the response.

After each result:
- Hit: give brief, warm praise, then follow the scene's transition rules. Never claim to measure pronunciation quality.
- Miss: give encouraging feedback and a hint. Replay only the challenge, not the narration.
- When attempts are exhausted: model the answer where appropriate, praise the effort, advance and leave a parent note.
- Silence: offer gentle encouragement; do not count the first silence as a miss.

Decision types:
- `single_correct`: a learning question with a correct answer. Use `correct_word` to assess the answer; other options trigger the authored retry or hint behaviour.
- `branch_choice`: a story preference. Every declared branch option is valid and selects its corresponding destination. Do not count an unrecognised choice as a learning miss.
- No `decision`: the agent creates a speaking challenge from the narration.

For an unrecognised branch choice, repeat the options. After repeated uncertainty, propose an
option and allow the child to accept it or choose another.

Feedback must remain supportive. An answer may be incorrect without telling the child "you're wrong".

## Story file (`data/story.json`)

The story file defines the authored content and navigation.

- Top-level fields include `title`, optional `description`, optional `start_scene`, and `scenes`.
- Each scene has a unique `id`, string `narration`, `image_prompt`, and optional `avatar_position`.
- Narration length should suit the audience; there is no fixed word count.
- Use `next` for a linear transition, `branches` for a choice of destinations, and `next: null` for an ending.
- Branch entries contain `word`, `label`, `icon`, and `next`; labels and icons supply the frontend's choice cards.
- An optional `decision` defines an authored question or choice, including its type, prompt, options, answer rules, hints and retry behaviour.
- Without an authored decision, the agent generates a speaking challenge.
- All scene references must exist. Every path must eventually reach an ending.
- Endings should provide a calm bedtime wind-down.

The backend must explicitly implement supported decision behaviours. JSON action names describe
behaviour; they are not executable instructions.

## Data contract (fixed; examples in `contract/`)

`POST /session/start`
```json
{ "child_name": "Mia", "age": 5, "pronouns": "she",
  "avatar": {"skin_tone": "medium", "hair_style": "curly", "hair_colour": "red", "outfit": "raincoat", "pet": "fox"} }
```
returns
```json
{ "session_id": "abc", "child_id": "mia-1", "avatar_url": null,
  "scene": { "id": "s1", "index": 1, "total": 5, "narration": "...", "narration_audio_url": null,
             "image_url": "https://.../s1.jpg", "avatar_position": {"x": 0.26, "y": 0.64, "scale": 0.32},
             "challenge": { "level": 1, "prompt": "Can you say 'afternoon'?", "target_words": ["afternoon"] },
             "choices": null } }
```
`POST /turn`: multipart form with `session_id` and `audio`, OR JSON
`{ "session_id": "abc", "transcript": "afternoon!" }` for testing. Returns
```json
{ "transcript": "afternoon", "result": "hit", "feedback": "You said 'afternoon'!",
  "feedback_audio_url": null, "retry": false, "scene": { "...same shape as above..." },
  "story_complete": false }
```
`retry: true` means stay on the same scene; `scene` repeats with the new challenge.

`GET /progress/{child_id}`
```json
{ "child_name": "Mia", "sessions": 3, "target_words_hit": 14, "attempts": 20,
  "new_words": ["forest", "brave"], "avg_answer_length": 2.4,
  "nightly": [{"date": "2026-11-14", "hits": 5, "attempts": 7}],
  "parent_notes": ["Struggled with 'lantern' - practise together"],
  "agent_log": [{"scene": "s2", "action": "retry_with_hint",
                 "reason": "Answer was not 'sun' (try 1 of 3); gave the authored hint"}] }
```
`agent_log` is optional: one entry per logged decision (`action` is advance, retry, retry_with_hint
or move_on). Reasons never quote the child's words.
`avatar_url` is null: the frontend draws the avatar from `pronouns` and `avatar`; the backend only stores them.
`narration_audio_url` and `feedback_audio_url` are null until real audio exists; show the text meanwhile.
`scene.avatar_position` comes from the scene in `story.json` (default `{"x": 0.3, "y": 0.62, "scale": 0.35}`).
Narration placeholders `{CHILD_NAME}`, `{PET}`, `{THEY}`, `{THEM}`, `{THEIR}` are filled from `/session/start`.
`choices` lists the tap cards, each `{"word", "label", "icon"}`: the `decision.options` on `single_correct`
scenes, the `branches` on `branch_choice` scenes, and null otherwise. Example (s3):
`[{"word": "bridge", "label": "Cross the bridge", "icon": "bridge"}, {"word": "boat", "label": "Take the boat", "icon": "boat"}]`.
On `single_correct` scenes `challenge.target_words` lists all the options, so the screen never gives the answer away.
`word` must match the words in `story.json`, so options and branches there carry `label` and `icon` too. Change field names only by team
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
| 1, to 16:40 | Mock backend, deployed. Send Ana the link. | Transcribe and speak working in a test script. Pick the voice. | `story.json` committed. One test background on fal. |
| 2, to 17:40 | Real `/turn`: fallback rule, then the agent with its tools and limits. | Voice wired into the backend. | Backgrounds for every scene. Agent system prompt with Anvay. |
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
| Incorrect answer to a `single_correct` question | authored hint or retry; advances when the attempt limit is reached |
| Attempt limit reached (default: three misses) | models the answer where appropriate, then moves on with a parent note |
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
