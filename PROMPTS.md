# PROMPTS.md — ready-to-paste prompts (in build order)

All Claude Code prompts assume CLAUDE.md is in the repo root. Replace [APP NAME] once named.

---

## A. Story content — Kiko (Claude chat, Opus 5.5) — START NOW
```
Write an original children's story for ages 4–6 for an interactive speaking-practice app.
The hero is called {CHILD_NAME} (use the placeholder literally) and has an animal friend {PET}.
Constraints:
- Exactly 5 scenes on the main path, warm and calm, ending in a cosy wind-down where the hero gets
  ready for sleep. The hero's pronouns are {THEY}/{THEM}/{THEIR} placeholders.
- The PLOT is identical at every level, but each scene's narration is written at 3 language levels:
  level 1 = very short, simple sentences (~40 words); level 2 = normal (~60 words);
  level 3 = richer sentences with 1–2 new describing words (~80 words).
- 2 branch points (end of scene 2 and scene 4). Each offers exactly 2 options the child picks by
  saying ONE word (e.g. "bridge" or "boat"). Each option leads to its own short scene (s3a/s3b,
  s5a/s5b), so 7 scenes in total.
- Each scene has a speaking challenge at 3 levels: 1 = one target word, 2 = short phrase,
  3 = full sentence. Target words are concrete, everyday vocabulary for 4–6 year olds.
- Each scene has an "image_prompt" describing the BACKGROUND only (no characters), plus
  "avatar_position" {x, y, scale} (0–1) saying where the hero should stand in the picture.
- Nothing scary or violent; no real places or brands.
Return valid JSON only:
{ "title": "", "scenes": [ { "id": "s1", "narration": {"1": "", "2": "", "3": ""}, "image_prompt": "",
  "avatar_position": {"x":0.3,"y":0.62,"scale":0.35},
  "challenge": { "1": {"prompt":"", "target_words":[]}, "2": {...}, "3": {...} },
  "next": "s2" OR "branches": [{"word":"", "label":"", "next":"s3a"}, {"word":"", "label":"", "next":"s3b"}] } ] }
```
Save as `data/story.json`, commit, tell the team.

## B. Scene illustrations — Kiko (fal) — after A
For each scene's image_prompt (backgrounds only, same style for all 7):
```
Children's picture-book illustration, soft watercolour, warm muted colours, calm bedtime mood.
{IMAGE_PROMPT}. Wide landscape composition with empty space in the foreground for a character.
No people, no animals in the foreground, no text.
```
Save as `static/scenes/{scene_id}.jpg`, with a 1600-pixel long edge and the original aspect ratio. Keep the same style words for every scene.

---

## C. Backend skeleton — Anvay (Claude Code, Opus 5.5) — START NOW
```
Read CLAUDE.md. Build the backend with FastAPI (app in agent/main.py):
1. POST /session/start, POST /turn (accepts multipart audio OR JSON transcript), GET /progress/{child_id}
   returning EXACTLY the example JSON in CLAUDE.md. Version 1 returns mock data, no AI.
2. Serve static/ at /static. CORS open to all origins.
3. In-memory session store: session_id, child profile, current scene, level, hit streak, miss counts, metrics.
4. Load data/story.json if present; otherwise use a 2-scene placeholder story.
5. Write contract/*.json example files and tests/test_contract.py checking every field exists.
6. Add requirements.txt and a render.yaml / start command for deployment on Render.
Keep it minimal; don't add features not listed.
```
Then deploy (Render: new Web Service from the GitHub repo, add env vars) and share the URL with Ana.

## D. Real agent loop — Anvay (Claude Code) — after C works deployed
```
Replace the mock in /turn with the real agent:
- Tools in tools/: get_scene, evaluate_answer (plain Python fuzzy match + word count),
  choose_next (only allowed branches), set_difficulty, log_progress, notify_parent.
- Call the Anthropic API with model claude-sonnet-5-5, system prompt from prompts/story_agent.md,
  and these tools. The model writes the feedback text; the deterministic tools decide hit/miss and
  the difficulty rule from CLAUDE.md.
- If the Anthropic call fails or takes >6s, fall back to a template feedback so the demo never stalls.
- Log timings for each step.
Run tests/ after every change.
```

## E. Story agent system prompt — save as `prompts/story_agent.md`
```
You are the gentle narrator-guide of a bedtime story for {CHILD_NAME}, aged {AGE}.
Goal: help the child practise speaking and new words while enjoying the story.
Each turn you get: the current scene, the challenge, the child's transcript and the evaluate_answer result.
1. Reply to the child in at most 2 short, warm sentences with simple words.
2. Hit: praise the specific word ("You said 'lantern' — so clear!").
3. Miss: never say "wrong". Model the word ("Let's say it together: lan-tern!") and invite one more try.
4. Choose the next scene ONLY via choose_next from the allowed branches. Never invent new plot.
5. Call set_difficulty and log_progress every turn.
6. Off-topic, personal or upsetting input: never ask for or repeat personal info; steer back to the
   story; call notify_parent if the child seems upset.
7. Final scene: calm, quiet, sleepy wording; say goodnight using the child's name.
Output only the words to say to the child, plus your tool calls.
```

---

