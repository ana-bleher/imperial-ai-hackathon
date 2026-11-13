# CLAUDE.md

Context for any AI coding assistant (Claude Code, Cursor, etc.) working in this repo.
Read this first. If a request conflicts with anything here, say so before making changes.

## What we're building



## Team

| Person | Owns |
|---|---|
| Ana | Front-end, customer/user experience, pitch |
| Kiko | Strategy, MVP scope, demo script, test scenarios |
| Anvay | Architecture, project management, backend orchestration |
| Ines | Integrations, applied AI beyond the LLM (tools, data, fine-tuning) |

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

```
agent/      agent loop, system prompt, orchestration
tools/      tool functions the agent can call (one file per tool)
frontend/   UI
data/       fake / seed data (small JSON only; large files via Drive)
notebooks/  experiments, not imported by the app
```

## Build order



## Rules for AI assistants

- Make small, focused changes. One feature or fix per request.
- Only edit files in the folder relevant to the task. Ask before touching another owner's folder.
- Never read, print, create or commit `.env` or any API key. Use `os.getenv` with names from `.env.example`.
- Do not change the API contract above without flagging it explicitly.
- Do not add dependencies without saying so; if you add one, update `requirements.txt`.
- Prefer fake data in `data/` over live services until the walking skeleton works end to end.
- After a change, say how to run or test it.
- Do not run git commands (commit, push, pull, branch). Humans do that in GitHub Desktop.

## Rules for humans

- Pull before you start working.
- Commit and push small and often; commit every time something works.
- Work in your own folder where possible.
- `main` must always run: the demo deploys from it.
- Merge conflict or strange error? Ask the team; never force-push.
- When a decision is made out loud, update this file.
