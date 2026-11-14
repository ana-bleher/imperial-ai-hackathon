# Speakaboo review (Sat 14 Nov, late evening)

Four parallel read-only reviews (integration, learning & agency, design, video & pitch), merged. Nothing in the code was changed by this review. File and line numbers refer to the working copy at review time.

## 1. Top 10 actions (ranked by demo impact ÷ effort)

| # | Action | Tag | Effort | Why |
|---|---|---|---|---|
| 1 | **Fix the "three misses" freeze.** When attempts run out the backend sends `result: miss, retry: false` + the next scene; the frontend stays on the old page with the next question, and a later `scene: null` throws, so goodnight is never reached. `App.tsx` `processChallengeResponse` / `processDecisionResponse`: remove the two `result !== "hit"` stay-blocks, check `story_complete` first, never read `response.scene` when it is null. | frontend-now | 15 min | Only real crash path in the demo flow |
| 2 | **Dashboard must never show fake data as real.** `main.py` returns canned "Mia" progress with HTTP 200 for an unknown `child_id` (after any restart); the frontend then saves those fake stars/words into the child's history. Backend: 404 for unknown children. Frontend: new child ids from `Date.now()` so a new child cannot inherit an old child's saved history. | backend → Anvay + frontend-now | 10 min | Judges will open the dashboard |
| 3 | **Use Kiko's authored questions.** `fallback.enter_scene` ignores `scene["challenge"]` in story.json, so scene 1 asks a picked noun instead of "What was Pip holding…? 'lantern'". | backend → Anvay | 10 min | Makes questions fit the story |
| 4 | **Show "agent" vs "rule" in the timeline.** Each log entry already has `source`; add it to `agent_log` in `/progress`, show a small badge on the dashboard. | backend → Anvay + frontend-now | 15 min | Cheapest visible proof of agency |
| 5 | **Let the last page speak.** The frontend never asks the final "Can you whisper 'goodnight'?" (the last page only shows "The end"), so the last speaking moment and the personalised goodnight line are never heard. Ask it like any other page, then go to goodnight. Do after #1. | frontend-now | 20 min | One more speaking moment, warm ending |
| 6 | **Audio and scoring guards.** (a) A clip stopped while loading can restart in the robot voice: add `if (!LIVE_AUDIO.has(audio)) return;` at the top of `fallBack` and the retry timer. (b) "Turn page" at a question sends the target word and earns +2 stars: needs a `skip` flag on `/turn`. (c) "Child said it ✓" in demo controls sends the mock story's word to the live backend (scores a miss): don't use it live, or send the real target word. | frontend-now (a, c) + backend (b) | 15 min | Prevents odd moments on camera |
| 7 | **Polish batch.** Remove the navy overlay still painted over the paper (`.story-screen .scene-art:after`); move feet out of the faded edge (s3 y 0.88, s5a/s5b y 0.88, s4a x 0.33 y 0.72, s4b y 0.74); Pip's sleeping spots (s5a 0.555/0.565, s5b 0.82/0.58); page buttons and "Tap microphone" to 15px, min-height 44px, opacity 0.8; guide bubble text 17px; one wording "Turn the page"; night dimming on the picture only. | frontend-now | 25 min | Figma prize: coherence and readability |
| 8 | **Brand.** New mark: a crescent moon cradling Pip (SVG in the design notes below); use it as favicon and logo; tab title "Speakaboo"; only one moon on the login page; Pip's face in the guide bubble instead of the teal blob. | frontend-now | 25 min | Brand is currently four different marks |
| 9 | **Make the learning personal.** The frontend already sends `practice_words` (parent focus words + recent tricky words) with `/session/start`; the backend ignores them. Prefer them in `pick_key_word` when they occur in the story, add to `get_child_state`, one prompt line. Also: avatar traits reach fal as hex colours ("A skin"); send labels. Also: `challenge_path` can wait 15s, total turn 26s > 25s client timeout. | backend → Anvay (+ small frontend) | 30 min | "It remembered 'lantern'" is the strongest agent line |
| 10 | **Submission hygiene.** README is a two-line stub; write a real one. Clear `speakaboo-*` localStorage and restart the backend before recording. Fish in s4b is tiny but is the answer to the question. Retell question before goodnight: only after a clean recorded run. | content → Kiko / all, later | 30 min | Public repo is judged |

## 2. Is it agentic? (honest verdict)

Partly, and that is fine if described accurately. On the open speaking challenges Claude (one tool-calling response per turn, no loop) judges the answer, sets the difficulty, chooses the next step and writes the next challenge and parent note; code validates every choice and a rule takes over after 6 seconds or on invalid output. On the two authored moments (sun/moon, bridge/boat) and on first silence, rules decide and the model only words the reply; nothing persists on the server between sessions.

