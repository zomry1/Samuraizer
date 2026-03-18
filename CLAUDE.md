# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


## What this project is

Samuraizer is a personal cyber-security knowledge base. It ingests URLs (GitHub repos, CVE writeups, blog posts) and uses Gemini 2.5 Flash to produce a short summary, category, and tags. Results are stored in SQLite and exposed via a React web UI and a Telegram bot.

## Running the project

Three processes, each in its own terminal:

```bash
# Backend API (port 8000)
python server.py

# Frontend dev server (port 5173)
cd frontend && npm run dev

# Telegram bot (optional, requires TELEGRAM_BOT_TOKEN in .env)
python telegram_bot.py
```

Build the frontend for production:
```bash
cd frontend && npm run build
```

## Environment

All secrets go in `.env` at the project root:
```
GEMINI_API_KEY=...
TELEGRAM_BOT_TOKEN=...   # optional
GITHUB_TOKEN=...         # optional, raises GitHub API rate limits
SAMURAIZER_URL=http://localhost:8000  # optional, default for bot
```

## Architecture

### Data flow

1. URL submitted → `server.py /analyze` (POST, streaming NDJSON)
2. Server detects GitHub vs article, fetches content (`_fetch_github_content` / `_fetch_article_content`)
3. Content sent to Gemini 2.5 Flash with a fixed system prompt → returns `{name, bullets, category, tags}` JSON
4. Result saved to `samuraizer.db` (SQLite), streamed back to caller as NDJSON events

### Backend: `server.py` (Flask)
- Core generator: `_process_url(url)` yields `{type: "log"|"result"|"error"}` events. Uses direct SQLite connection.
- Gemini call: `_call_gemini(content)` returns JSON, uses regex fallback.
- Endpoints: `/analyze`, `/entries`, `/tags`.
- Database: `samuraizer.db` at project root.

### Frontend: `frontend/src/App.jsx` (React SPA)
- Analysis state lives in `App`.
- NDJSON stream consumed in `App.handleSubmit`.
- Tag cloud and filtering in `KnowledgeBaseTab`.
- Tailwind custom tokens in `tailwind.config.js`.

### Telegram bot: `telegram_bot.py` (python-telegram-bot v20)
- Extracts URLs from messages.
- Posts to backend `/analyze` and processes NDJSON.
- Edits status message with live log updates.
- Sends formatted cards per result.

## Key constraints
- Gemini model: always `gemini-2.5-flash`.
- `_process_url` must not use Flask `g`.
- Tag sanitization: lowercased, hyphens for spaces, non-alphanumerics stripped.
- The `functions/` directory and `firebase.json` are not used (legacy, safe to ignore).
