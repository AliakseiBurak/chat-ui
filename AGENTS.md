# Ollama Chat — Agent Guide

## Run
```bash
pip install -r requirements.txt && python3 app.py
# Default: http://localhost:8080
```

## Environment
- `PORT` — server port (default `8080`)
- `OLLAMA_URL` — Ollama host (default `http://localhost:11434`)

## Key files
- `app.py` — FastAPI server, entrypoint
- `index.html` — Single-page chat UI (no framework)
- `requirements.txt` — fastapi, uvicorn, requests, python-multipart, reportlab

## Architecture
- **`POST /chat`** streams Ollama responses via SSE (`text/event-stream`). Frontend reads with `fetch` + `ReadableStream` reader, not `EventSource`. Tokens arrive as `data: {"token":"...","done":false}\n\n`. Final event has `done:true` with `model` and `elapsed_secs`.
- **`GET /models`** fetches available Ollama models.
- **`POST /export`** generates PDF from `chatHistory` via reportlab. Strips non-ASCII.
- Chat persisted in `localStorage` key `ollama-chat-history`. Arrow up/down navigates `messageHistory`.
- Markdown rendered client-side via `marked.js` (CDN).

## Logging
- Sessions: `log/sessions/{timestamp}.log` (user msg, model, reply, elapsed time)
- Errors: `log/errors/{timestamp}.log` (kind, detail)
- Both are best-effort — failures are silently caught.

## Git workflow
After making changes, show `git diff` for review. Wait for user approval before committing. Commit with `git add -A && git commit -m "message"`. Write a short summary line followed by a blank line and deeper bullet-point description when the change is non-trivial.

## Conventions
- No linter, typechecker, or test framework configured.
- `/.well-known/{path}` returns empty JSON (avoids Chrome DevTools 404 noise).
