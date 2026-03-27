# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


## What this project is

Samuraizer is a personal cyber-security knowledge base. It ingests URLs (GitHub repos, CVE writeups, blog posts) and uses an LLM (Gemini 2.5 Flash or a local Ollama model) to produce a short summary, category, and tags. Results are stored in SQLite and exposed via a React web UI and a Telegram bot.

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
LLM_PROVIDER=gemini       # "gemini" (cloud, default) or "ollama" (local)
GEMINI_API_KEY=...         # required when LLM_PROVIDER=gemini
OLLAMA_URL=http://localhost:11434  # optional, default for ollama
OLLAMA_MODEL=qwen3:14b             # optional, reasoning model
OLLAMA_EMBED_MODEL=qwen3-embedding:8b  # optional, embedding model
TELEGRAM_BOT_TOKEN=...    # optional
GITHUB_TOKEN=...           # optional, raises GitHub API rate limits
SAMURAIZER_URL=http://localhost:8000  # optional, default for bot
```

## Architecture

### Data flow

1. URL submitted → `server.py /analyze` (POST, streaming NDJSON)
2. Server detects GitHub vs article, fetches content (`_fetch_github_content` / `_fetch_article_content`)
3. Content sent to LLM (Gemini or Ollama via `_call_gemini` dispatcher) with a fixed system prompt → returns `{name, bullets, category, tags}` JSON
4. Result saved to `samuraizer.db` (SQLite), streamed back to caller as NDJSON events

### LLM provider abstraction
- `_LLM_PROVIDER` env var selects `"gemini"` (cloud) or `"ollama"` (local).
- `_call_gemini()` is the dispatcher — routes to `_call_gemini_impl()` or `_call_ollama()`.
- `_get_embedding()` dispatches to Gemini or Ollama embedding endpoints.
- `_parse_llm_json()` is a shared helper for JSON extraction/validation from any LLM response.
- Chat endpoint streams via Gemini SDK or Ollama OpenAI-compatible SSE based on provider.
- Embedding dimension migration: on startup, if chunk embedding dimensions don't match the current provider, `entry_chunks` are wiped (re-embed via `/entries/embed-all`).

### Backend: `server.py` (Flask)
- Core generator: `_process_url(url)` yields `{type: "log"|"result"|"error"}` events. Uses direct SQLite connection.
- LLM call: `_call_gemini(content)` dispatches to Gemini or Ollama, returns JSON via `_parse_llm_json`.
- Endpoints: `/analyze`, `/entries`, `/tags`, `/provider`, `/chat`.
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
- Default Gemini model: `gemini-2.5-flash`. Default Ollama model: `qwen3:14b`.
- `_process_url` must not use Flask `g`.
- Tag sanitization: lowercased, hyphens for spaces, non-alphanumerics stripped.
- The `functions/` directory and `firebase.json` are not used (legacy, safe to ignore).