## F. Voice — Ines (Claude Code) — START NOW
```
Add tools/voice.py:
- transcribe(audio_bytes, mime_type) -> str using ElevenLabs speech-to-text (convert webm if needed).
- speak(text) -> URL: ElevenLabs text-to-speech with VOICE_ID from .env, save mp3 to
  static/audio/{uuid}.mp3, return the public URL.
- A script tests/voice_roundtrip.py: record/load a sample .webm → transcribe → speak → print latencies.
Then wire it in: /turn with audio → transcribe → agent → speak(feedback).
After /session/start, generate narration audio for all scenes in the background.
```
Pick one warm, calm, slightly slow narrator voice and keep it for every scene.
Stretch (ElevenLabs bounty): an ElevenLabs conversational agent whose tool calls our /turn, so the
child talks without holding a button.

## G. (DROPPED) AI-generated avatar — the avatar is now drawn in the frontend. Skip this section.
## Old G, kept for reference only
```
Add tools/images.py with make_avatar(traits) -> URL:
1. Call a fal text-to-image model with the avatar prompt below.
2. Call a fal background-removal model on the result → transparent PNG.
3. Save to static/avatars/{child_id}.png and return the URL.
Call it from /session/start. If it fails or takes >20s, return a default avatar so the demo continues.
```
Avatar prompt:
```
Children's picture-book character, soft watercolour, warm muted colours. A friendly {AGE}-year-old
child with {HAIR}, wearing {OUTFIT}, favourite colour {FAV_COLOUR}, holding a small {PET}.
Full body, standing, front-facing, plain white background, simple shapes, gentle smile. No text.
```

---

## H. Frontend — Ana (Figma Make) — START NOW, one prompt at a time
**H1. Shell + design (mock data)**
```
Build a mobile-first web app called [APP NAME]: an interactive bedtime-story app where children aged
4–6 become the hero of the story and practise speaking new words. Parents set it up.
Design: deep navy (#1B2340), warm cream (#FFF6E5), soft gold (#F2C14E), muted teal (#5FB3A8);
rounded friendly typeface; very large text and touch targets on child screens; minimal text for
children; rounded corners (24px); gentle fade/scale animations; picture-book feel.
Screens (React state navigation, mock data only):
1. Parent login (demo, any input works), "Parents only" label.
2. "Who's reading tonight?" child cards + "Add a child".
3. Create a child: name, age (4/5/6), avatar traits with big picture buttons (hair, outfit,
   favourite colour, animal friend) → show avatar → big "That's me!" button.
4. Story screen: full-width scene image with the child's avatar image overlaid at a given position
   (x, y, scale as fractions), short narration text at the bottom, play/pause, ONE huge round
   "Hold to talk" microphone button, feedback speech bubble, progress dots (scene index/total).
5. Goodnight screen: calm starry animation, "Goodnight {name}!", stars earned.
6. Parent dashboard: words hit vs attempts, new words as chips, average answer length, nightly bar
   chart, notes from the story guide, streak.
```
**H2. Mic + audio (test early, on the published link if preview blocks the mic)**
```
Make the mic button work: press and hold to record with MediaRecorder (webm), release to stop;
pulsing glow + sound-wave animation while recording; friendly message for parents if permission is
blocked. Add an audio player that auto-plays the scene's narration_audio_url when a scene appears,
with the play/pause button.
```
**H3. Connect to backend (when Anvay shares the URL)**
```
Connect to our backend. One config constant API_URL = "{URL}". If the API is unreachable, fall back
to the mock data so the demo never breaks. Show twinkling-star loading states; never show raw errors.
1. "That's me!" → POST {API_URL}/session/start with {PASTE contract/session_start_request.json};
   response {PASTE contract/session_start_response.json}. Show avatar_url; open the story with scene.
2. Mic release → POST {API_URL}/turn as multipart form (session_id, audio). Response
   {PASTE contract/turn_response.json}. Play feedback_audio_url, show feedback; if retry is true stay
   on the scene with the new challenge, else show the next scene; story_complete → Goodnight screen.
3. Dashboard → GET {API_URL}/progress/{child_id}, response {PASTE contract/progress_response.json}.
```
**H4. Polish (Sunday morning, before freeze)**
```
Polish for a demo: gentle page-turn transitions; star burst on hits; encouraging bubble on misses
(never red or "wrong"); dimmer colours and slower animations on the final scene; premium-looking
dashboard; contrast check; child buttons ≥ 64px.
```
At the end: export the code into `frontend/` in our repo.

---

## I. Tests — Kiko (with Anvay) — by 17:00
| # | Child says (JSON transcript) | Expected |
|---|---|---|
| 1 | Exactly the target word | result=hit, praise names the word, next scene |
| 2 | Target word inside a sentence ("I see the forest!") | hit, word count = 4 |
| 3 | Branch word ("boat") | goes to the boat branch |
| 4 | Silence / wrong word 3× on one scene | retry with easier level, then moves on, parent note added |
| 5 (failure) | "What's your address?" / off-topic | no personal info, redirects to the story |

## J. Adaption — Ines, stretch, remote evening
Fine-tune a small model to rewrite story narration + challenges for age 4, 5 or 6 better than the base
model. Generate a synthetic dataset with Adaption, fine-tune, submit to their leaderboard
(ranked by win rate vs base). Ask the Adaption team how evaluation works first.

## K. Submission — Kiko + Ana (Claude chat)
Write-up:
```
Write a Devpost write-up for [APP NAME] (max 400 words): inspiration, what it does, how we built it
(agent loop + tools, Claude, ElevenLabs, fal, Figma Make), how we keep children safe, challenges,
accomplishments, what's next (book archive, art styles, languages, nurseries and speech therapists).
```
2-minute video:
```
Write a 2-minute demo video script: 15s problem (a parent at bedtime), 75s demo (create avatar, one
scene, child speaks, story adapts, parent dashboard), 20s how it works, 10s impact + next steps.
Mark what is on screen for each line.
```
