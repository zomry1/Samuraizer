
# Samuraizer — Cyber-Security Insight Engine

Paste a URL (GitHub repo, CVE writeup, blog post) and get a concise summary, category, and tags. Results are stored in SQLite and shown in a React web UI and Telegram bot.

## Stack

| Layer     | Tech                                 |
|-----------|--------------------------------------|
| Backend   | Python · Flask · Gemini 2.5 Flash    |
| Extraction| trafilatura (articles) · GitHub API  |
| Frontend  | React 18 · Vite · Tailwind CSS       |
| Bot       | python-telegram-bot v20 (optional)   |

---

## Setup

1. Create a `.env` file at the project root:

  ```
  GEMINI_API_KEY=your_key_here
  TELEGRAM_BOT_TOKEN=optional
  GITHUB_TOKEN=optional
  SAMURAIZER_URL=http://localhost:8000
  ```

2. Install Python dependencies:

  ```bash
  pip install -r requirements.txt
  ```

3. Install frontend dependencies:

  ```bash
  cd frontend
  npm install
  ```

4. Run the backend API:

  ```bash
  python server.py
  # Starts at http://localhost:8000
  ```

5. Run the frontend dev server:

  ```bash
  cd frontend
  npm run dev
  # Opens at http://localhost:5173
  ```

6. (Optional) Run the Telegram bot:

  ```bash
  python telegram_bot.py
  ```

---

## API

POST http://localhost:8000/analyze
Content-Type: application/json

Body:
```
{"url": "https://github.com/owner/repo"}
```

## Notes
- The functions/ directory and firebase.json are not used.
- All secrets go in .env at the project root.
- Data flow: URL → server.py/analyze → Gemini → SQLite → frontend/Telegram bot.
- Gemini model: always gemini-2.5-flash.
- Tags are sanitized before storage.

Response:
```json
{
  "summary":  "2-4 sentence plain-text description.",
  "category": "tool"
}
```
