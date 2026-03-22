# Samuraizer — Cyber‑Security Insight Engine

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/) [![React](https://img.shields.io/badge/react-v18-blueviolet)](https://reactjs.org/) [![Gemini](https://img.shields.io/badge/gemini-2.5%20Flash-orange)](https://cloud.google.com/vertex-ai)

Samuraizer ingests URLs (GitHub repos, CVE writeups, blog posts, etc.) **and PDF files**, summarizes them using *Gemini 2.5 Flash*, categorizes/tags them, and stores results in a local SQLite knowledge base.

You can interact via:
- 🌐 **Web UI** (React + Tailwind)
- 🤖 **Telegram bot** (optional)

---

## 🧩 What you get (at-a-glance)

### Knowledge Base (Web UI)
- 📝 Add any URL and get a clean summary + tags + category
- 📄 **Upload PDF files** for analysis — full text extracted and sent to Gemini; PDFs stored in the DB and viewable/downloadable from the card
- ✏️ Inline tag editing (add/remove tags on entries, feeds, and list items)
- 🔎 Semantic search (vector search using Gemini embeddings) + classic text search
- 🧩 Tag cloud + multi-filtering (by tag, category, source, list, read/useful)
- 📚 List management (groups of entries, RSS lists, manual lists)
- 👁️‍🗨️ Built-in “hover preview” (summary cards) and quick copy buttons

### RSS / Blog Feed Support
- Add RSS feeds and Samuraizer auto‑polls them periodically
- New posts are automatically ingested and summarized
- Each feed becomes its own “list”, making it easy to batch-review
- Feed items show source metadata and can be tagged/filtered like any entry

### YouTube Channel Subscriptions
- Subscribe to YouTube channels via URL (e.g. https://www.youtube.com/@handle, /channel/UCxxx)
- Preview latest videos before subscribing and select which videos to analyze
- On subscribe, selected videos are analyzed immediately; future uploads are auto-polled hourly
- Runs via `/yt-channels` API and appears in the UI under RSS/YT sections

### Telegram Bot (Optional)
- Send URLs to the bot, and it will analyze them through the same backend
- **Send a PDF file** to the bot — it downloads, analyzes, and returns a result card with a link to view the file
- Live progress updates and formatted result cards
- Works with arbitrary URLs (GitHub repos, blog posts, CVEs, etc.)

### Chat (RAG + streaming + pinned context)
- 💬 Ask questions over your knowledge base (GitHub repos, writeups, blog posts, PDFs)
- 🔗 Answers are sourced from the best matching entries (retrieval-augmented generation)
- ⚡ Streaming responses with live typing and source citations
- 🗂️ Multiple chat sessions with saved history and model selection
- 📌 **Pin specific articles** as context — type `@` to get an autocomplete dropdown, or click the `@` browse button to search and select entries
  - When entries are pinned, Gemini is constrained to answer **only** from those articles (no RAG lookup)
  - Pinned entries appear as yellow chips above the input; source cards show a 📌 badge instead of a relevance score
  - Useful for deep-diving into a specific PDF, writeup, or CVE without noise from the rest of the KB

### API + Developer Features
- Stream results from `/analyze` as NDJSON for progress updates
- Upload PDFs via `POST /analyze-pdf` (multipart) — streamed NDJSON, same shape as `/analyze`
- Retrieve stored PDF bytes via `GET /entries/<id>/pdf` (`?dl=1` for download, default inline)
- Patch entries via `PATCH /entries/<id>` to update tags, useful state, or read/useful flags
- Built-in SQLite persistence in `samuraizer.db`
- Tag sanitization ensures consistent tagging (lowercase, deduped, normalized)
- Chat endpoints: `/chat/sessions`, `/chat/sessions/<id>/messages`, `/chat` (streaming RAG)
- Pinned-context chat: `POST /chat` accepts `pinned_ids: [...]` to bypass RAG and answer exclusively from selected entries
- Entry autocomplete: `GET /entries/search?q=...` — fuzzy name/URL search, used by the `@` mention feature

---

## 🏗 Architecture (high-level)

```mermaid
flowchart LR
  Browser[Browser UI] -->|HTTP| Frontend[React Frontend]
  Frontend -->|REST/NDJSON| Backend[Flask API]
  Backend -->|SQL| SQLite[(samuraizer.db)]
  Backend -->|API| Gemini[Gemini 2.5 Flash]
  Backend -->|GitHub API| GitHub[GitHub]
  Backend -->|RSS| RSS[RSS feeds]
  Telegram[Telegram Bot] -->|HTTP| Backend
```

---

## 📸 Screenshots (placeholders)

### Web UI — Knowledge Base
![KB view placeholder](docs/screenshots/kb.png)
*Replace with a screenshot of the main knowledge base view.*

### Telegram bot (optional)
![Telegram bot placeholder](docs/screenshots/telegram.png)
*Replace with a screenshot of the bot responding to a URL.*

---

## 🧠 How it works (end-to-end)

1. **Submit a URL or PDF** via the web UI (or Telegram bot).
2. Backend determines the type (GitHub repo, blog post, RSS feed, PDF, etc.) and fetches/extracts content.
3. Content is sent to **Gemini 2.5 Flash** to generate:
   - A concise summary
   - A category and tags
   - (Optionally) embeddings used for semantic search
4. Results are stored in `samuraizer.db` and surfaced in the frontend.
5. The frontend lets you:
   - Filter by tags, category, source, list, read/useful flags
   - Edit tags inline (updates persisted via `PATCH /entries/<id>`)
   - Use semantic search (vector search over Gemini embeddings)
6. RSS feeds are polled periodically; new posts are automatically ingested.

---

## 🧰 Tech Stack

| Layer     | Tech / Libraries                      |
|-----------|----------------------------------------|
| Backend   | Python, Flask, SQLite, feedparser, PyMuPDF |
| LLM       | Gemini 2.5 Flash (Gemini API)          |
| Frontend  | React 18, Vite, Tailwind CSS           |
| Bot       | python-telegram-bot v20                |
| Transcripts | [transcriptapi.com](https://transcriptapi.com) |

---

## 📺 YouTube Transcript Fetching

### Why not `youtube-transcript-api`?

The original implementation used the open-source [`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) Python library. It works well locally but has a critical limitation in practice: **YouTube aggressively blocks IP addresses** that make automated transcript requests, especially:

- IPs belonging to cloud providers / VPS hosts (AWS, GCP, Azure, Hetzner, etc.)
- IPs that hit the transcript endpoint too frequently

This meant that after analyzing just a handful of videos, the whole server would get blocked and every subsequent transcript fetch would fail with an `IPBlocked` / `RequestBlocked` error — completely breaking YouTube video analysis.

### Current solution: `transcriptapi.com`

Samuraizer now uses [transcriptapi.com](https://transcriptapi.com) — a third-party paid API that handles the YouTube transcript fetching on their end, routing through infrastructure that isn't blocked.

**Pros:**
- No IP blocks — they manage the anti-bot problem for you
- Simple REST API (`GET /api/v2/youtube/transcript`)
- Free tier available; credits only charged on success (HTTP 200)
- Retryable error codes (408 / 503) with clear semantics

**Cons:**
- Not free beyond the free tier (credit-based billing)
- External dependency — if their service is down, transcript fetching fails
- Data goes through a third party

**Setup:** Add to `.env`:
```env
TRANSCRIPTAPI=your_key_here
```
Get a key at [transcriptapi.com/dashboard/api-keys](https://transcriptapi.com/dashboard/api-keys).

### Alternatives worth considering

| Option | How it works | IP block risk | Cost |
|--------|-------------|--------------|------|
| **[transcriptapi.com](https://transcriptapi.com)** *(current)* | Managed REST API | None (their problem) | Credit-based |
| **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** | Downloads subtitles via `--write-sub --skip-download` | Low (mimics browser) | Free, self-hosted |
| **`youtube-transcript-api` + cookies** | Pass a Netscape cookies.txt from a logged-in browser session | Medium (burner account risk) | Free |
| **YouTube Data API v3** | Official Google API, no scraping | None | Free quota, then paid |
| **[Supadata](https://supadata.ai)** | Similar managed REST API | None | Free tier (100 req/day) |

**Best free alternative:** `yt-dlp` — it is actively maintained, mimics real browser requests, and is unlikely to get blocked as quickly as a plain HTTP request. To switch, replace `_fetch_youtube_content` to shell out to `yt-dlp --write-auto-sub --sub-format vtt --skip-download` and parse the resulting `.vtt` file.

---

## ⚙️ Setup (Local)

### 1) Config 🔐
Create a `.env` in the project root:

```env
GEMINI_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=optional
GITHUB_TOKEN=optional
SAMURAIZER_URL=http://localhost:8000
TRANSCRIPTAPI=your_transcriptapi_key_here   # required for YouTube transcript fetching
```

### 2) Install dependencies 📦

```bash
pip install -r requirements.txt
cd frontend && npm install
```

### 3) Run backend ▶️

```bash
python server.py
```

### 4) Run frontend 🌐

```bash
cd frontend
npm run dev
```

### 5) (Optional) Run Telegram bot 🤖

```bash
python telegram_bot.py
```

---

## 📦 API Endpoints

### Analyze a URL
`POST /analyze`

Body:
```json
{ "url": "https://github.com/owner/repo" }
```

### Analyze a PDF
`POST /analyze-pdf`

Body: `multipart/form-data` with a `file` field containing a `.pdf` file.
Streams NDJSON events in the same shape as `/analyze` (using the filename as the `url` key).

### Retrieve a stored PDF
`GET /entries/<id>/pdf` — serves the PDF inline in the browser.
`GET /entries/<id>/pdf?dl=1` — serves the PDF as a file download.

### List entries
`GET /entries` (supports filters: `search`, `category`, `tag`, `source`, `list_id`, `read`, `useful`)

### YouTube channel subscriptions
- `GET /yt-channels` — list subscribed channels (id, channel_id, channel_url, name, last_checked)
- `POST /yt-channels/preview` — body `{ "url": "https://www.youtube.com/@handle" }`, returns channel info + latest videos (url/title/published)
- `POST /yt-channels` — body `{ "url": "...", "name": "optional", "analyze_urls": ["https://...", ...] }`; create subscription and optionally analyze selected videos
- `POST /yt-channels/<id>/poll` — immediate manual poll for a channel
- `DELETE /yt-channels/<id>` — remove subscription

### Manage tags
- Tag edits happen via `PATCH /entries/<id>` with JSON `{ "tags": ["tag1","tag2"] }`

---

## 🧠 Notes

- The `functions/` directory and `firebase.json` are legacy and not used.
- The knowledge base uses `source` values: `manual`, `rss`, and `pdf`.
- PDF files are stored as BLOBs in the `entries.pdf_data` column and deduplicated by SHA-256 hash.
- Tags are sanitized (lowercased, de-duped) before storing.
- Embeddings use **gemini-embedding-2-preview** and are stored in chunked form (`entry_chunks` table) so the full article can be searched.
- Run **Embed all entries** after initial setup or when updating the embedding model.

---

## 🙌 Contributing

1. Fork
2. Create a branch
3. Make changes
4. Submit a PR

---

## ⚖️ License
MIT
