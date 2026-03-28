"""
Samuraizer – Configuration module.
Centralizes all environment variables, paths, and global constants,
plus mutable runtime state (Gemini client, embed-all progress, etc.).
"""

import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.environ.get("SAMURAIZER_DATA_DIR", BASE_DIR)
LOG_PATH = os.environ.get("SAMURAIZER_LOG_PATH", os.path.join(DATA_DIR, "samuraizer.log"))
DB_PATH = os.environ.get("SAMURAIZER_DB_PATH", os.path.join(DATA_DIR, "samuraizer.db"))
BACKUP_DIR = os.environ.get("SAMURAIZER_BACKUP_DIR", os.path.join(BASE_DIR, "db_backups"))

APP_HOST = os.environ.get("SAMURAIZER_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("SAMURAIZER_PORT", "8000"))


def _ensure_parent_dir(path: str):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


_ensure_parent_dir(LOG_PATH)
_ensure_parent_dir(DB_PATH)

# ---------------------------------------------------------------------------
# LLM provider settings (mutable — reloaded by /settings endpoint)
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:8b")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = "gemini-2.5-flash"
EMBED_MODEL = "gemini-embedding-2-preview"

OLLAMA_CHAT_OPTIONS = {
    "temperature": 0.1,
    "num_predict": 2048,
    "top_k": 50,
    "top_p": 0.95,
}
OLLAMA_ANALYZE_OPTIONS = {
    "temperature": 0.3,
    "num_predict": 5000,
    "top_k": 10,
    "top_p": 0.05,
}

# ---------------------------------------------------------------------------
# Category constants
# ---------------------------------------------------------------------------
BUILTIN_CATS = {
    "tool", "agent", "mcp", "list", "workflow",
    "cve", "article", "video", "playlist", "blog",
}

# ---------------------------------------------------------------------------
# Chat model validation sets
# ---------------------------------------------------------------------------
VALID_CHAT_MODELS_GEMINI = {
    "gemini-2.5-flash", "gemini-2.5-pro",
    "gemini-1.5-flash", "gemini-1.5-pro",
}
VALID_CHAT_MODELS_OLLAMA = {OLLAMA_MODEL}
VALID_CHAT_MODELS = VALID_CHAT_MODELS_GEMINI | VALID_CHAT_MODELS_OLLAMA

# ---------------------------------------------------------------------------
# Embedding tuning
# ---------------------------------------------------------------------------
CHUNK_SIZE = 6000      # chars per chunk
CHUNK_OVERLAP = 300    # overlap between consecutive chunks

# ---------------------------------------------------------------------------
# GitHub auth
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_HEADERS: dict = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    GITHUB_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# ---------------------------------------------------------------------------
# Transcript API
# ---------------------------------------------------------------------------
TRANSCRIPT_API_KEY = os.getenv("TRANSCRIPTAPI", "").strip()

# ---------------------------------------------------------------------------
# Gemini SDK client (mutable — rebuilt when settings change)
# ---------------------------------------------------------------------------
genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ---------------------------------------------------------------------------
# Mutable runtime state
# ---------------------------------------------------------------------------
embed_all_status = {
    "active": False,
    "done": 0,
    "total": 0,
    "failed": 0,
    "message": "",
    "updated_at": None,
}

OLLAMA_SERVE_PROCESS = None
