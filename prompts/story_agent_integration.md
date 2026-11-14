# Tutor prompt integration note

This prompt is aligned with the current `backend` implementation in
`agent/tutor.py`. That implementation was added after the initial prompt draft:
it now loads `prompts/story_agent.md`, makes one model call per turn, parses tool
calls, validates decisions and falls back on timeout over six seconds, errors
or invalid output. No backend code or public API changes accompany this update.

## Current runtime interface

The model returns tool calls only, in one response, without a tool-result round
trip. The registered tools are:

- `assess(result, reason)`: `hit` or `miss`; reason up to 160 characters.
- `set_difficulty(level)`: integer 1–3.
- `next_step(action, say)`: `advance`, `retry_with_hint` or `move_on`; child-facing
  text up to 160 characters and 25 words. Required on every turn.
- `ask(prompt, target_words, level)`: speaking challenge; prompt up to 160
  characters, with 1 word at level 1, 2–4 at level 2, or 3–20 at level 3.
- `notify_parent(note)`: dashboard note up to 200 characters.

`get_child_state()` is run by code and included in the message, not registered as
a model tool. The model must not emit the internal fallback decision dictionary
or a full `/turn` response.

`speaking_message()` supplies the child name/pronouns, current personalised
narration, challenge, practice history, streaks, attempt number/limit,
transcript, and eligible next speaking narration. On these turns the model
assesses, adapts and proposes a retry or transition, optionally setting the next
speaking challenge in the same response.

`authored_message()` supplies the personalised scene, question/challenge,
code-decided result and action, word to name in praise, transcript, and text code
will append. Questions, branches and first silence are evaluated by fallback
before this message. The model contributes only a warm line and optional parent
note; it must not change answers, choices, counters or levels. Code handles
authored scene entry and the initial challenge at session start.

## Remaining differences from CLAUDE.md

- **Ownership:** the brief describes agent assessment of authored questions;
  current code deliberately reserves that assessment for the authored rules.
  This prompt preserves the current interface and flags that architectural
  distinction rather than telling the model to override code decisions.
- **Feedback length:** the model's `say` is one sentence, but code appends authored
  hints/options/answers, which can make the complete feedback multiple sentences.
- **Privacy:** the tutor has an output-leak guard, but raw transcripts remain in
  session logs despite the brief's metrics-only storage requirement. Redaction
  and retention still need code enforcement.
- **Answer intent:** authored fallback rejects a quiz response mentioning both
  options and selects the first branch word mentioned. Negation and
  self-correction handling there requires a code/test change; the prompt cannot
  repair a result already decided by code.
- **Supported actions:** validation accepts `on_max_attempts: "advance"`, but
  `_question_turn()` always reveals the answer at the limit. The current story
  requests `reveal_correct_and_advance`, so that discrepancy does not affect it.
- **Endings:** the turn message does not explicitly distinguish completion from
  entry to an authored scene when next narration is absent. Add a terminal flag
  if a reliable personalised goodnight is required; do not make the model guess.
- **Voice:** voice helpers exist, but `/turn` still mocks multipart input and
  scene/feedback audio URLs remain null in `agent/main.py`.

Further optional context would include the child's age and an explicit terminal
indicator. If the model is later meant to assess authored questions, also supply
their validated decision configuration and revise the application path; merely
changing the prompt is insufficient. No new tools or structured-output schema
are needed for this tool-based integration.

Run `python -m pytest tests/test_tutor.py tests/test_fallback.py tests/test_contract.py -q`
to check current tool parsing and orchestration with mocked model calls. Those
tests do not measure live adherence to the prompt: also exercise quiz hits and
limits, both routes, unclear choices, first/repeated silence, off-topic/personal
input and endings against the configured model before demoing.
