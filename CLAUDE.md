# CLAUDE.md

Context for any AI coding assistant (Claude Code, Cursor, etc.) working in this repo.
Read this first. If a request conflicts with anything here, say so before making changes.

## What we're building



## Team

| Person | Role | Team / branch |
|---|---|---|
| Anvay | Architecture, project management, agent loop and API | Back-end / `backend` |
| Ines | Tools, integrations, data, applied AI beyond the LLM (e.g. Adaption) | Back-end / `backend` |
| Ana | Front-end, user experience, pitch | Front-end / `frontend` |
| Kiko | Strategy, MVP scope, demo script, front-end | Front-end / `frontend` |

## Stack

- Python 3.11+, dependencies in `requirements.txt`
- LLM: Anthropic API (`anthropic`)
- Web search tool: Tavily (`tavily-python`)
- Code-execution sandbox: E2B (`e2b-code-interpreter`)
- UI: Streamlit (Lovable / Figma for design)
- Keys load from `.env` via `python-dotenv`; key names are in `.env.example`

## Architecture



## API contract (frontend <-> backend)



## Repo layout

| Path | What goes in it | Owner |
|---|---|---|
| `agent/` | Agent loop, system prompt, the `/chat` API | Back-end (Anvay, Ines) |
| `tools/` | One file per tool: the function and its description | Back-end (Anvay, Ines) |
| `data/` | Fake data the tools read (small JSON; large files via Drive) | Back-end (Anvay, Ines) |
| `tests/` | Test user inputs, rerun after every change | Back-end (Anvay, Ines) |
| `frontend/` | Streamlit screen (localhost) + the mock JSON it reads; Lovable later | Front-end (Ana, Kiko) |
| `contract/` | Example request/response JSON shared by both teams | Both, by agreement only |
| `notebooks/` | Experiments, not imported by the app | Anyone |

Only edit files in your own team's folders. Changes to `contract/` must be agreed by both teams first.

## Build order



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