Say: "The story is fixed and safe; the tutor is a bounded agent that listens, judges, adapts and explains itself to the parent."
Do not say: "The agent runs the story and remembers your child between nights."

Learning today: five speaking moments per story, three of them single-word repeats; the difficulty level can rise only once. Items 3, 5 and 9 are the cheapest ways to deepen it.

Check once on the live backend: `tutor.py:78` passes `thinking={"type": "between_tools"}`. If the API rejects that, every turn silently falls back to rules. Look for `tutor fallback: agent error` in the Render logs.

## 3. Messages to send

**To Anvay (backend):**
```
From tonight's full review, backend items in priority order:
1. /progress/{child_id}: return 404 for an unknown child instead of MOCK_PROGRESS (after a restart the dashboard shows canned Mia data as if real).
2. fallback.enter_scene: when the scene has an authored "challenge" in story.json, use it as the first challenge (currently ignored, so s1 asks a picked noun).
3. Add "source" (agent / rule) to each agent_log entry in /progress; I'll show a badge.
4. /session/start already receives practice_words (parent focus words + recent tricky words, max 5): prefer them in pick_key_word when they occur in the narration, add them to get_child_state, one prompt line.
5. Please check Render logs for "tutor fallback: agent error": is thinking={"type": "between_tools"} (tutor.py:78) accepted by the API? If not, every turn is falling back to rules.
6. challenge_path can wait 15s (worst-case turn 26s vs my 25s timeout): wrap in wait_for(..., VOICE_TIMEOUT).
7. Small safety: leak-check ask.prompt like "say"; cap child_name length and restrict to letters.
8. Optional: accept {"skip": true} on /turn so "Turn the page" moves on without scoring a hit.
Details in REVIEW.md on main.
```

**To Kiko (content):**
```
From tonight's review:
1. README.md is a two-line stub and the repo goes public tomorrow: can you write a real one (what it is, how to run, architecture, tools: Claude, ElevenLabs, fal, Figma Make)?
2. s4b: the fish is the answer to the question but is tiny and faint in the picture. Either regenerate with a clear silver fish near the boat, or change the question to "paddle"/"boat".
3. s5a has a white border baked into the image, so it looks smaller than the other scenes: re-export without the border if easy.
4. Still open: watercolour Pip (awake + asleep) and the 5 pets into frontend/public/characters/.
5. The Devpost draft skeleton is in REVIEW.md, section 4.
```

## 4. Video script and pitch

**Pitch.** Speakaboo is an interactive bedtime story for children aged four to six that moves forward when the child speaks. A Claude tutor agent listens through ElevenLabs, judges each answer kindly, gives hints and adjusts the difficulty, inside watercolour scenes made with fal. Parents see what was practised and why the tutor made each decision.

**Two-minute script (about 265 words).** ★ = shots judges must see.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:11 | Title card, then login with "Big stories for little voices." | Children aged four to six learn to speak by speaking. But most bedtime screens only ask them to watch. Speakaboo is a bedtime story that waits for the child's voice. |
| 0:11–0:20 | Parent gate, build avatar, pick pet | A parent signs in, and the child builds an avatar and picks a pet. No photos, only drawings. |
| 0:20–0:29 | Bookshelf, cover, narrator audio, "Open the book" | On the cover, the narrator reads the title and says hello to Mia by name. |
| 0:29–0:40 | Scene 1: highlighted sentence, avatar, pet, Pip | Each page is a watercolour scene, read aloud in an ElevenLabs voice, with the sentence highlighted as it is spoken. |
| 0:40–0:52 | ★ "Your turn!", child says "lantern", "Pip heard you!", stars | Then Pip the firefly asks a question. Mia answers out loud. Our Claude tutor judges it, accepts a near-miss, and she earns stars. |
| 0:52–1:08 | ★ Scene 2: child says "moon", hint, mic re-opens, "sun" | Here she says moon. Nobody tells her she is wrong. Pip gives a hint, the microphone opens again, and she gets it. |
| 1:08–1:17 | Scene 3: child says "boat", page turns | Next, a real choice, made by voice: bridge or boat. The story follows her answer. |
| 1:17–1:25 | Goodnight with stars | The story ends calmly, with the stars she earned. |
| 1:25–1:41 | ★ Dashboard, scroll to "How Speakaboo helped" | Parents get their own page: stars, words practised, words that needed help, a note, and a timeline of why the tutor did each thing. |
| 1:41–1:54 | Simple architecture card | How it works: a Claude agent with five tools, checked by code limits and a six-second fallback. ElevenLabs for speech in and out. fal for the illustrations. Designed in Figma Make. Our server never stores the child's audio. |
| 1:54–2:00 | Logo and team names | Next: memory between nights, and more stories. Speakaboo: big stories for little voices. |

**Recording plan.** One continuous run, cut afterwards: (1) login, gate, avatar; (2) bookshelf, cover with full intro; (3) scene 1 "lantern"; (4) scene 2 "moon" then "sun"; (5) scene 3 "boat"; (6) scenes 4–5 and goodnight; (7) dashboard straight after the run; (8) architecture card and logo. Warm the backend with one throwaway run first. One tab, fixed window size, sound on, notifications off, headset or quiet room. Use a child name you have not used in rehearsals. Record the voice-over separately. If the backend is down the app falls back to an offline story, but the dashboard timeline needs live data: keep clip 7 from any good run.

**Devpost skeleton.**
- *Inspiration.* Young children build vocabulary by talking, yet most story apps are passive. We wanted a bedtime story that waits for the child's voice. It is speaking practice, not speech therapy.
- *What it does.* A parent sets up a child profile with a drawn avatar and a pet. The narrator reads an illustrated story aloud, Pip the firefly asks questions, and the child answers by voice. Parents get a dashboard with stars, words practised, words that needed help and the tutor's reasons.
- *How we built it.* Designed in Figma Make and exported to React. A FastAPI backend runs a Claude tutor agent (claude-sonnet-5-5) with tools to assess, set difficulty, choose the next step, ask and notify the parent. ElevenLabs Scribe transcribes and ElevenLabs speaks; fal generated the backgrounds and repaints the avatar in watercolour.
- *Challenges.* Keeping each turn fast enough for a five-year-old; making browser microphones behave; agreeing a fixed data contract between two sub-teams.
- *Accomplishments.* A full voice loop that does not stall, because every agent decision is checked by code and backed by a rule. Feedback that never tells a child they are wrong. A dashboard that explains the agent's decisions in plain words.
- *What we learned.* Give the agent the judgement calls and let code hold the limits. Build the fallback first. Children's products need safety decisions early.
- *What's next.* Memory between nights, more stories, then live story generation behind the same limits. Testing with real families.

**Likely judge questions.**
1. *Is it really agentic?* Partly: on speaking challenges the agent assesses, sets the level, picks the next step and writes the next challenge through tool calls, one model call per turn; the authored questions are decided by rules.
2. *Do you store children's voices?* No: audio is held in memory, sent to ElevenLabs for transcription and not saved; only metrics are kept.
3. *What if the model is slow or wrong?* After six seconds, or on invalid output, a rule decides, so the story carries on.
4. *Is this speech therapy?* No: it is vocabulary and speaking practice and never claims to measure pronunciation.
5. *How is it safe?* One fixed authored story, illustrations only, no personal questions, a parent gate, and the agent cannot invent scenes.

## 5. Design notes

Proposed logo mark (crescent cradling Pip), 64×64:
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><mask id="sb-moon"><rect width="64" height="64" fill="#fff"/><circle cx="39" cy="26" r="19" fill="#000"/></mask></defs>
<rect width="64" height="64" rx="16" fill="#1b2340"/>
<circle cx="30" cy="33" r="22" fill="#f2c14e" mask="url(#sb-moon)"/>
<circle cx="41" cy="29" r="9.5" fill="none" stroke="#f2c14e" stroke-width="1.5" opacity=".45"/>
<ellipse cx="35" cy="19.5" rx="5.2" ry="2.6" fill="#5fb3a8" transform="rotate(35 35 19.5)"/>
<ellipse cx="47" cy="19.5" rx="5.2" ry="2.6" fill="#5fb3a8" transform="rotate(-35 47 19.5)"/>
<circle cx="41" cy="29" r="6" fill="#fff6e5"/>
<circle cx="38.8" cy="28.2" r="1" fill="#1b2340"/><circle cx="43.2" cy="28.2" r="1" fill="#1b2340"/>
<path d="M39 31q2 1.6 4 0" fill="none" stroke="#1b2340" stroke-width="1.1" stroke-linecap="round"/></svg>
```
Readability (computed contrast): story text 14:1 (fine); guide bubble 15px (small next to 21px story text); page buttons and "Tap microphone" at 13px and opacity 0.55 are 3.5:1 in day mode (below the usual 4.5:1) and too small a target for a young child. All seven pictures match their text; only positions need the tweaks in item 7.

## 6. Pre-demo checklist
1. Commit and push everything; deploy backend and frontend at least 30 minutes before recording.
2. Fresh browser window, clear site data (localStorage), allow the microphone.
3. Warm the backend; do one full rehearsal with a different child name.
4. Quiet room or headset: in noise the mic never detects silence.
5. After the first turn, check Demo controls shows no "offline demo" badge.
6. Keep one recorded clean run as backup.
