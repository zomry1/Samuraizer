"""
Samuraizer – Cyber-Security Insight Engine
Run: python server.py
"""

import os
import re
import json
import math
import time
import shutil
import sqlite3
import hashlib
import logging
import threading
import collections
import subprocess
import requests
import trafilatura
import feedparser
import json_repair
import ollama as _ollama_mod
from urllib.parse import urlparse, urljoin
import fitz  # PyMuPDF
from scrapling import Fetcher as ScraplingFetcher
from google import genai
from google.genai import types as genai_types

from flask import Flask, request, jsonify, g, Response, stream_with_context
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("samuraizer.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
ollama_logger = logging.getLogger("ollama")
ollama_logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# In-memory log ring-buffer (exposed via GET /logs)
# ---------------------------------------------------------------------------

class _MemoryLogHandler(logging.Handler):
    """Thread-safe ring-buffer that keeps the last 2000 log records."""
    _MAX = 2000

    def __init__(self):
        super().__init__(logging.DEBUG)
        self._lock    = threading.Lock()
        self._records = collections.deque(maxlen=self._MAX)
        self._counter = 0

    def emit(self, record: logging.LogRecord):
        with self._lock:
            self._counter += 1
            self._records.append({
                "id":    self._counter,
                "ts":    time.strftime("%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "name":  record.name,
                "msg":   record.getMessage(),
            })

    def get_since(self, since: int) -> list:
        with self._lock:
            return [r for r in self._records if r["id"] > since]

    def clear(self):
        with self._lock:
            self._records.clear()
            self._counter = 0


_mem_log = _MemoryLogHandler()
logging.getLogger().addHandler(_mem_log)

# Re-embed (embed-all) progress status, to support polling from UI.
_embed_all_status = {
    "active": False,
    "done": 0,
    "total": 0,
    "failed": 0,
    "message": "",
    "updated_at": None,
}

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), "samuraizer.db")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "db_backups")


def _ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _make_db_backup(reason: str = "manual", keep: int = 10):
    """Copy the current DB to a timestamped backup file, keeping only the
    most recent *keep* backups (oldest are deleted automatically).
    """
    try:
        _ensure_backup_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(BACKUP_DIR, f"samuraizer_{ts}.db")
        shutil.copy2(DB_PATH, dest)
        logger.info("DB backup saved to %s (%s)", dest, reason)
        # Prune oldest backups beyond the keep limit
        backups = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.startswith("samuraizer_") and f.endswith(".db")]
        )
        for old in backups[:-keep]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
                logger.info("DB backup pruned: %s", old)
            except Exception as prune_exc:
                logger.warning("Could not prune old backup %s: %s", old, prune_exc)
    except Exception as exc:
        logger.error("DB backup failed (%s): %s", reason, exc)


def _start_backup_scheduler(interval_hours: int = 12):
    def loop():
        while True:
            time.sleep(interval_hours * 3600)
            _make_db_backup("interval")

    t = threading.Thread(target=loop, daemon=True)
    t.start()

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA busy_timeout=30000")
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                url        TEXT    UNIQUE NOT NULL,
                name       TEXT    NOT NULL DEFAULT '',
                bullets    TEXT    NOT NULL,
                category   TEXT    NOT NULL,
                tags       TEXT    NOT NULL DEFAULT '[]',
                content    TEXT    DEFAULT '',
                read       INTEGER DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS lists (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS list_entries (
                list_id    INTEGER NOT NULL,
                entry_id   INTEGER NOT NULL,
                added_at   TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (list_id, entry_id),
                FOREIGN KEY (list_id)  REFERENCES lists(id)   ON DELETE CASCADE,
                FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS custom_categories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                slug       TEXT UNIQUE NOT NULL,
                label      TEXT NOT NULL,
                color      TEXT NOT NULL DEFAULT '#94a3b8',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Migrations for existing DBs
        cols = [r[1] for r in db.execute("PRAGMA table_info(entries)").fetchall()]
        for col, dflt in [("name", "''"), ("tags", "'[]'"), ("content", "''"), ("embedding", "''")]:
            if col not in cols:
                db.execute(f"ALTER TABLE entries ADD COLUMN {col} TEXT NOT NULL DEFAULT {dflt}")
        if "useful" not in cols:
            db.execute("ALTER TABLE entries ADD COLUMN useful INTEGER DEFAULT 0")
        if "parent_id" not in cols:
            db.execute("ALTER TABLE entries ADD COLUMN parent_id INTEGER DEFAULT NULL")
        if "source" not in cols:
            db.execute("ALTER TABLE entries ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        if "pdf_data" not in cols:
            db.execute("ALTER TABLE entries ADD COLUMN pdf_data BLOB DEFAULT NULL")
        if "reembedded" not in cols:
            db.execute("ALTER TABLE entries ADD COLUMN reembedded INTEGER NOT NULL DEFAULT 0")

        db.execute("""
            CREATE TABLE IF NOT EXISTS entry_embedding_status (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id    INTEGER NOT NULL,
                provider    TEXT    NOT NULL,
                model       TEXT    NOT NULL,
                dimension   INTEGER NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'ready',
                updated_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(entry_id, provider, model),
                FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
            )
        """)

        # RSS feeds table
        db.execute("""
            CREATE TABLE IF NOT EXISTS rss_feeds (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url           TEXT    UNIQUE NOT NULL,
                name          TEXT    NOT NULL DEFAULT '',
                last_checked  TEXT    DEFAULT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        # YouTube channel subscriptions table
        db.execute("""
            CREATE TABLE IF NOT EXISTS yt_channels (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id    TEXT    UNIQUE NOT NULL,
                channel_url   TEXT    NOT NULL DEFAULT '',
                name          TEXT    NOT NULL DEFAULT '',
                last_checked  TEXT    DEFAULT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        # Chunked embeddings table (replaces entries.embedding for search)
        db.execute("""
            CREATE TABLE IF NOT EXISTS entry_chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id    INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                chunk_text  TEXT    NOT NULL DEFAULT '',
                embedding   TEXT    NOT NULL DEFAULT '',
                FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
            )
        """)
        # Chat sessions
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    DEFAULT NULL,
                model      TEXT    NOT NULL DEFAULT 'gemini-2.5-flash',
                created_at TEXT    DEFAULT (datetime('now')),
                updated_at TEXT    DEFAULT (datetime('now'))
            )
        """)
        # Chat messages
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role       TEXT    NOT NULL,
                text       TEXT    NOT NULL DEFAULT '',
                sources    TEXT    NOT NULL DEFAULT '[]',
                created_at TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        """)
        db.commit()


# ---------------------------------------------------------------------------
# LLM provider setup
# ---------------------------------------------------------------------------
_LLM_PROVIDER     = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
_OLLAMA_URL        = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
_OLLAMA_MODEL      = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
_OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:8b")

_OLLAMA_CHAT_OPTIONS = {
    "temperature": 0.1,
    "num_predict": 2048,
    "top_k": 50,
    "top_p": 0.95,
}
_OLLAMA_ANALYZE_OPTIONS = {
    "temperature": 0.3,
    "num_predict": 5000,
    "top_k": 10,
    "top_p": 0.05,
}

_SYSTEM_PROMPT_BASE = os.environ.get("SYSTEM_PROMPT_BASE", """You are a concise cyber-security and AI tooling analyst.
Given the raw text of a resource, respond with ONLY a valid JSON object
(no markdown fences, no extra keys) in this exact shape:

{{
  "bullets":  ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
  "category": "<exactly one of: {categories}>",
  "tags":     ["<tag1>", "<tag2>", "..."]
}}

Rules for bullets:
- Exactly 3 bullets, each under 15 words. Plain text only.
- Cover: what it is (general explanation to someone who dont know what we talk about), what it does, why it matters (one each).

Rules for tags:
- 5 to 15 tags. Lowercase, hyphenated (e.g. "use-after-free", "linux-kernel").
- Only tag what is actually discussed — do not guess or hallucinate tags.
- For CVEs always include the CVE ID as a tag (e.g. "cve-2024-1234").
- Cover as many of the following categories as the content supports:

  1. TOPIC / DOMAIN
     recon, osint, web, appsec, cloud, network, mobile, iot, active-directory,
     malware, reverse-engineering, ai-security, llm, mcp, automation,
     bug-bounty, red-team, blue-team, threat-intel, exploit-dev, pwn

  2. VULNERABILITY CLASS
     sqli, xss, rce, ssrf, lfi, xxe, idor, csrf, ssti, command-injection,
     deserialization, memory-corruption, buffer-overflow, heap-overflow,
     stack-overflow, type-confusion, race-condition, integer-overflow,
     logic-bug, format-string, path-traversal, open-redirect

  3. MEMORY PRIMITIVES (if exploit or vuln research)
     use-after-free, double-free, oob-read, oob-write, heap-spray, info-leak,
     arbitrary-read, arbitrary-write, null-deref, stack-pivot, ret2libc,
     rop, jop, tcache-poison, heap-fengshui, fake-chunk, fastbin-dup

  4. INTERNAL STRUCTURES / FUNCTIONS (exact names, lowercased + hyphenated)
     Tag notable kernel objects, syscalls, heap internals, Windows/Linux internals
     that are central to the technique. Examples:
     vtable, vptr, free-list, kmalloc, kfree, mmap, brk, slab, tcache,
     pipe-inode, inode-cache, socket-buffer, msg-queue, tls-storage,
     peb, teb, ldr-data, token-object, pool-chunk, alpc, lpc-port,
     nt-allocate-virtual-memory, nt-create-section, virtual-alloc,
     io-completion-port, object-manager, handle-table

  5. DEFENSE MECHANISMS (tag what is bypassed, exploited, or discussed)
     aslr, kaslr, dep, nx, stack-canary, pie, cfi, shadow-stack, safe-stack,
     waf, edr, av, sandbox, seccomp, apparmor, selinux, hvci, kpp, kvas,
     smep, smap, umip, pac, mte, exploit-mitigation, cfg, xfg

Category definitions — apply in STRICT priority order (first match wins):

1. cve      : a specific vulnerability advisory, CVE ID, or bug report. ALWAYS wins.

2. list     : a curated collection of links/resources. STRONG signals:
              - repo name starts with "awesome-" or contains "awesome"
              - README is mostly bullet points linking to OTHER projects/tools/resources
              - described as "curated list", "collection of", "resources for", "link roundup"
              - Examples: awesome-hacking, awesome-mcp-servers, awesome-ai-security,
                          top-bug-bounty-programs, security-resources

3. mcp      : a Model Context Protocol (MCP) server or MCP client implementation.
              - Primary purpose is providing MCP tools/resources to an AI host
              - Repo name or README explicitly mentions "MCP server", "MCP client",
                "Model Context Protocol"
              - Examples: mcp-server-github, filesystem-mcp, any "mcp-server-*" repo
              - NOT a general AI agent framework — must specifically implement MCP

4. tool     : you INSTALL and RUN it — scanner, exploit, framework, PoC, CLI utility,
              library that does security/hacking work FOR you.
              - Has install instructions (pip, npm, go install, apt, etc.)
              - Has usage/CLI examples
              - Examples: nmap, nuclei, burpsuite, sqlmap, metasploit, semgrep, amass
              - A tool that happens to USE AI is still a "tool", not "agent"

5. agent    : Claude Code extensions/slash commands, LLM/AI agent frameworks (non-MCP),
              prompt engineering guides, AI coding assistant resources, SPARC/memory agents.
              - Must be PRIMARILY about building or using AI agents / LLMs
              - Not just "uses AI" as a feature — the AI IS the product
              - Examples: claude-code-guide, SPARC methodology, prompt-injection research,
                          ai-agent-framework, llm-jailbreak-guide

6. workflow : a repeatable process, methodology, checklist, or step-by-step procedure.
              - Describes HOW to do something phase-by-phase
              - Examples: bug-bounty-methodology, pentest-checklist, red-team-playbook

7. article  : a blog post, paper, news writeup, or written analysis — typically NOT a repo.

{custom_section}Do not include any text outside the JSON object.
""")

_CHAT_SYSTEM_PROMPT = os.environ.get("CHAT_SYSTEM_PROMPT", (
    "You are a cyber-security expert assistant. "
    "Answer ONLY using the knowledge base context provided below. "
    "Cite the entry names you used. "
    "If the answer is not in the context, say so explicitly.\n\n"
    "KNOWLEDGE BASE CONTEXT:\n{context}"
))

# Gemini (only active when provider is "gemini")
_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
_MODEL_NAME = "gemini-2.5-flash"
_genai_client = genai.Client(api_key=_API_KEY) if _API_KEY else None

_SYSTEM_PROMPT_BASE = """You are a concise cyber-security and AI tooling analyst.
Given the raw text of a resource, respond with ONLY a valid JSON object
(no markdown fences, no extra keys) in this exact shape:

{{
  "bullets":  ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
  "category": "<exactly one of: {categories}>",
  "tags":     ["<tag1>", "<tag2>", "..."]
}}

Rules for bullets:
- Exactly 3 bullets, each under 15 words. Plain text only.
- Cover: what it is (general explanation to someone who dont know what we talk about), what it does, why it matters (one each).

Rules for tags:
- 5 to 15 tags. Lowercase, hyphenated (e.g. "use-after-free", "linux-kernel").
- Only tag what is actually discussed — do not guess or hallucinate tags.
- For CVEs always include the CVE ID as a tag (e.g. "cve-2024-1234").
- Cover as many of the following categories as the content supports:

  1. TOPIC / DOMAIN
     recon, osint, web, appsec, cloud, network, mobile, iot, active-directory,
     malware, reverse-engineering, ai-security, llm, mcp, automation,
     bug-bounty, red-team, blue-team, threat-intel, exploit-dev, pwn

  2. VULNERABILITY CLASS
     sqli, xss, rce, ssrf, lfi, xxe, idor, csrf, ssti, command-injection,
     deserialization, memory-corruption, buffer-overflow, heap-overflow,
     stack-overflow, type-confusion, race-condition, integer-overflow,
     logic-bug, format-string, path-traversal, open-redirect

  3. MEMORY PRIMITIVES (if exploit or vuln research)
     use-after-free, double-free, oob-read, oob-write, heap-spray, info-leak,
     arbitrary-read, arbitrary-write, null-deref, stack-pivot, ret2libc,
     rop, jop, tcache-poison, heap-fengshui, fake-chunk, fastbin-dup

  4. INTERNAL STRUCTURES / FUNCTIONS (exact names, lowercased + hyphenated)
     Tag notable kernel objects, syscalls, heap internals, Windows/Linux internals
     that are central to the technique. Examples:
     vtable, vptr, free-list, kmalloc, kfree, mmap, brk, slab, tcache,
     pipe-inode, inode-cache, socket-buffer, msg-queue, tls-storage,
     peb, teb, ldr-data, token-object, pool-chunk, alpc, lpc-port,
     nt-allocate-virtual-memory, nt-create-section, virtual-alloc,
     io-completion-port, object-manager, handle-table

  5. DEFENSE MECHANISMS (tag what is bypassed, exploited, or discussed)
     aslr, kaslr, dep, nx, stack-canary, pie, cfi, shadow-stack, safe-stack,
     waf, edr, av, sandbox, seccomp, apparmor, selinux, hvci, kpp, kvas,
     smep, smap, umip, pac, mte, exploit-mitigation, cfg, xfg

Category definitions — apply in STRICT priority order (first match wins):

1. cve      : a specific vulnerability advisory, CVE ID, or bug report. ALWAYS wins.

2. list     : a curated collection of links/resources. STRONG signals:
              - repo name starts with "awesome-" or contains "awesome"
              - README is mostly bullet points linking to OTHER projects/tools/resources
              - described as "curated list", "collection of", "resources for", "link roundup"
              - Examples: awesome-hacking, awesome-mcp-servers, awesome-ai-security,
                          top-bug-bounty-programs, security-resources

3. mcp      : a Model Context Protocol (MCP) server or MCP client implementation.
              - Primary purpose is providing MCP tools/resources to an AI host
              - Repo name or README explicitly mentions "MCP server", "MCP client",
                "Model Context Protocol"
              - Examples: mcp-server-github, filesystem-mcp, any "mcp-server-*" repo
              - NOT a general AI agent framework — must specifically implement MCP

4. tool     : you INSTALL and RUN it — scanner, exploit, framework, PoC, CLI utility,
              library that does security/hacking work FOR you.
              - Has install instructions (pip, npm, go install, apt, etc.)
              - Has usage/CLI examples
              - Examples: nmap, nuclei, burpsuite, sqlmap, metasploit, semgrep, amass
              - A tool that happens to USE AI is still a "tool", not "agent"

5. agent    : Claude Code extensions/slash commands, LLM/AI agent frameworks (non-MCP),
              prompt engineering guides, AI coding assistant resources, SPARC/memory agents.
              - Must be PRIMARILY about building or using AI agents / LLMs
              - Not just "uses AI" as a feature — the AI IS the product
              - Examples: claude-code-guide, SPARC methodology, prompt-injection research,
                          ai-agent-framework, llm-jailbreak-guide

6. workflow : a repeatable process, methodology, checklist, or step-by-step procedure.
              - Describes HOW to do something phase-by-phase
              - Examples: bug-bounty-methodology, pentest-checklist, red-team-playbook

7. article  : a blog post, paper, news writeup, or written analysis — typically NOT a repo.

{custom_section}Do not include any text outside the JSON object.
"""


def _build_system_prompt(custom_cats: list) -> str:
    builtin_cats = "tool | agent | mcp | list | workflow | cve | article | video"
    if custom_cats:
        extra = " | ".join(c["slug"] for c in custom_cats)
        categories = f"{builtin_cats} | {extra}"
        custom_lines = "\n".join(
            f"   {c['slug']:<12}: {c['label']} — user-defined category."
            for c in custom_cats
        )
        custom_section = (
            "Custom categories (user-defined — use when the content clearly fits):\n"
            f"{custom_lines}\n\n"
        )
    else:
        categories     = builtin_cats
        custom_section = ""
    return _SYSTEM_PROMPT_BASE.format(
        categories=categories,
        custom_section=custom_section,
    )

# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
_EMBED_MODEL = "gemini-embedding-2-preview"

_CHUNK_SIZE    = 6000   # chars per chunk
_CHUNK_OVERLAP = 300    # overlap between consecutive chunks


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks of ~_CHUNK_SIZE chars."""
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - _CHUNK_OVERLAP
    return chunks


def _get_embedding_gemini(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list:
    result = _genai_client.models.embed_content(
        model=_EMBED_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(task_type=task_type),
    )
    return list(result.embeddings[0].values)


# Ollama client (created lazily on first use to avoid startup errors when using Gemini)
_ollama_client: _ollama_mod.Client | None = None


def _get_ollama_client() -> _ollama_mod.Client:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = _ollama_mod.Client(host=_OLLAMA_URL)
    return _ollama_client


def _ollama_list_models() -> list[dict]:
    """Return installed Ollama models via ollama module list()."""
    client = _get_ollama_client()
    data = client.list()
    models = []

    # `ollama.Client.list()` may return a ListResponse object that behaves like ("models", [Model(...), ...]).
    if hasattr(data, "models"):
        entries = data.models or []
    elif isinstance(data, (list, tuple)) and len(data) == 2 and data[0] == "models":
        entries = data[1] or []
    else:
        # Fallback for other iterable shapes.
        try:
            entries = list(data)
        except Exception:
            entries = []

    for m in entries:
        if isinstance(m, dict):
            name = m.get("name") or m.get("model")
            size = m.get("size", None)
            status = m.get("status", "installed")
        else:
            name = getattr(m, "name", None) or getattr(m, "model", None)
            size = getattr(m, "size", None)
            status = getattr(m, "status", "installed")

        # Ollama list() shows installed models; mark accordingly when status absent.
        status = status or "installed"

        models.append({"name": name, "size": size, "status": status})

    return models


def _ollama_model_status(model_name: str) -> dict:
    """Check if a model is currently loaded in Ollama.
    Returns {"loaded": bool, "size_gb": float|None, "detail": str}."""
    try:
        models = _ollama_list_models()
        base = model_name.split(":")[0]
        for m in models:
            if m.get("name", "").startswith(base):
                size = m.get("size")
                if isinstance(size, str) and size.lower().endswith("gb"):
                    try:
                        size_gb = float(size[:-2])
                    except Exception:
                        size_gb = None
                elif isinstance(size, (int, float)):
                    size_gb = float(size) / (1024 ** 3)
                else:
                    size_gb = None
                return {"loaded": True, "size_gb": round(size_gb, 1) if size_gb is not None else None,
                        "detail": m.get("name", model_name)}
        return {"loaded": False, "size_gb": None, "detail": model_name}
    except Exception:
        return {"loaded": False, "size_gb": None, "detail": model_name}


def _ollama_pre_flight_logs() -> list[str]:
    """Return diagnostic log messages about Ollama readiness (call before the blocking LLM request)."""
    if _LLM_PROVIDER != "ollama":
        return []
    logs = []
    status = _ollama_model_status(_OLLAMA_MODEL)
    if status["loaded"]:
        logs.append(f"Ollama model {status['detail']} is loaded ({status['size_gb']} GB)")
    else:
        logs.append(
            f"Ollama model {_OLLAMA_MODEL} is not loaded \u2014 it will be loaded on first request (this may take a while)"
        )
    logs.append(f"Analyzing with Ollama ({_OLLAMA_MODEL}) \u2014 duration depends on your local hardware")
    return logs


def _get_embedding_ollama(text: str, logs: list | None = None) -> list:
    if logs is not None:
        logs.append(f"Requesting embedding from Ollama ({_OLLAMA_EMBED_MODEL})...")
    ollama_logger.debug(
        "EMBED REQUEST — model=%s, input=%d chars: %s",
        _OLLAMA_EMBED_MODEL, len(text), text[:200],
    )
    t0 = time.time()
    try:
        client = _get_ollama_client()
        data = client.embed(model=_OLLAMA_EMBED_MODEL, input=text)
    except _ollama_mod.ResponseError as e:
        ollama_logger.error("EMBED ERROR: %s", e)
        raise RuntimeError(f"Ollama embedding error: {e}") from e
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            ollama_logger.error("EMBED CONNECTION ERROR: %s", e)
            raise EnvironmentError(
                f"Cannot connect to Ollama at {_OLLAMA_URL}. "
                f"Make sure Ollama is running (ollama serve) and the required models are pulled:\n"
                f"  ollama pull {_OLLAMA_EMBED_MODEL}"
            ) from e
        raise
    elapsed = time.time() - t0
    emb = list(data.embeddings[0])
    ollama_logger.debug(
        "EMBED RESPONSE — %d dims in %.1fs",
        len(emb), elapsed,
    )
    if logs is not None:
        logs.append(f"Embedding received in {elapsed:.1f}s ({len(emb)} dims)")
    return emb


def _current_embedding_target():
    provider = _LLM_PROVIDER
    model = _OLLAMA_EMBED_MODEL if provider == "ollama" else _EMBED_MODEL
    return provider, model


def _get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list:
    if _LLM_PROVIDER == "ollama":
        return _get_embedding_ollama(text)
    return _get_embedding_gemini(text, task_type)


def _upsert_entry_embedding_status(db, entry_id: int, dim: int, status: str = "ready"):
    provider, model = _current_embedding_target()
    db.execute(
        "INSERT INTO entry_embedding_status (entry_id, provider, model, dimension, status, updated_at) "
        "VALUES (?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(entry_id, provider, model) DO UPDATE SET dimension=excluded.dimension, status=excluded.status, updated_at=excluded.updated_at",
        (entry_id, provider, model, dim, status),
    )


def _sqlite_retry(fn, retries: int = 8, delay: float = 0.15):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc).lower():
                last_exc = exc
                time.sleep(delay * (1 + attempt * 0.5))
                continue
            raise
    raise last_exc


def _store_entry_embedding(db, entry_id: int, name: str, bullets: list, tags: list,
                           content: str = "") -> None:
    """Chunk the entry content, embed each chunk, and store in entry_chunks."""
    header = f"{name}. {' '.join(bullets or [])}. {' '.join(tags or [])}."

    def work():
        _sqlite_retry(lambda: db.execute("DELETE FROM entry_chunks WHERE entry_id = ?", (entry_id,)))

        text_chunks = _chunk_text(content.strip()) if content and content.strip() else []

        if text_chunks:
            for i, chunk in enumerate(text_chunks):
                full_text = f"{header}\n{chunk}"[:8000]
                emb = _get_embedding(full_text)
                _sqlite_retry(lambda: db.execute(
                    "INSERT INTO entry_chunks (entry_id, chunk_index, chunk_text, embedding) VALUES (?,?,?,?)",
                    (entry_id, i, chunk[:3000], json.dumps(emb)),
                ))
        else:
            emb = _get_embedding(header)
            _sqlite_retry(lambda: db.execute(
                "INSERT INTO entry_chunks (entry_id, chunk_index, chunk_text, embedding) VALUES (?,?,?,?)",
                (entry_id, 0, header, json.dumps(emb)),
            ))

        _upsert_entry_embedding_status(db, entry_id, len(emb), "ready")
        _sqlite_retry(lambda: db.commit())

    work()


def _cosine_sim(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------
_GH_REPO_RE  = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?(?:/.*)?$"
)
_GH_RAW      = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
_GH_TREE     = "https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
_GH_BRANCHES = ["main", "master", "develop"]

_GH_HEADERS: dict = {"Accept": "application/vnd.github+json"}
_GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
if _GH_TOKEN:
    _GH_HEADERS["Authorization"] = f"Bearer {_GH_TOKEN}"


def _fetch_github_content(url: str) -> tuple[str, list[str]]:
    m = _GH_REPO_RE.match(url)
    owner, repo = m.group("owner"), m.group("repo")
    logs, parts = [], []
    default_branch = "main"

    logs.append(f"GitHub repo detected: {owner}/{repo}")

    for branch in _GH_BRANCHES:
        try:
            r = requests.get(_GH_RAW.format(owner=owner, repo=repo, branch=branch),
                             headers=_GH_HEADERS, timeout=15)
            if r.status_code == 200:
                parts.append(f"# README\n\n{r.text}")
                default_branch = branch
                logs.append(f"README fetched from branch '{branch}' ({len(r.text):,} chars)")
                break
        except requests.RequestException as exc:
            logs.append(f"Branch '{branch}' failed: {exc}")

    if not any("README fetched" in l for l in logs):
        logs.append("No README found — continuing with file tree only")

    try:
        r = requests.get(_GH_TREE.format(owner=owner, repo=repo, branch=default_branch),
                         headers=_GH_HEADERS, timeout=15)
        if r.status_code == 200:
            paths = [i["path"] for i in r.json().get("tree", []) if i.get("type") == "blob"]
            parts.append(f"# File Tree\n\n```\n{chr(10).join(paths[:200])}\n```")
            logs.append(f"File tree fetched ({len(paths)} files)")
        else:
            logs.append(f"File tree returned HTTP {r.status_code}")
    except Exception as exc:
        logs.append(f"File tree fetch failed: {exc}")

    if not parts:
        raise RuntimeError("No content retrieved")

    content = "\n\n---\n\n".join(parts)
    logs.append(f"Total content size: {len(content):,} chars")
    return content, logs


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------
_YT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:"
    r"youtube\.com/watch\?(?:.*&)?v=(?P<v1>[A-Za-z0-9_-]{11})"
    r"|youtu\.be/(?P<v2>[A-Za-z0-9_-]{11})"
    r"|youtube\.com/shorts/(?P<v3>[A-Za-z0-9_-]{11})"
    r")"
)
_YT_OEMBED = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"


def _extract_video_id(url: str) -> str | None:
    m = _YT_RE.search(url)
    if not m:
        return None
    return m.group("v1") or m.group("v2") or m.group("v3")


def _fetch_youtube_content(url: str) -> tuple[str, list[str], str]:
    logs = []
    video_id = _extract_video_id(url)
    if not video_id:
        raise RuntimeError("Could not extract YouTube video ID from URL")

    logs.append(f"YouTube video detected (id={video_id})")

    # Fetch title via oEmbed (free, no API key)
    title = f"YouTube video {video_id}"
    try:
        r = requests.get(_YT_OEMBED.format(video_id=video_id), timeout=10)
        if r.status_code == 200:
            data = r.json()
            title = data.get("title", title)
            author = data.get("author_name", "")
            logs.append(f"Title: \"{title}\" by {author}")
    except Exception as exc:
        logs.append(f"oEmbed fetch failed (non-fatal): {exc}")

    # Fetch transcript via transcriptapi.com (retries on 408/429/503)
    transcript_api_key = os.getenv("TRANSCRIPTAPI", "").strip()
    if not transcript_api_key:
        raise RuntimeError("TRANSCRIPTAPI key not set in .env")

    headers = {"Authorization": f"Bearer {transcript_api_key}"}
    transcript_text = None
    last_error = None
    for attempt in range(3):
        try:
            tr = requests.get(
                "https://transcriptapi.com/api/v2/youtube/transcript",
                params={"video_url": video_id, "format": "text", "include_timestamp": "false"},
                headers=headers,
                timeout=30,
            )
            if tr.status_code == 200:
                data = tr.json()
                transcript_text = data.get("transcript", "")
                logs.append(f"Transcript fetched ({len(transcript_text):,} chars)")
                break
            elif tr.status_code in (408, 503):
                wait = 2 ** attempt
                logs.append(f"Transcript API returned {tr.status_code}, retrying in {wait}s…")
                time.sleep(wait)
                last_error = f"HTTP {tr.status_code}"
            elif tr.status_code == 429:
                retry_after = int(tr.headers.get("Retry-After", 5))
                logs.append(f"Transcript API rate-limited, retrying in {retry_after}s…")
                time.sleep(retry_after)
                last_error = "rate limited"
            elif tr.status_code == 404:
                raise RuntimeError("No transcript available for this video")
            elif tr.status_code == 402:
                raise RuntimeError("Transcript API credits exhausted — top up at transcriptapi.com")
            elif tr.status_code == 401:
                raise RuntimeError("TRANSCRIPTAPI key is invalid")
            else:
                raise RuntimeError(f"Transcript API error: HTTP {tr.status_code} — {tr.text[:200]}")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Transcript API request failed: {exc}")

    if not transcript_text:
        raise RuntimeError(f"Failed to fetch transcript after 3 attempts ({last_error})")

    content = f"# {title}\n\nYouTube URL: {url}\n\n## Transcript\n\n{transcript_text}"
    logs.append(f"Total content size: {len(content):,} chars")
    return content, logs, title


_YT_PLAYLIST_RE = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?(?:.*&)?list=(?P<list>[A-Za-z0-9_-]+)"
)


def _extract_playlist_id(url: str) -> str | None:
    m = _YT_PLAYLIST_RE.search(url)
    return m.group("list") if m else None


def _fetch_article_content(url: str, return_title: bool = False):
    logs = ["Article URL detected — fetching with trafilatura"]
    t0   = time.time()

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise RuntimeError("Failed to download page")
    logs.append(f"Page downloaded in {time.time() - t0:.1f}s — extracting text")

    text = trafilatura.extract(downloaded, include_tables=True, no_fallback=False)
    if not text or len(text.strip()) < 80:
        raise RuntimeError("Extracted content too short or empty")

    logs.append(f"Text extracted ({len(text):,} chars)")
    if return_title:
        meta  = trafilatura.extract_metadata(downloaded)
        title = (meta.title or "").strip() if meta else ""
        return text, logs, title
    return text, logs


# ---------------------------------------------------------------------------
# Shared LLM JSON response parser
# ---------------------------------------------------------------------------
def _parse_llm_json(raw: str, custom_cats: list, logs: list) -> dict:
    """Extract and validate the structured JSON from an LLM response string."""
    # Strip <think>…</think> blocks (qwen3 reasoning traces)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    logs.append(f"Raw LLM response ({len(raw):,} chars): {raw[:200]}{'…' if len(raw) > 200 else ''}")

    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

    # Extract first complete JSON object via bracket counting (handles nested objects)
    start = raw.find('{')
    if start == -1:
        raise RuntimeError(f"No JSON object found in response: {raw[:200]}")
    depth = 0
    end   = start
    for i, ch in enumerate(raw[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    raw = raw[start:end + 1]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json_repair.loads(raw)
        except Exception as repair_exc:
            raise RuntimeError(f"LLM returned unparseable JSON: {repair_exc} — raw: {raw[:300]}")

    valid    = {"tool", "agent", "mcp", "list", "workflow", "cve", "article", "video", "playlist"} | {c["slug"] for c in custom_cats}
    name     = str(parsed.get("name", parsed.get("title", ""))).strip()

    # Accept alternate field names for bullets
    bullets_raw = parsed.get("bullets") or parsed.get("key_points") or parsed.get("summary") or parsed.get("highlights") or []
    if isinstance(bullets_raw, str):
        bullets_raw = [bullets_raw]
    bullets = [str(b).strip() for b in bullets_raw if str(b).strip()][:3]

    # Last resort: synthesize bullets from description field
    if not bullets:
        desc = str(parsed.get("description", parsed.get("overview", ""))).strip()
        if desc:
            bullets = [desc[:100]]
            logs.append("No 'bullets' field — synthesized from description")

    category = str(parsed.get("category", "")).strip().lower()
    # Normalize freeform categories into valid ones
    category = re.sub(r"[^a-z0-9\-]", "-", category).strip("-")
    if category == "skill":
        category = "agent"
    tags     = [
        re.sub(r"[^a-z0-9\-]", "", str(t).strip().lower().replace(" ", "-"))
        for t in parsed.get("tags", [])
        if str(t).strip()
    ]
    tags = [t for t in tags if t][:20]

    if not bullets:
        preview = json.dumps(parsed, ensure_ascii=False)[:300]
        raise RuntimeError(f"LLM returned no bullets — parsed JSON: {preview}")
    if category not in valid:
        logs.append(f"Unknown category '{category}' — defaulting to 'article'")
        category = "article"

    logs.append(f"Classified as: {category} — \"{name}\" — tags: {', '.join(tags)}")
    return {"name": name, "bullets": bullets, "category": category, "tags": tags}


def _sanitize_content(content: str, max_chars: int = 120_000) -> str:
    """Strip control chars and cap length for LLM input."""
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", content)
    # Local models need less context to stay reliable
    effective_max = 30_000 if _LLM_PROVIDER == "ollama" else max_chars
    if len(content) > effective_max:
        content = content[:effective_max] + "\n\n[content truncated]"
    return content


# ---------------------------------------------------------------------------
# Gemini call (implementation)
# ---------------------------------------------------------------------------
def _call_gemini_impl(content: str, custom_cats: list = []) -> tuple[dict, list[str]]:
    logs = []
    if not _API_KEY:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")

    logs.append(f"Sending {len(content):,} chars to {_MODEL_NAME}...")
    t0 = time.time()

    content = _sanitize_content(content)

    response = _genai_client.models.generate_content(
        model=_MODEL_NAME,
        contents=content,
        config=genai_types.GenerateContentConfig(
            system_instruction=_build_system_prompt(custom_cats),
            temperature=0.1,
            max_output_tokens=1024,
            response_mime_type="application/json",
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )

    elapsed = time.time() - t0
    raw = response.text.strip()
    logs.append(f"Gemini responded in {elapsed:.1f}s")

    result = _parse_llm_json(raw, custom_cats, logs)
    return result, logs


# ---------------------------------------------------------------------------
# JSON schema for structured Ollama output (used with format= parameter)
# ---------------------------------------------------------------------------
_OLLAMA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets":  {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string"},
        "tags":     {"type": "array", "items": {"type": "string"}},
    },
    "required": ["bullets", "category", "tags"],
}


def _extract_ollama_stats(resp) -> str:
    """Build a human-readable stats line from an Ollama ChatResponse."""
    prompt_eval_s = (resp.prompt_eval_duration or 0) / 1e9
    eval_s        = (resp.eval_duration or 0) / 1e9
    load_s        = (resp.load_duration or 0) / 1e9
    total_s       = (resp.total_duration or 0) / 1e9
    eval_count    = resp.eval_count or 0
    prompt_count  = resp.prompt_eval_count or 0
    tok_per_s     = eval_count / eval_s if eval_s > 0 else 0
    return (
        f"Ollama stats — total: {total_s:.1f}s, "
        f"load: {load_s:.1f}s, "
        f"prompt eval: {prompt_eval_s:.1f}s ({prompt_count} tokens), "
        f"generation: {eval_s:.1f}s ({eval_count} tokens, {tok_per_s:.1f} tok/s)"
    )


# ---------------------------------------------------------------------------
# Ollama call (implementation) — uses ollama module with streaming + format
# ---------------------------------------------------------------------------
def _call_ollama(content: str, custom_cats: list = [], purpose: str = "analyze") -> tuple[dict, list[str]]:
    logs = []
    t0 = time.time()

    content = _sanitize_content(content)
    if purpose == "chat":
        system_prompt = _CHAT_SYSTEM_PROMPT
        options = _OLLAMA_CHAT_OPTIONS
    else:
        # For analysis, we build the default structured prompt with category extension.
        system_prompt = _build_system_prompt(custom_cats)
        options = _OLLAMA_ANALYZE_OPTIONS

    ollama_logger.debug(
        "REQUEST — model=%s, purpose=%s, system_prompt=%d chars, content=%d chars",
        _OLLAMA_MODEL, purpose, len(system_prompt), len(content),
    )
    logs.append(f"Sending {len(content):,} chars to Ollama ({_OLLAMA_MODEL})..." )

    try:
        client = _get_ollama_client()
        stream = client.chat(
            model=_OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": content},
            ],
            stream=True,
            think=True,
            format=_OLLAMA_JSON_SCHEMA,
            options=options,
        )
    except _ollama_mod.ResponseError as e:
        raise RuntimeError(f"Ollama error: {e}") from e
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            raise EnvironmentError(
                f"Cannot connect to Ollama at {_OLLAMA_URL}. "
                f"Make sure Ollama is running (ollama serve) and the model is pulled:\n"
                f"  ollama pull {_OLLAMA_MODEL}"
            ) from e
        raise

    # ── Stream response, accumulate tokens ────────────────────────────
    chunks = []
    last_resp = None
    for chunk in stream:
        token = chunk.message.content or ""
        if token:
            chunks.append(token)
        last_resp = chunk

    raw = "".join(chunks).strip()
    elapsed = time.time() - t0

    # ── Ollama performance stats (available on the final streamed chunk) ──
    stats_line = _extract_ollama_stats(last_resp) if last_resp else f"Ollama responded in {elapsed:.1f}s"
    logs.append(f"Ollama responded in {elapsed:.1f}s ({len(raw):,} chars)")
    logs.append(stats_line)

    # ── Full debug logging ────────────────────────────────────────────
    ollama_logger.info(stats_line)
    ollama_logger.debug("RESPONSE (%d chars): %s", len(raw), raw[:2000])
    if len(raw) > 2000:
        ollama_logger.debug("RESPONSE (continued): %s", raw[2000:])

    result = _parse_llm_json(raw, custom_cats, logs)
    return result, logs


# ---------------------------------------------------------------------------
# LLM dispatcher (keeps the _call_gemini name so all call sites stay unchanged)
# ---------------------------------------------------------------------------
def _call_gemini(content: str, custom_cats: list = []) -> tuple[dict, list[str]]:
    if _LLM_PROVIDER == "ollama":
        return _call_ollama(content, custom_cats)
    return _call_gemini_impl(content, custom_cats)


# ---------------------------------------------------------------------------
# Playlist processor — generator, owns its own DB connection
# ---------------------------------------------------------------------------
def _process_playlist(url: str):
    def log(msg):
        logger.info("[%s] %s", url, msg)
        return {"type": "log", "msg": msg}

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        custom_cats = [dict(r) for r in db.execute("SELECT slug, label FROM custom_categories ORDER BY id").fetchall()]
        row = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        if row:
            yield log("Cache hit — returning saved playlist")
            children = db.execute(
                "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (row["id"],)
            ).fetchall()
            d = _row_to_dict(row, db)
            d["children"] = [_row_to_dict(c, db) for c in children]
            yield {"type": "result", "entry": d}
            return

        yield log("Playlist URL detected — fetching video list")

        try:
            from pytubefix import Playlist
            pl          = Playlist(url)
            pl_title    = pl.title
            video_urls  = list(pl.video_urls)[:50]
            yield log(f'Playlist: "{pl_title}" — {len(video_urls)} videos')
        except Exception as exc:
            yield {"type": "error", "msg": f"Failed to fetch playlist: {exc}"}
            return

        video_summaries  = []
        new_entry_ids    = []   # IDs we created fresh (will receive parent_id)

        for i, vid_url in enumerate(video_urls):
            yield log(f"[{i+1}/{len(video_urls)}] {vid_url}")
            existing = db.execute("SELECT * FROM entries WHERE url = ?", (vid_url,)).fetchone()
            if existing:
                yield log(f"  ↩ already in KB: {existing['name']}")
                video_summaries.append({
                    "name":     existing["name"],
                    "bullets":  json.loads(existing["bullets"] or "[]"),
                    "tags":     json.loads(existing["tags"] or "[]"),
                    "category": "video",
                })
                continue

            content = ""
            vid_name = f"Video {i+1}"
            try:
                content, fetch_logs = _fetch_youtube_content(vid_url)
                # Try to grab title from oEmbed for the placeholder name
                vid_id_str = _extract_video_id(vid_url)
                try:
                    r = requests.get(_YT_OEMBED.format(video_id=vid_id_str), timeout=5)
                    if r.status_code == 200:
                        vid_name = r.json().get("title", vid_name)
                except Exception:
                    pass
                for msg in fetch_logs:
                    yield log(f"  {msg}")
                for msg in _ollama_pre_flight_logs():
                    yield log(f"  {msg}")
                result, gemini_logs = _call_gemini(content, custom_cats)
                # Deterministic video name from metadata (fallback to LLM if unavailable)
                result["name"] = vid_name or result.get("name", f"Video {i+1}")
                result["category"] = "video"
                for msg in gemini_logs:
                    yield log(f"  {msg}")
                cur = db.execute(
                    "INSERT INTO entries (url, name, bullets, category, tags, content)"
                    " VALUES (?,?,?,?,?,?)",
                    (vid_url, result["name"], json.dumps(result["bullets"]),
                     "video", json.dumps(result["tags"]), content),
                )
                db.commit()
                try:
                    _store_entry_embedding(
                        db,
                        cur.lastrowid,
                        result["name"],
                        result["bullets"],
                        result["tags"],
                        content,
                    )
                    yield log("  embedding stored")
                except Exception as exc:
                    yield log(f"  embedding skipped: {exc}")
                new_entry_ids.append(cur.lastrowid)
                video_summaries.append(result)
                yield log(f"  ✓ {result['name']}")
            except Exception as exc:
                yield log(f"  ✗ {exc} — saving placeholder")
                cur = db.execute(
                    "INSERT OR IGNORE INTO entries (url, name, bullets, category, tags, content)"
                    " VALUES (?,?,?,?,?,?)",
                    (vid_url, vid_name,
                     json.dumps(["Summary could not be generated — click Retry to try again"]),
                     "video", json.dumps(["summary-failed"]), content),
                )
                db.commit()
                if cur.lastrowid:
                    new_entry_ids.append(cur.lastrowid)
                video_summaries.append({"name": vid_name, "bullets": [], "tags": []})

        if not video_summaries:
            yield {"type": "error", "msg": "No videos could be processed"}
            return

        yield log("Generating playlist summary…")
        summary_text = f"# Playlist: {pl_title}\n\n"
        for i, vs in enumerate(video_summaries):
            summary_text += f"## Video {i+1}: {vs['name']}\n"
            for b in vs["bullets"]:
                summary_text += f"- {b}\n"
            summary_text += f"Tags: {', '.join(vs['tags'])}\n\n"

        try:
            pl_result, gemini_logs = _call_gemini(summary_text, custom_cats)
            pl_result["category"] = "playlist"
            pl_result["name"]     = pl_title or url
            for msg in gemini_logs:
                yield log(msg)
        except Exception as exc:
            yield {"type": "error", "msg": f"Playlist summary failed: {exc}"}
            return

        cur = db.execute(
            "INSERT INTO entries (url, name, bullets, category, tags, content)"
            " VALUES (?,?,?,?,?,?)",
            (url, pl_result["name"], json.dumps(pl_result["bullets"]),
             "playlist", json.dumps(pl_result["tags"]), summary_text),
        )
        db.commit()
        playlist_id = cur.lastrowid

        for vid_id in new_entry_ids:
            db.execute("UPDATE entries SET parent_id = ? WHERE id = ?", (playlist_id, vid_id))
        db.commit()
        yield log(f"Playlist saved — {len(new_entry_ids)} new videos linked")

        try:
            _store_entry_embedding(
                db,
                playlist_id,
                pl_result["name"],
                pl_result["bullets"],
                pl_result["tags"],
                summary_text,
            )
            yield log("Embedding stored")
        except Exception as exc:
            yield log(f"Embedding skipped: {exc}")

        row      = db.execute("SELECT * FROM entries WHERE id = ?", (playlist_id,)).fetchone()
        children = db.execute(
            "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (playlist_id,)
        ).fetchall()
        d = _row_to_dict(row, db)
        d["children"] = [_row_to_dict(c, db) for c in children]
        yield {"type": "result", "entry": d}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Blog listing detection + scraping
# ---------------------------------------------------------------------------
_BLOG_PATH_RE = re.compile(
    r"/(blog|posts?|articles?|news|research|writings?|thoughts?|insights?)"
    r"(?:/(?:page/\d+/?)?)?$",
    re.IGNORECASE,
)
_SKIP_PATH_RE = re.compile(
    r"/(tag|author|category|categories|search|feed|rss|page/\d)",
    re.IGNORECASE,
)
_SKIP_EXT_RE  = re.compile(r"\.(pdf|zip|png|jpg|jpeg|gif|svg|ico|css|js)$", re.IGNORECASE)


def _is_blog_listing_url(url: str) -> bool:
    """Heuristic: is this URL likely a blog index/listing page?"""
    path = urlparse(url).path.rstrip("/")
    if not path or path == "":
        return False  # bare domain — too ambiguous
    return bool(_BLOG_PATH_RE.search(url))


def _extract_blog_links(base_url: str, page) -> list[dict]:
    """Extract article links from a scrapling page object.
    Returns list of {url, title} dicts where title is the anchor text."""
    base = urlparse(base_url)
    base_root = f"{base.scheme}://{base.netloc}"
    seen   = set()
    result = []

    elements = page.css("a") or []
    for a in elements:
        # scrapling Adaptor: try .attrib dict first, then .get()
        try:
            attrib = a.attrib or {}
            href = attrib.get("href") or a.get("href") or ""
        except Exception:
            continue
        href = str(href).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        # Resolve relative URLs
        if href.startswith("//"):
            href = base.scheme + ":" + href
        elif href.startswith("/"):
            href = base_root + href
        elif not href.startswith("http"):
            href = urljoin(base_url, href)
        # Same domain only
        try:
            parsed = urlparse(href)
        except Exception:
            continue
        if parsed.netloc != base.netloc:
            continue
        # Skip nav/taxonomy/files
        if _SKIP_PATH_RE.search(parsed.path):
            continue
        if _SKIP_EXT_RE.search(parsed.path):
            continue
        # Must have some slug (skip root and very short paths like /about, /cv)
        path_clean = parsed.path.strip("/")
        if len(path_clean) < 2 or "/" not in path_clean and len(path_clean) < 5:
            continue
        # Deduplicate (ignore query string + fragment)
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if clean in seen or clean == base_url.rstrip("/"):
            continue
        seen.add(clean)
        # Extract anchor text as preliminary title
        try:
            anchor = (a.text or "").strip()
            if not anchor:
                anchor = " ".join(t.strip() for t in (a.get_all_text(separator=" ") or "").split() if t.strip())
        except Exception:
            anchor = ""
        result.append({"url": clean, "title": anchor[:150]})

    return result


def _process_blog_listing(url: str, selected_urls: list | None = None, listing_title: str | None = None):
    """Generator: fetch a blog listing page, extract article links, summarise each.
    If selected_urls is provided, skip page fetch and use those URLs directly."""
    def log(msg):
        logger.info("[blog-list] %s", msg)
        return {"type": "log", "msg": msg}

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        site_host = (urlparse(url).hostname or "").replace("www.", "")
        site_name = site_host or listing_title or url
        custom_cats = [dict(r) for r in db.execute(
            "SELECT slug, label FROM custom_categories ORDER BY id"
        ).fetchall()]
        existing_parent = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        link_title_map: dict[str, str] = {}

        # Cache check (only when not given explicit selection)
        if selected_urls is None:
            if existing_parent:
                yield log("Cache hit — returning saved listing")
                yield {"type": "result", "entry": _row_to_dict(existing_parent, db)}
                return

        if selected_urls is not None:
            # User pre-selected specific articles — skip page fetch
            article_urls = selected_urls
            listing_title = listing_title or url
        else:
            yield log("Blog listing detected — fetching page…")
            try:
                page = ScraplingFetcher().get(url, timeout=20)
            except Exception as exc:
                yield {"type": "error", "msg": f"Failed to fetch listing page: {exc}"}
                return

            links = _extract_blog_links(url, page)
            if len(links) < 2:
                yield {"type": "error", "msg": "No article links detected on this page"}
                return

            article_urls = [lnk["url"] for lnk in links]
            link_title_map = {lnk["url"]: (lnk.get("title") or "").strip() for lnk in links}
            title_els = page.css("title")
            listing_title = (title_els[0].text if title_els else "") or urlparse(url).path or url

        # Prefer stable website/domain naming for the parent blog card.
        site_name = site_host or listing_title or url

        yield log(f"Analyzing {len(article_urls)} articles — '{listing_title}'")

        article_summaries = []
        new_entry_ids     = []

        for idx, art_url in enumerate(article_urls, 1):
            yield log(f"[{idx}/{len(article_urls)}] {art_url}")
            content = ""
            try:
                # Cache check for individual article
                cached = db.execute("SELECT * FROM entries WHERE url = ?", (art_url,)).fetchone()
                if cached:
                    yield log(f"  ↩ already in KB")
                    e = _row_to_dict(cached, db)
                    cached_name = (e.get("name") or "").strip()
                    link_name = link_title_map.get(art_url, "")
                    new_entry_ids.append(cached["id"])
                    article_summaries.append({
                        "name": link_name or cached_name or art_url,
                        "bullets": json.loads(cached["bullets"]) if isinstance(cached["bullets"], str) else e["bullets"],
                        "tags": json.loads(cached["tags"]) if isinstance(cached["tags"], str) else e["tags"],
                    })
                    continue

                content, fetch_logs, page_title = _fetch_article_content(art_url, return_title=True)
                for msg in fetch_logs:
                    yield log(f"  {msg}")
                for msg in _ollama_pre_flight_logs():
                    yield log(f"  {msg}")
                result, gemini_logs = _call_gemini(content, custom_cats)
                result["category"] = "article"
                # Use the real page title instead of Gemini's generated name
                if page_title:
                    result["name"] = page_title
                elif link_title_map.get(art_url):
                    result["name"] = link_title_map[art_url]
                for msg in gemini_logs:
                    yield log(f"  {msg}")
                cur = db.execute(
                    "INSERT OR IGNORE INTO entries (url, name, bullets, category, tags, content)"
                    " VALUES (?,?,?,?,?,?)",
                    (art_url, result["name"], json.dumps(result["bullets"]),
                     "article", json.dumps(result["tags"]), content),
                )
                db.commit()
                if cur.lastrowid:
                    try:
                        _store_entry_embedding(
                            db,
                            cur.lastrowid,
                            result["name"],
                            result["bullets"],
                            result["tags"],
                            content,
                        )
                        yield log("  embedding stored")
                    except Exception as exc:
                        yield log(f"  embedding skipped: {exc}")
                    new_entry_ids.append(cur.lastrowid)
                article_summaries.append(result)
                yield log(f"  ✓ {result['name']}")
            except Exception as exc:
                yield log(f"  ✗ {exc} — skipping")
                article_summaries.append({"name": art_url, "bullets": [], "tags": []})

        if not article_summaries:
            yield {"type": "error", "msg": "No articles could be processed"}
            return

        yield log("Generating listing summary…")
        summary_text = f"# Blog: {listing_title}\n\n"
        summary_text += f"Website: {site_name}\n"
        summary_text += f"URL: {url}\n\n"
        summary_text += "## Full post title list\n"
        for art in article_summaries:
            summary_text += f"- {art['name']}\n"
        summary_text += "\n"
        for i, art in enumerate(article_summaries):
            summary_text += f"## Article {i+1}: {art['name']}\n"
            for b in art["bullets"]:
                summary_text += f"- {b}\n"
            summary_text += f"Tags: {', '.join(art['tags'])}\n\n"

        try:
            list_result, gemini_logs = _call_gemini(summary_text, custom_cats)
            list_result["category"] = "blog"
            list_result["name"]     = site_name
            for msg in gemini_logs:
                yield log(msg)
        except Exception as exc:
            yield {"type": "error", "msg": f"Listing summary failed: {exc}"}
            return

        # Save parent listing entry (update existing row on re-analyze)
        if existing_parent:
            listing_id = existing_parent["id"]
            db.execute(
                "UPDATE entries SET name = ?, bullets = ?, category = ?, tags = ? WHERE id = ?",
                (
                    list_result["name"],
                    json.dumps(list_result["bullets"]),
                    "blog",
                    json.dumps(list_result["tags"]),
                    listing_id,
                ),
            )
            db.commit()
            yield log("Updated existing listing entry")
        else:
            cur = db.execute(
                "INSERT INTO entries (url, name, bullets, category, tags)"
                " VALUES (?,?,?,?,?)",
                (url, list_result["name"], json.dumps(list_result["bullets"]),
                 "blog", json.dumps(list_result["tags"])),
            )
            db.commit()
            listing_id = cur.lastrowid

        if listing_id:
            try:
                _store_entry_embedding(
                    db,
                    listing_id,
                    list_result["name"],
                    list_result["bullets"],
                    list_result["tags"],
                    summary_text,
                )
                yield log("Listing embedding stored")
            except Exception as exc:
                yield log(f"Listing embedding skipped: {exc}")

        # Link children to parent
        if listing_id and new_entry_ids:
            db.executemany(
                "UPDATE entries SET parent_id = ? WHERE id = ?",
                [(listing_id, eid) for eid in new_entry_ids],
            )
            db.commit()

        # Auto-list: find-or-create a list named after the blog and add all children
        if new_entry_ids:
            auto_list_name = site_name or listing_title or url
            auto_list_id = _get_or_create_list(db, auto_list_name)
            _add_entries_to_list(db, auto_list_id, new_entry_ids)
            yield log(f"Added {len(new_entry_ids)} articles to list '{auto_list_name}'")

        children = [_row_to_dict(r, db) for r in db.execute(
            "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (listing_id,)
        ).fetchall()] if listing_id else []

        parent_row = db.execute("SELECT * FROM entries WHERE id = ?", (listing_id,)).fetchone()
        if parent_row:
            entry = _row_to_dict(parent_row, db)
            entry["children"] = children
            yield {"type": "result", "entry": entry}
        else:
            yield {"type": "error", "msg": "Failed to save listing entry"}

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Core: process one URL — generator, owns its own DB connection
# ---------------------------------------------------------------------------
def _process_url(url: str, source: str = "manual"):
    # Playlists have their own full pipeline (cache + fetch + summarise)
    if _extract_playlist_id(url):
        yield from _process_playlist(url)
        return

    # Blog listing pages — detect heuristically, confirm by finding ≥2 article links
    if _is_blog_listing_url(url):
        yield from _process_blog_listing(url)
        return

    def log(msg):
        logger.info("[%s] %s", url, msg)
        return {"type": "log", "msg": msg}

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        custom_cats = [dict(r) for r in db.execute("SELECT slug, label FROM custom_categories ORDER BY id").fetchall()]
        row = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        if row:
            # If the cached entry lacks a name or bullets it was likely left
            # by a failed or incomplete analysis — remove it and re-analyze.
            bullets_raw = row["bullets"] or "[]"
            if not row["name"] or bullets_raw in ("", "[]"):
                db.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
                db.commit()
                yield log("Removed incomplete cached entry — re-analyzing")
            else:
                yield log("Cache hit — returning saved entry")
                yield {"type": "result", "entry": _row_to_dict(row, db)}
                return

        yield log("Starting analysis")

        deterministic_name = None
        deterministic_category = None
        try:
            if _extract_video_id(url):
                content, fetch_logs, page_title = _fetch_youtube_content(url)
                deterministic_name = page_title or url
                deterministic_category = "video"
            elif _GH_REPO_RE.match(url):
                content, fetch_logs = _fetch_github_content(url)
                gh_match = _GH_REPO_RE.match(url)
                deterministic_name = f"{gh_match.group('repo')}" if gh_match else url
            else:
                content, fetch_logs, page_title = _fetch_article_content(url, return_title=True)
                deterministic_name = page_title or url
            for msg in fetch_logs:
                yield log(msg)
        except Exception as exc:
            msg = f"Fetch failed: {exc}"
            logger.error("[%s] %s", url, msg)
            yield {"type": "error", "msg": msg}
            return

        for msg in _ollama_pre_flight_logs():
            yield log(msg)

        try:
            result, gemini_logs = _call_gemini(content, custom_cats)
            for msg in gemini_logs:
                yield log(msg)

            # Deterministic name/category override (source-based)
            if deterministic_name:
                result["name"] = deterministic_name
            if deterministic_category:
                result["category"] = deterministic_category
        except EnvironmentError as exc:
            logger.error("[%s] %s", url, exc)
            yield {"type": "error", "msg": str(exc)}
            return
        except Exception as exc:
            msg = f"LLM failed: {exc}"
            logger.error("[%s] %s", url, msg)
            yield {"type": "error", "msg": msg}
            return

        cur = db.execute(
            "INSERT INTO entries (url, name, bullets, category, tags, content, source) VALUES (?,?,?,?,?,?,?)",
            (url, result["name"], json.dumps(result["bullets"]),
             result["category"], json.dumps(result["tags"]), content, source),
        )
        db.commit()
        yield log("Saved to knowledge base")

        try:
            _store_entry_embedding(
                db,
                cur.lastrowid,
                result["name"],
                result["bullets"],
                result["tags"],
                content,
            )
            yield log("Embedding stored")
        except Exception as exc:
            yield log(f"Embedding skipped: {exc}")

        row = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        yield {"type": "result", "entry": _row_to_dict(row, db)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_dict(row, db=None) -> dict:
    list_ids = []
    if db is not None:
        le = db.execute(
            "SELECT list_id FROM list_entries WHERE entry_id = ?", (row["id"],)
        ).fetchall()
        list_ids = [r[0] for r in le]

    return {
        "id":          row["id"],
        "url":         row["url"],
        "name":        row["name"] or "",
        "bullets":     json.loads(row["bullets"]),
        "category":    row["category"],
        "tags":        json.loads(row["tags"] or "[]"),
        "list_ids":    list_ids,
        "has_content": bool(row["content"]),
        "has_pdf":     bool(row["pdf_data"]) if "pdf_data" in row.keys() else False,
        "read":        bool(row["read"]),
        "useful":      bool(row["useful"]),
        "parent_id":   row["parent_id"] if "parent_id" in row.keys() else None,
        "source":      row["source"] if "source" in row.keys() else "manual",
        "created_at":  row["created_at"],
    }


def _bulk_list_ids(db, entry_ids: list[int]) -> dict[int, list[int]]:
    """Return {entry_id: [list_id, ...]} for all given entry ids."""
    if not entry_ids:
        return {}
    placeholders = ",".join("?" * len(entry_ids))
    rows = db.execute(
        f"SELECT entry_id, list_id FROM list_entries WHERE entry_id IN ({placeholders})",  # nosec B608 – placeholders are only '?' chars, not user data
        entry_ids,
    ).fetchall()
    result: dict[int, list[int]] = {eid: [] for eid in entry_ids}
    for r in rows:
        result[r["entry_id"]].append(r["list_id"])
    return result


def _get_or_create_list(db, name: str) -> int:
    """Return the id of a list with the given name, creating it if needed."""
    row = db.execute("SELECT id FROM lists WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO lists (name) VALUES (?)", (name,))
    db.commit()
    return cur.lastrowid


def _add_entries_to_list(db, list_id: int, entry_ids: list[int]) -> None:
    """Insert entries into a list, ignoring duplicates."""
    if not entry_ids:
        return
    db.executemany(
        "INSERT OR IGNORE INTO list_entries (list_id, entry_id) VALUES (?, ?)",
        [(list_id, eid) for eid in entry_ids],
    )
    db.commit()


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------
def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract plain text from a PDF byte string (full document, no truncation)."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    parts = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "".join(parts)


def _process_pdf(file_bytes: bytes, filename: str):
    """Generator: analyse a PDF and yield log/result/error events."""
    def log(msg):
        logger.info("[pdf:%s] %s", filename, msg)
        return {"type": "log", "msg": msg}

    sha = hashlib.sha256(file_bytes).hexdigest()
    synthetic_url = f"pdf:{sha}"

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        custom_cats = [dict(r) for r in db.execute(
            "SELECT slug, label FROM custom_categories ORDER BY id"
        ).fetchall()]

        row = db.execute("SELECT * FROM entries WHERE url = ?", (synthetic_url,)).fetchone()
        if row:
            if not row["pdf_data"]:
                db.execute("UPDATE entries SET pdf_data = ? WHERE id = ?", (file_bytes, row["id"]))
                db.commit()
                yield log("Backfilled PDF data for existing entry")
                row = db.execute("SELECT * FROM entries WHERE url = ?", (synthetic_url,)).fetchone()
            else:
                yield log("Already analyzed — returning saved entry")
            yield {"type": "result", "entry": _row_to_dict(row, db)}
            return

        yield log("Extracting text from PDF")
        try:
            content = _extract_pdf_text(file_bytes)
        except Exception as exc:
            yield {"type": "error", "msg": f"PDF extraction failed: {exc}"}
            return

        if not content.strip():
            yield {"type": "error", "msg": "No extractable text — scanned/image-only PDFs are not supported"}
            return

        yield log(f"Extracted {len(content):,} characters")

        for msg in _ollama_pre_flight_logs():
            yield log(msg)

        try:
            result, gemini_logs = _call_gemini(content, custom_cats)
            for msg in gemini_logs:
                yield log(msg)
        except EnvironmentError as exc:
            logger.error("PDF analysis env error: %s", exc)
            yield {"type": "error", "msg": str(exc)}
            return
        except Exception as exc:
            yield {"type": "error", "msg": f"LLM failed: {exc}"}
            return

        deterministic_name = os.path.splitext(os.path.basename(filename))[0] if filename else "PDF"
        entry_name = deterministic_name or result.get("name", "PDF")
        entry_category = "pdf"

        cur = db.execute(
            "INSERT INTO entries (url, name, bullets, category, tags, content, source, pdf_data) VALUES (?,?,?,?,?,?,?,?)",
            (synthetic_url, entry_name, json.dumps(result["bullets"]),
             entry_category, json.dumps(result["tags"]), content, "pdf", file_bytes),
        )
        db.commit()
        yield log("Saved to knowledge base")

        try:
            _store_entry_embedding(
                db, cur.lastrowid,
                entry_name, result["bullets"], result["tags"], content,
            )
            yield log("Embedding stored")
        except Exception as exc:
            yield log(f"Embedding skipped: {exc}")

        row = db.execute("SELECT * FROM entries WHERE url = ?", (synthetic_url,)).fetchone()
        yield {"type": "result", "entry": _row_to_dict(row, db)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/analyze",                                   methods=["OPTIONS"])
@app.route("/analyze-pdf",                               methods=["OPTIONS"])
@app.route("/analyze-blog",                              methods=["OPTIONS"])
@app.route("/scan-blog",                                 methods=["OPTIONS"])
@app.route("/entries",                                   methods=["OPTIONS"])
@app.route("/entries/embed-all",                         methods=["OPTIONS"])
@app.route("/tags",                                      methods=["OPTIONS"])
@app.route("/suggest",                                   methods=["OPTIONS"])
@app.route("/search/semantic",                           methods=["OPTIONS"])
@app.route("/lists",                                     methods=["OPTIONS"])
@app.route("/lists/<int:list_id>",                       methods=["OPTIONS"])
@app.route("/lists/<int:list_id>/entries",               methods=["OPTIONS"])
@app.route("/lists/<int:list_id>/entries/<int:entry_id>",methods=["OPTIONS"])
@app.route("/entries/<int:entry_id>",                    methods=["OPTIONS"])
@app.route("/entries/<int:entry_id>/read",               methods=["OPTIONS"])
@app.route("/entries/<int:entry_id>/content",            methods=["OPTIONS"])
@app.route("/entries/<int:entry_id>/pdf",                methods=["OPTIONS"])
@app.route("/categories",                                methods=["OPTIONS"])
@app.route("/categories/<slug>",                         methods=["OPTIONS"])
@app.route("/entries/<int:entry_id>/children",           methods=["OPTIONS"])
@app.route("/entries/<int:entry_id>/retry-summary",      methods=["OPTIONS"])
def preflight(**_):
    return "", 204


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------
@app.route("/analyze", methods=["POST"])
def analyze():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON body"}), 400

    if "url" in body:
        urls = [str(body["url"]).strip()]
    elif "urls" in body:
        urls = [str(u).strip() for u in body["urls"]]
    else:
        return jsonify({"error": "Missing field: url or urls"}), 400

    urls = [u for u in urls if u.startswith(("http://", "https://"))]
    if not urls:
        return jsonify({"error": "No valid URLs"}), 400

    logger.info("Analyze request: %d URL(s)", len(urls))

    def generate():
        for url in urls:
            for event in _process_url(url):
                if event["type"] == "log":
                    yield json.dumps({"url": url, "log": event["msg"]}) + "\n"
                elif event["type"] == "result":
                    yield json.dumps({"url": url, "entry": event["entry"]}) + "\n"
                elif event["type"] == "error":
                    yield json.dumps({"url": url, "error": event["msg"]}) + "\n"

    return app.response_class(generate(), mimetype="application/x-ndjson")


@app.route("/analyze-pdf", methods=["POST"])
def analyze_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a .pdf"}), 400
    filename = f.filename
    file_bytes = f.read()
    logger.info("Analyze-PDF request: %s (%d bytes)", filename, len(file_bytes))

    def generate():
        for event in _process_pdf(file_bytes, filename):
            if event["type"] == "log":
                yield json.dumps({"url": filename, "log": event["msg"]}) + "\n"
            elif event["type"] == "result":
                yield json.dumps({"url": filename, "entry": event["entry"]}) + "\n"
            elif event["type"] == "error":
                yield json.dumps({"url": filename, "error": event["msg"]}) + "\n"

    return app.response_class(stream_with_context(generate()), mimetype="application/x-ndjson")


@app.route("/entries/<int:entry_id>/pdf", methods=["GET", "OPTIONS"])
def download_pdf(entry_id):
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("SELECT url, name, pdf_data FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        if not row["pdf_data"]:
            return jsonify({"error": "No PDF stored for this entry"}), 404
        filename = (row["name"] or f"entry-{entry_id}").replace("/", "_") + ".pdf"
        # HTTP headers must be latin-1 safe; strip any characters outside that range
        filename = filename.encode("latin-1", "replace").decode("latin-1")
        disposition = "attachment" if request.args.get("dl") else "inline"
        return Response(
            bytes(row["pdf_data"]),
            mimetype="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        )
    finally:
        db.close()


@app.route("/scan-blog", methods=["POST"])
def scan_blog():
    """Fast scan: fetch a blog listing page and return all discovered article links."""
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON body"}), 400
    url = str(body.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Missing or invalid url"}), 400
    try:
        page = ScraplingFetcher().get(url, timeout=20)
        links = _extract_blog_links(url, page)
        title_els = page.css("title")
        blog_title = (title_els[0].text if title_els else "") or url
        return jsonify({"title": blog_title, "links": links})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/analyze-blog", methods=["POST"])
def analyze_blog():
    """Directly process a URL as a blog listing — bypasses URL heuristics.
    Accepts optional selected_urls list to analyze only specific articles."""
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON body"}), 400
    url = str(body.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Missing or invalid url"}), 400

    selected_urls  = body.get("selected_urls")   # list[str] | None
    listing_title  = body.get("listing_title")   # str | None

    logger.info("Analyze-blog request: %s (%s articles selected)",
                url, len(selected_urls) if selected_urls else "all")

    def generate():
        for event in _process_blog_listing(url, selected_urls=selected_urls, listing_title=listing_title):
            if event["type"] == "log":
                yield json.dumps({"url": url, "log": event["msg"]}) + "\n"
            elif event["type"] == "result":
                yield json.dumps({"url": url, "entry": event["entry"]}) + "\n"
            elif event["type"] == "error":
                yield json.dumps({"url": url, "error": event["msg"]}) + "\n"

    return app.response_class(generate(), mimetype="application/x-ndjson")


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
@app.route("/entries", methods=["GET"])
def list_entries():
    search      = request.args.get("search",   "").strip()
    category    = request.args.get("category", "").strip().lower()
    tag         = request.args.get("tag",      "").strip().lower()
    list_id     = request.args.get("list_id",  "").strip()
    read_filter = request.args.get("read",     "").strip()
    useful_only = request.args.get("useful",   "").strip()
    source_filter = request.args.get("source", "").strip().lower()

    db = get_db()
    query, params = "SELECT * FROM entries WHERE parent_id IS NULL", []

    if source_filter in ("manual", "rss"):
        query += " AND source = ?"
        params.append(source_filter)

    if category and category != "all":
        query += " AND category = ?"
        params.append(category)

    if tag:
        query += ' AND (tags LIKE ? OR id IN (SELECT parent_id FROM entries WHERE parent_id IS NOT NULL AND tags LIKE ?))'
        params.extend([f'%"{tag}"%', f'%"{tag}"%'])

    if list_id:
        query += " AND id IN (SELECT entry_id FROM list_entries WHERE list_id = ?)"
        params.append(int(list_id))

    if read_filter in ("0", "1"):
        query += " AND read = ?"
        params.append(int(read_filter))

    if useful_only == "1":
        query += " AND useful = 1"

    if search:
        query += (" AND (url LIKE ? OR name LIKE ? OR bullets LIKE ? OR tags LIKE ?"
                  " OR id IN (SELECT parent_id FROM entries WHERE parent_id IS NOT NULL"
                  " AND (url LIKE ? OR name LIKE ? OR bullets LIKE ? OR tags LIKE ?)))")
        params.extend([f"%{search}%"] * 8)

    query += " ORDER BY created_at DESC"
    rows = db.execute(query, params).fetchall()

    entry_ids = [r["id"] for r in rows]
    list_map  = _bulk_list_ids(db, entry_ids)

    # Build matched_child_ids so the frontend can auto-open and filter children
    matched_child_map: dict[int, list[int]] = {}
    if tag or search:
        parent_ids = [r["id"] for r in rows if r["category"] in ("playlist", "list", "blog")]
        if parent_ids:
            ph  = ",".join("?" * len(parent_ids))
            cq  = f"SELECT id, parent_id FROM entries WHERE parent_id IN ({ph})"  # nosec B608 – ph contains only '?' placeholders
            cp  = list(parent_ids)
            if tag:
                cq += " AND tags LIKE ?"
                cp.append(f'%"{tag}"%')
            if search:
                cq += " AND (url LIKE ? OR name LIKE ? OR bullets LIKE ? OR tags LIKE ?)"
                cp.extend([f"%{search}%"] * 4)
            for c in db.execute(cq, cp).fetchall():
                matched_child_map.setdefault(c["parent_id"], []).append(c["id"])

    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["list_ids"] = list_map.get(r["id"], [])
        if r["category"] in ("playlist", "list", "blog"):
            d["matched_child_ids"] = matched_child_map.get(r["id"], [])
        result.append(d)
    return jsonify(result), 200


@app.route("/entries/<int:entry_id>/read", methods=["PATCH"])
def toggle_read(entry_id):
    db  = get_db()
    row = db.execute("SELECT read FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    new_read = 0 if row["read"] else 1
    db.execute("UPDATE entries SET read = ? WHERE id = ?", (new_read, entry_id))
    db.commit()
    return jsonify({"id": entry_id, "read": bool(new_read)}), 200


@app.route("/entries/<int:entry_id>", methods=["PATCH"])
def update_entry(entry_id):
    body = request.get_json(silent=True) or {}
    db   = get_db()
    row  = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    custom_slugs = {r["slug"] for r in db.execute("SELECT slug FROM custom_categories").fetchall()}
    valid_cats = _BUILTIN_CATS | custom_slugs
    updates    = {}
    if "name" in body:
        name = str(body["name"]).strip()
        if not name:
            return jsonify({"error": "Name cannot be empty"}), 400
        updates["name"] = name
    if "category" in body:
        cat = str(body["category"]).strip().lower()
        if cat not in valid_cats:
            return jsonify({"error": f"Invalid category: {cat}"}), 400
        updates["category"] = cat
    if "useful" in body:
        updates["useful"] = 1 if body["useful"] else 0
    if "tags" in body:
        tags = body.get("tags") or []
        if not isinstance(tags, list):
            return jsonify({"error": "Tags must be a list"}), 400
        tags = [str(t).strip() for t in tags if str(t).strip()]
        tags = sorted(set(tags))
        updates["tags"] = json.dumps(tags)
    if not updates:
        return jsonify({"error": "Nothing to update"}), 400
    _ALLOWED_PATCH_COLS = {"name", "category", "useful", "tags", "read"}
    if not all(k in _ALLOWED_PATCH_COLS for k in updates):
        return jsonify({"error": "Invalid field in update"}), 400
    set_clause = ", ".join(f"{k} = ?" for k in updates)  # nosec B608 – keys validated against allowlist above
    db.execute(f"UPDATE entries SET {set_clause} WHERE id = ?", [*updates.values(), entry_id])  # nosec B608
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return jsonify(_row_to_dict(row, db)), 200


@app.route("/entries/<int:entry_id>", methods=["DELETE"])
def delete_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM entries WHERE parent_id = ?", (entry_id,))
    db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    db.commit()
    return "", 204


@app.route("/entries/<int:entry_id>/content", methods=["GET"])
def get_content(entry_id):
    row = get_db().execute(
        "SELECT content FROM entries WHERE id = ?", (entry_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"content": row["content"] or ""}), 200


@app.route("/entries/<int:entry_id>/retry-summary", methods=["POST"])
def retry_summary(entry_id):
    db  = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    content = row["content"] or ""
    if not content.strip():
        return jsonify({"error": "No content stored — cannot retry"}), 400
    custom_cats = [dict(r) for r in db.execute("SELECT slug, label FROM custom_categories ORDER BY id").fetchall()]
    try:
        result, _ = _call_gemini(content, custom_cats)
        result["category"] = "video"
        tags = [t for t in result["tags"] if t != "summary-failed"]
        db.execute(
            "UPDATE entries SET name=?, bullets=?, category=?, tags=? WHERE id=?",
            (result["name"], json.dumps(result["bullets"]), "video",
             json.dumps(tags), entry_id),
        )
        db.commit()
        try:
            _store_entry_embedding(
                db,
                entry_id,
                result["name"],
                result["bullets"],
                tags,
                content,
            )
        except Exception as exc:
            logger.error("Retry embed failed for %d: %s", entry_id, exc)
        row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return jsonify(_row_to_dict(row, db)), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/entries/<int:entry_id>/children", methods=["GET"])
def get_children(entry_id):
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (entry_id,)
    ).fetchall()
    return jsonify([_row_to_dict(r, db) for r in rows]), 200


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
@app.route("/tags", methods=["GET"])
def list_tags():
    rows = get_db().execute("SELECT tags FROM entries").fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        for tag in json.loads(row["tags"] or "[]"):
            counts[tag] = counts.get(tag, 0) + 1
    return jsonify([{"tag": t, "count": c}
                    for t, c in sorted(counts.items(), key=lambda x: -x[1])]), 200


# ---------------------------------------------------------------------------
# Suggest
# ---------------------------------------------------------------------------
@app.route("/suggest", methods=["GET"])
def suggest():
    """Return one random unread entry. Returns null if all read."""
    exclude = request.args.get("exclude", "")
    db  = get_db()
    q   = "SELECT * FROM entries WHERE read = 0 AND source = 'manual'"
    params: list = []
    if exclude:
        q += " AND id != ?"
        params.append(int(exclude))
    q  += " ORDER BY RANDOM() LIMIT 1"
    row = db.execute(q, params).fetchone()
    if not row:
        return jsonify(None), 200
    d = _row_to_dict(row, db)
    # Include a short content preview (first 400 chars)
    if row["content"]:
        d["preview"] = row["content"][:400].strip()
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------
@app.route("/search/semantic", methods=["GET"])
def semantic_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([]), 200
    if _LLM_PROVIDER == "gemini" and not _API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500
    logger.info("Semantic search: %r", q)
    try:
        query_emb = _get_embedding(q, task_type="RETRIEVAL_QUERY")
    except Exception as exc:
        logger.error("Embed query failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    db     = get_db()
    chunks = db.execute("SELECT entry_id, embedding FROM entry_chunks").fetchall()
    if not chunks:
        return jsonify([]), 200

    # Best cosine score per entry across all its chunks
    entry_scores: dict = {}
    for chunk in chunks:
        try:
            emb = json.loads(chunk["embedding"])
            sim = _cosine_sim(query_emb, emb)
            eid = chunk["entry_id"]
            if sim > entry_scores.get(eid, 0):
                entry_scores[eid] = sim
        except Exception:
            continue

    top_pairs = sorted(
        [(eid, s) for eid, s in entry_scores.items() if s > 0.25],
        key=lambda x: -x[1],
    )[:20]
    if not top_pairs:
        return jsonify([]), 200

    top_ids   = [eid for eid, _ in top_pairs]
    score_map = {eid: s for eid, s in top_pairs}
    ph        = ",".join("?" * len(top_ids))
    rows      = db.execute(f"SELECT * FROM entries WHERE id IN ({ph})", top_ids).fetchall()  # nosec B608 – ph contains only '?' placeholders
    entry_map = {r["id"]: r for r in rows}
    list_map  = _bulk_list_ids(db, top_ids)

    results = []
    for eid in top_ids:
        row = entry_map.get(eid)
        if not row:
            continue
        d             = _row_to_dict(row)
        d["list_ids"] = list_map.get(eid, [])
        d["score"]    = round(score_map[eid], 3)
        results.append(d)

    logger.info("Semantic search %r → %d results", q, len(results))
    return jsonify(results), 200


def _fetch_embedding_health():
    """Check embedding status using the entry_embedding_status table.

    Returns a dict with counts of embedded/missing entries for the current
    provider+model.  No LLM API calls are made — everything comes from the DB.
    """
    db = get_db()
    provider, model = _current_embedding_target()

    total_entries = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    if total_entries == 0:
        return {
            "ok": True,
            "total": 0,
            "embedded": 0,
            "mismatched": 0,
            "missing": 0,
            "missing_ids": [],
            "mismatch_ids": [],
            "provider": provider,
            "model": model,
        }

    # Entries that are ready for the *current* provider+model
    ready_rows = db.execute(
        "SELECT entry_id FROM entry_embedding_status "
        "WHERE provider = ? AND model = ? AND status = 'ready'",
        (provider, model),
    ).fetchall()
    ready_ids = set(r[0] for r in ready_rows)

    # All entry IDs
    all_ids = set(
        r[0] for r in db.execute("SELECT id FROM entries").fetchall()
    )

    # Missing = entries without a ready embedding for the current model
    missing_ids = sorted(all_ids - ready_ids)

    embedded = len(ready_ids)
    missing = len(missing_ids)
    ok = missing == 0

    return {
        "ok": ok,
        "total": total_entries,
        "embedded": embedded,
        "mismatched": 0,
        "missing": missing,
        "missing_ids": missing_ids,
        "mismatch_ids": [],
        "provider": provider,
        "model": model,
    }


@app.route("/embeddings/status")
def embeddings_status():
    try:
        data = _fetch_embedding_health()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(data), 200


def _embed_all_runner(all_mode=False):
    global _embed_all_status
    if _LLM_PROVIDER == "gemini" and not _API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500

    db = get_db()

    _embed_all_status = {
        "active": True,
        "done": 0,
        "total": 0,
        "failed": 0,
        "message": "Starting re-embed",
        "updated_at": time.time(),
    }

    # DB consistency check before starting long-running re-embed
    try:
        check = db.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != 'ok':
            _embed_all_status.update({
                "active": False,
                "message": f"Database integrity check failed: {check}",
                "updated_at": time.time(),
            })
            return jsonify({"error": "Database integrity check failed. Please restore from backup."}), 500
    except sqlite3.OperationalError as exc:
        if "database is locked" in str(exc).lower():
            _embed_all_status.update({
                "active": False,
                "message": f"Database is locked: {exc}",
                "updated_at": time.time(),
            })
            return jsonify({"error": "Database is locked. Please retry in a moment."}), 503
        _embed_all_status.update({
            "active": False,
            "message": f"Database unreadable: {exc}",
            "updated_at": time.time(),
        })
        return jsonify({"error": f"Database is malformed: {exc}. Try restoring from backup."}), 500
    except sqlite3.DatabaseError as exc:
        _embed_all_status.update({
            "active": False,
            "message": f"Database unreadable: {exc}",
            "updated_at": time.time(),
        })
        return jsonify({"error": f"Database is malformed: {exc}. Try restoring from backup."}), 500

    if all_mode:
        # Full wipe: clear ALL chunks and status, then re-embed everything
        db.execute("DELETE FROM entry_chunks")
        db.execute("DELETE FROM entry_embedding_status")
        db.commit()
        logger.info("embed-all: wiped entry_chunks and entry_embedding_status for full rebuild")
        rows = db.execute("SELECT * FROM entries").fetchall()
    else:
        # Targeted: only entries missing embeddings for the current model
        health = _fetch_embedding_health()
        missing_ids = health["missing_ids"]
        if missing_ids:
            placeholders = ",".join(["?"] * len(missing_ids))
            sql = "SELECT * FROM entries WHERE id IN (" + placeholders + ")"  # nosec B608
            rows = db.execute(sql, missing_ids).fetchall()
        else:
            rows = []

    total = len(rows)
    provider, model = _current_embedding_target()
    if all_mode:
        logger.info("embed-all: %d entries to embed (full re-embed for %s/%s)", total, provider, model)
        _embed_all_status["message"] = f"Full re-embed for {provider}/{model}"
    else:
        logger.info("embed-all: %d entries need embedding for %s/%s", total, provider, model)
        _embed_all_status["message"] = f"{total} entries to embed for {provider}/{model}"

    rows_data = [dict(r) for r in rows]
    _embed_all_status.update({"total": total, "updated_at": time.time()})

    def generate():
        sdb = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        sdb.row_factory = sqlite3.Row
        sdb.execute("PRAGMA journal_mode=WAL")
        sdb.execute("PRAGMA busy_timeout=30000")
        done, failed = 0, 0

        try:
            for row in rows_data:
                model_name = row.get("name") or ""
                try:
                    bullets = json.loads(row.get("bullets") or "[]")
                    tags = json.loads(row.get("tags") or "[]")
                    content = row.get("content") or ""
                    _store_entry_embedding(sdb, row["id"], model_name, bullets, tags, content)
                    _sqlite_retry(lambda: sdb.commit())
                    done += 1
                except sqlite3.OperationalError as exc:
                    if "database is locked" in str(exc).lower():
                        logger.warning("embed-all row %d locked, retrying: %s", row.get("id"), exc)
                        time.sleep(1)
                        continue
                    logger.error("embed-all row %d DB error: %s", row.get("id"), exc)
                    _embed_all_status.update({
                        "active": False,
                        "message": f"Database error: {exc}",
                        "updated_at": time.time(),
                    })
                    yield json.dumps({"type": "error", "message": f"Database error: {exc}"}) + "\n"
                    return
                except sqlite3.DatabaseError as exc:
                    logger.error("embed-all row %d DB error: %s", row.get("id"), exc)
                    _embed_all_status.update({
                        "active": False,
                        "message": f"Database error: {exc}",
                        "updated_at": time.time(),
                    })
                    yield json.dumps({"type": "error", "message": f"Database error: {exc}"}) + "\n"
                    return
                except Exception as exc:
                    logger.error("embed-all row %d: %s", row.get("id"), exc)
                    failed += 1
                _embed_all_status.update({
                    "done": done,
                    "failed": failed,
                    "message": f"Re-embedding {done}/{total} (failed {failed})",
                    "updated_at": time.time(),
                })
                yield json.dumps({"type": "progress", "done": done, "failed": failed, "total": total, "name": model_name}) + "\n"

            logger.info("embed-all: done=%d failed=%d", done, failed)
            _embed_all_status.update({
                "active": False,
                "done": done,
                "failed": failed,
                "message": "Re-embedding complete",
                "updated_at": time.time(),
            })
            yield json.dumps({"type": "complete", "done": done, "failed": failed, "total": total}) + "\n"
        finally:
            sdb.close()

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@app.route("/entries/embed-all", methods=["POST"])
def embed_all():
    all_mode = request.args.get("all", "false").lower() in ("1", "true", "yes")
    return _embed_all_runner(all_mode)


@app.route("/entries/embed-required", methods=["POST"])
def embed_required():
    return _embed_all_runner(False)


@app.route("/entries/embed-all/status", methods=["GET"])
def embed_all_status():
    global _embed_all_status
    return jsonify(_embed_all_status), 200


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------
@app.route("/lists", methods=["GET"])
def get_lists():
    db   = get_db()
    rows = db.execute("""
        SELECT l.id, l.name, l.created_at,
               COUNT(le.entry_id) as entry_count
        FROM lists l
        LEFT JOIN list_entries le ON le.list_id = l.id
        GROUP BY l.id ORDER BY l.created_at DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/lists", methods=["POST"])
def create_list():
    body = request.get_json(silent=True)
    name = (body or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO lists (name) VALUES (?)", (name,))
    db.commit()
    row = db.execute("SELECT * FROM lists WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({**dict(row), "entry_count": 0}), 201


@app.route("/lists/<int:list_id>", methods=["PATCH"])
def rename_list(list_id):
    body = request.get_json(silent=True)
    name = (body or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    db = get_db()
    db.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id))
    db.commit()
    return jsonify({"id": list_id, "name": name}), 200


@app.route("/lists/<int:list_id>", methods=["DELETE"])
def delete_list(list_id):
    db = get_db()
    db.execute("DELETE FROM lists WHERE id = ?", (list_id,))
    db.commit()
    return "", 204


@app.route("/lists/<int:list_id>/entries", methods=["POST"])
def add_to_list(list_id):
    body     = request.get_json(silent=True)
    entry_id = (body or {}).get("entry_id")
    if not entry_id:
        return jsonify({"error": "entry_id required"}), 400
    db = get_db()
    try:
        db.execute(
            "INSERT OR IGNORE INTO list_entries (list_id, entry_id) VALUES (?,?)",
            (list_id, int(entry_id)),
        )
        db.commit()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return "", 201


@app.route("/lists/<int:list_id>/entries/<int:entry_id>", methods=["DELETE"])
def remove_from_list(list_id, entry_id):
    db = get_db()
    db.execute(
        "DELETE FROM list_entries WHERE list_id = ? AND entry_id = ?",
        (list_id, entry_id),
    )
    db.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Custom Categories
# ---------------------------------------------------------------------------
_BUILTIN_CATS = {"tool", "agent", "mcp", "list", "workflow", "cve", "article", "video", "playlist", "blog"}


@app.route("/categories", methods=["GET"])
def get_categories():
    rows = get_db().execute("SELECT * FROM custom_categories ORDER BY created_at").fetchall()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/categories", methods=["POST"])
def create_category():
    body  = request.get_json(silent=True) or {}
    label = body.get("label", "").strip()
    color = body.get("color", "#94a3b8").strip()
    if not label:
        return jsonify({"error": "label required"}), 400
    slug = re.sub(r"[^a-z0-9\-]", "", label.lower().replace(" ", "-"))
    if not slug:
        return jsonify({"error": "invalid label"}), 400
    if slug in _BUILTIN_CATS:
        return jsonify({"error": f"'{slug}' is a built-in category"}), 400
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO custom_categories (slug, label, color) VALUES (?,?,?)",
            (slug, label, color),
        )
        db.commit()
        row = db.execute("SELECT * FROM custom_categories WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/categories/<slug>", methods=["DELETE"])
def delete_category(slug):
    db = get_db()
    db.execute("DELETE FROM custom_categories WHERE slug = ?", (slug,))
    db.commit()
    return "", 204


# ---------------------------------------------------------------------------
# RSS Feed Polling
# ---------------------------------------------------------------------------

def _poll_rss_feed(db, feed_id: int, feed_url: str) -> int:
    """Fetch and parse one RSS/Atom feed; analyse new entries. Returns count added."""
    try:
        parsed = feedparser.parse(feed_url)
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", feed_url, exc)
        return 0

    # Determine the list name from the feed title or its stored name
    feed_row = db.execute("SELECT name FROM rss_feeds WHERE id = ?", (feed_id,)).fetchone()
    feed_title = (feed_row["name"] if feed_row and feed_row["name"] else "") or \
                 getattr(getattr(parsed, "feed", None), "title", "") or feed_url
    auto_list_id = _get_or_create_list(db, feed_title)

    added = 0
    new_ids = []
    for item in parsed.entries:
        url = item.get("link", "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        existing = db.execute("SELECT id FROM entries WHERE url = ?", (url,)).fetchone()
        if existing:
            # Still add to list if not already there
            _add_entries_to_list(db, auto_list_id, [existing["id"]])
            continue
        try:
            entry_id = None
            for event in _process_url(url, source="rss"):
                if event.get("type") == "error":
                    logger.warning("RSS analysis error for %s: %s", url, event.get("msg"))
                elif event.get("type") == "result":
                    entry_id = event["entry"]["id"]
            if entry_id:
                new_ids.append(entry_id)
        except Exception as exc:
            logger.warning("RSS item skipped (%s): %s", url, exc)
            continue
        added += 1

    if new_ids:
        _add_entries_to_list(db, auto_list_id, new_ids)

    db.execute(
        "UPDATE rss_feeds SET last_checked = datetime('now') WHERE id = ?",
        (feed_id,),
    )
    db.commit()
    logger.info("RSS feed %s polled: %d new entries added to list '%s'", feed_url, added, feed_title)
    return added


def _poll_all_feeds():
    """Poll all registered RSS feeds. Called by the background scheduler."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        feeds = db.execute("SELECT id, url FROM rss_feeds").fetchall()
        for feed in feeds:
            _poll_rss_feed(db, feed["id"], feed["url"])
    except Exception as exc:
        logger.error("RSS poll error: %s", exc)
    finally:
        db.close()


def _resolve_yt_channel(url: str) -> tuple[str, str]:
    """Return (channel_id, channel_name) for a YouTube channel URL.

    Supports @handle, /channel/UCxxx, /c/name, /user/name formats.
    Raises RuntimeError on failure.
    """
    try:
        from pytubefix import Channel
        ch = Channel(url)
        channel_id   = ch.channel_id
        channel_name = ch.channel_name or ch.title or url
        if not channel_id:
            raise RuntimeError("Could not resolve channel ID")
        return channel_id, channel_name
    except Exception as exc:
        raise RuntimeError(f"Failed to resolve YouTube channel: {exc}")


def _analyze_selected_yt_videos(channel_db_id: int, urls: list[str]):
    """Background task: analyse a specific set of YT video URLs for a channel subscription."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            "SELECT id, channel_id, name FROM yt_channels WHERE id = ?", (channel_db_id,)
        ).fetchone()
        if not row:
            return
        auto_list_id = _get_or_create_list(db, row["name"] or row["channel_id"])
        new_ids = []
        for url in urls:
            existing = db.execute("SELECT id FROM entries WHERE url = ?", (url,)).fetchone()
            if existing:
                _add_entries_to_list(db, auto_list_id, [existing["id"]])
                continue
            try:
                entry_id = None
                for event in _process_url(url, source="youtube"):
                    if event.get("type") == "result":
                        entry_id = event["entry"]["id"]
                if entry_id:
                    new_ids.append(entry_id)
            except Exception as exc:
                logger.warning("Selected YT video skipped (%s): %s", url, exc)
        if new_ids:
            _add_entries_to_list(db, auto_list_id, new_ids)
        db.commit()
    finally:
        db.close()


_YT_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _poll_yt_channel(db, row) -> int:
    """Fetch the latest videos for a YouTube channel and analyse new ones.

    Returns the count of newly added entries.
    """
    channel_id   = row["channel_id"]
    channel_name = row["name"] or channel_id
    feed_url     = _YT_FEED_URL.format(channel_id=channel_id)

    try:
        parsed = feedparser.parse(feed_url)
    except Exception as exc:
        logger.warning("YT channel feed fetch failed for %s: %s", channel_id, exc)
        return 0

    auto_list_id = _get_or_create_list(db, channel_name)

    added   = 0
    new_ids = []
    for item in parsed.entries:
        # YouTube feed entries use the yt:videoId link element
        url = item.get("link", "").strip()
        if not url or not _extract_video_id(url):
            continue
        existing = db.execute("SELECT id FROM entries WHERE url = ?", (url,)).fetchone()
        if existing:
            _add_entries_to_list(db, auto_list_id, [existing["id"]])
            continue
        try:
            entry_id = None
            for event in _process_url(url, source="youtube"):
                if event.get("type") == "error":
                    logger.warning("YT channel analysis error for %s: %s", url, event.get("msg"))
                elif event.get("type") == "result":
                    entry_id = event["entry"]["id"]
            if entry_id:
                new_ids.append(entry_id)
                added += 1
        except Exception as exc:
            logger.warning("YT channel item skipped (%s): %s", url, exc)

    if new_ids:
        _add_entries_to_list(db, auto_list_id, new_ids)

    db.execute(
        "UPDATE yt_channels SET last_checked = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    db.commit()
    logger.info("YT channel %s polled: %d new videos added to list '%s'",
                channel_name, added, channel_name)
    return added


def _poll_all_yt_channels():
    """Poll all subscribed YouTube channels."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        channels = db.execute("SELECT id, channel_id, name FROM yt_channels").fetchall()
        for ch in channels:
            _poll_yt_channel(db, ch)
    except Exception as exc:
        logger.error("YT channel poll error: %s", exc)
    finally:
        db.close()


def _start_rss_scheduler():
    """Start a recurring background timer that polls all RSS feeds and YT channels every hour."""
    def _run():
        _poll_all_feeds()
        _poll_all_yt_channels()
        t = threading.Timer(3600, _run)
        t.daemon = True
        t.start()

    initial = threading.Timer(60, _run)
    initial.daemon = True
    initial.start()
    logger.info("RSS/YT scheduler started (first poll in 60s, then every 3600s)")


# ---------------------------------------------------------------------------
# RSS Feed API routes
# ---------------------------------------------------------------------------

@app.route("/rss-feeds", methods=["GET"])
def list_rss_feeds():
    db   = get_db()
    rows = db.execute("""
        SELECT f.id, f.url, f.name, f.last_checked, f.created_at,
               COUNT(e.id) AS entry_count
        FROM rss_feeds f
        LEFT JOIN entries e ON e.source = 'rss'
            AND e.url IN (SELECT url FROM entries WHERE source='rss')
        GROUP BY f.id
        ORDER BY f.created_at DESC
    """).fetchall()
    # Use a simpler query that counts entries where feed url is matched by domain heuristic
    # Actually just return feed metadata + a total RSS entry count per feed stored in a separate way
    # Simplest: return feeds, entry_count = total rss entries (not per-feed)
    feeds = []
    for r in db.execute("SELECT id, url, name, last_checked, created_at FROM rss_feeds ORDER BY created_at DESC").fetchall():
        count = db.execute(
            "SELECT COUNT(*) FROM entries WHERE source = 'rss'"
        ).fetchone()[0]
        feeds.append({
            "id":           r["id"],
            "url":          r["url"],
            "name":         r["name"],
            "last_checked": r["last_checked"],
            "created_at":   r["created_at"],
            "entry_count":  count,
        })
    return jsonify(feeds), 200


@app.route("/rss-feeds", methods=["POST"])
def add_rss_feed():
    body = request.get_json(silent=True) or {}
    url  = str(body.get("url", "")).strip()
    name = str(body.get("name", "")).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"}), 400
    db = get_db()
    try:
        row = db.execute(
            "INSERT INTO rss_feeds (url, name) VALUES (?, ?) RETURNING id, url, name, last_checked, created_at",
            (url, name),
        ).fetchone()
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Feed URL already exists"}), 409
    return jsonify(dict(row)), 201


@app.route("/rss-feeds/<int:feed_id>", methods=["DELETE"])
def delete_rss_feed(feed_id):
    db = get_db()
    db.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
    db.commit()
    return "", 204


@app.route("/rss-feeds/<int:feed_id>/poll", methods=["POST"])
def poll_rss_feed(feed_id):
    db  = get_db()
    row = db.execute("SELECT id, url FROM rss_feeds WHERE id = ?", (feed_id,)).fetchone()
    if not row:
        return jsonify({"error": "Feed not found"}), 404
    # Use a fresh connection so _poll_rss_feed can commit independently
    poll_db = sqlite3.connect(DB_PATH)
    poll_db.row_factory = sqlite3.Row
    try:
        added = _poll_rss_feed(poll_db, row["id"], row["url"])
    finally:
        poll_db.close()
    return jsonify({"added": added}), 200


# ---------------------------------------------------------------------------
# YouTube channel subscriptions
# ---------------------------------------------------------------------------

@app.route("/yt-channels",                  methods=["OPTIONS"])
@app.route("/yt-channels/preview",          methods=["OPTIONS"])
@app.route("/yt-channels/<int:cid>",        methods=["OPTIONS"])
@app.route("/yt-channels/<int:cid>/poll",   methods=["OPTIONS"])
def yt_channels_options(*args, **kwargs):
    resp = jsonify({})
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp, 204


@app.route("/yt-channels/preview", methods=["POST"])
def preview_yt_channel():
    """Resolve a YouTube channel URL and return its latest video list without subscribing."""
    body = request.get_json(silent=True) or {}
    url  = str(body.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"}), 400
    try:
        channel_id, channel_name = _resolve_yt_channel(url)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 400
    feed_url = _YT_FEED_URL.format(channel_id=channel_id)
    try:
        parsed = feedparser.parse(feed_url)
    except Exception as exc:
        return jsonify({"error": f"Failed to fetch channel feed: {exc}"}), 500
    videos = []
    for item in parsed.entries:
        video_url = item.get("link", "").strip()
        if not video_url or not _extract_video_id(video_url):
            continue
        thumbnail = None
        if getattr(item, "media_thumbnail", None):
            thumbnail = item.media_thumbnail[0].get("url")
        videos.append({
            "url":       video_url,
            "title":     item.get("title", video_url),
            "published": item.get("published", ""),
            "thumbnail": thumbnail,
        })
    return jsonify({"channel_id": channel_id, "name": channel_name, "videos": videos}), 200


@app.route("/yt-channels", methods=["GET"])
def list_yt_channels():
    db   = get_db()
    rows = db.execute(
        "SELECT id, channel_id, channel_url, name, last_checked, created_at FROM yt_channels ORDER BY created_at DESC"
    ).fetchall()
    channels = []
    for r in rows:
        channels.append({
            "id":           r["id"],
            "channel_id":   r["channel_id"],
            "channel_url":  r["channel_url"],
            "name":         r["name"],
            "last_checked": r["last_checked"],
            "created_at":   r["created_at"],
        })
    return jsonify(channels), 200


@app.route("/yt-channels", methods=["POST"])
def add_yt_channel():
    body         = request.get_json(silent=True) or {}
    url          = str(body.get("url", "")).strip()
    name         = str(body.get("name", "")).strip()
    analyze_urls = body.get("analyze_urls")   # list[str] | None; if provided, only these are analysed immediately
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"}), 400
    try:
        channel_id, resolved_name = _resolve_yt_channel(url)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 400
    display_name = name or resolved_name
    db = get_db()
    try:
        row = db.execute(
            """INSERT INTO yt_channels (channel_id, channel_url, name)
               VALUES (?, ?, ?)
               RETURNING id, channel_id, channel_url, name, last_checked, created_at""",
            (channel_id, url, display_name),
        ).fetchone()
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Channel already subscribed"}), 409
    channel_db_id = row["id"]
    if analyze_urls is not None:
        # Mark last_checked = now so the hourly scheduler only picks up NEW videos from here on.
        db.execute("UPDATE yt_channels SET last_checked = datetime('now') WHERE id = ?", (channel_db_id,))
        db.commit()
        # Analyse only the explicitly selected videos in a background thread.
        if analyze_urls:
            t = threading.Thread(
                target=_analyze_selected_yt_videos,
                args=(channel_db_id, analyze_urls),
                daemon=True,
            )
            t.start()
    return jsonify(dict(row)), 201


@app.route("/yt-channels/<int:cid>", methods=["DELETE"])
def delete_yt_channel(cid):
    db = get_db()
    db.execute("DELETE FROM yt_channels WHERE id = ?", (cid,))
    db.commit()
    return "", 204


@app.route("/yt-channels/<int:cid>/poll", methods=["POST"])
def poll_yt_channel_endpoint(cid):
    db  = get_db()
    row = db.execute("SELECT id, channel_id, name FROM yt_channels WHERE id = ?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Channel not found"}), 404
    poll_db = sqlite3.connect(DB_PATH)
    poll_db.row_factory = sqlite3.Row
    try:
        added = _poll_yt_channel(poll_db, row)
    finally:
        poll_db.close()
    return jsonify({"added": added}), 200


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------

@app.route("/chat/sessions", methods=["GET"])
def list_chat_sessions():
    db   = get_db()
    rows = db.execute("""
        SELECT cs.id, cs.title, cs.model, cs.created_at, cs.updated_at,
               COUNT(cm.id) AS message_count
        FROM chat_sessions cs
        LEFT JOIN chat_messages cm ON cm.session_id = cs.id
        GROUP BY cs.id
        ORDER BY cs.updated_at DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/chat/sessions", methods=["POST"])
def create_chat_session():
    body  = request.get_json(silent=True) or {}
    model = (body.get("model") or "gemini-2.5-flash").strip()
    title = (body.get("title") or "").strip() or "Untitled"
    db    = get_db()
    cur   = db.execute(
        "INSERT INTO chat_sessions (title, model) VALUES (?,?)", (title, model)
    )
    db.commit()
    row = db.execute("SELECT * FROM chat_sessions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({**dict(row), "message_count": 0}), 201


@app.route("/chat/sessions/<int:session_id>", methods=["PATCH"])
def rename_chat_session(session_id):
    body  = request.get_json(silent=True) or {}
    title = body.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    db = get_db()
    db.execute(
        "UPDATE chat_sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
        (title, session_id),
    )
    db.commit()
    return jsonify({"id": session_id, "title": title}), 200


@app.route("/chat/sessions/<int:session_id>", methods=["DELETE"])
def delete_chat_session(session_id):
    db = get_db()
    db.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    db.commit()
    return "", 204


@app.route("/chat/sessions/<int:session_id>/messages", methods=["GET"])
def get_chat_messages(session_id):
    db  = get_db()
    row = db.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    msgs = db.execute(
        "SELECT id, role, text, sources, created_at FROM chat_messages "
        "WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()
    result = []
    for m in msgs:
        d = dict(m)
        try:
            d["sources"] = json.loads(d["sources"] or "[]")
        except Exception:
            d["sources"] = []
        result.append(d)
    return jsonify(result), 200


_VALID_CHAT_MODELS_GEMINI = {"gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"}
_VALID_CHAT_MODELS_OLLAMA = {_OLLAMA_MODEL}
_VALID_CHAT_MODELS = _VALID_CHAT_MODELS_GEMINI | _VALID_CHAT_MODELS_OLLAMA


def _default_chat_model() -> str:
    return _OLLAMA_MODEL if _LLM_PROVIDER == "ollama" else _MODEL_NAME

_CHAT_SYSTEM_PROMPT = (
    "You are a cyber-security expert assistant. "
    "Answer ONLY using the knowledge base context provided below. "
    "Cite the entry names you used. "
    "If the answer is not in the context, say so explicitly.\n\n"
    "KNOWLEDGE BASE CONTEXT:\n{context}"
)


def _read_env_file():
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return {}
    data = {}

    def decode_value(val: str):
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            try:
                return json.loads(val)
            except Exception:
                val = val[1:-1]
        try:
            return bytes(val, "utf-8").decode("unicode_escape")
        except Exception:
            return val

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            data[key.strip()] = decode_value(val.strip())
    return data


def _write_env_file(updates: dict):
    path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    seen = set()

    def encode_value(val):
        if not isinstance(val, str):
            val = str(val)
        if "\n" in val or "\"" in val or "'" in val or val.strip() != val:
            return json.dumps(val, ensure_ascii=False)
        return val

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    lines.append(line)
                    continue
                key, _ = stripped.split("=", 1)
                key = key.strip()
                if key in updates:
                    lines.append(f"{key}={encode_value(updates[key])}\n")
                    seen.add(key)
                else:
                    lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={encode_value(value)}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _reload_provider_settings():
    global _LLM_PROVIDER, _API_KEY, _OLLAMA_URL, _OLLAMA_MODEL, _OLLAMA_EMBED_MODEL, _genai_client, _VALID_CHAT_MODELS_OLLAMA, _VALID_CHAT_MODELS
    global _SYSTEM_PROMPT_BASE, _CHAT_SYSTEM_PROMPT, _OLLAMA_CHAT_OPTIONS, _OLLAMA_ANALYZE_OPTIONS

    env = _read_env_file()
    _LLM_PROVIDER = env.get("LLM_PROVIDER", _LLM_PROVIDER).strip().lower()
    _API_KEY = env.get("GEMINI_API_KEY", _API_KEY).strip()
    _OLLAMA_URL = env.get("OLLAMA_URL", _OLLAMA_URL).strip().rstrip("/")
    _OLLAMA_MODEL = env.get("OLLAMA_MODEL", _OLLAMA_MODEL).strip()
    _OLLAMA_EMBED_MODEL = env.get("OLLAMA_EMBED_MODEL", _OLLAMA_EMBED_MODEL).strip()

    _SYSTEM_PROMPT_BASE = env.get("SYSTEM_PROMPT_BASE", _SYSTEM_PROMPT_BASE)
    _CHAT_SYSTEM_PROMPT = env.get("CHAT_SYSTEM_PROMPT", _CHAT_SYSTEM_PROMPT)

    def _parse_options(value, fallback):
        if not value:
            return fallback
        try:
            opts = json.loads(value)
            if isinstance(opts, dict):
                return opts
        except Exception:
            pass
        return fallback

    _OLLAMA_CHAT_OPTIONS = _parse_options(env.get("OLLAMA_CHAT_OPTIONS", json.dumps(_OLLAMA_CHAT_OPTIONS)), _OLLAMA_CHAT_OPTIONS)
    _OLLAMA_ANALYZE_OPTIONS = _parse_options(env.get("OLLAMA_ANALYZE_OPTIONS", json.dumps(_OLLAMA_ANALYZE_OPTIONS)), _OLLAMA_ANALYZE_OPTIONS)

    _genai_client = genai.Client(api_key=_API_KEY) if _API_KEY else None
    _VALID_CHAT_MODELS_OLLAMA = {_OLLAMA_MODEL}
    _VALID_CHAT_MODELS = _VALID_CHAT_MODELS_GEMINI | _VALID_CHAT_MODELS_OLLAMA


@app.route("/settings", methods=["GET"])
def get_settings():
    env = _read_env_file()
    return jsonify({
        "provider": env.get("LLM_PROVIDER", _LLM_PROVIDER),
        "gemini_api_key": env.get("GEMINI_API_KEY", ""),
        "ollama_url": env.get("OLLAMA_URL", _OLLAMA_URL),
        "ollama_model": env.get("OLLAMA_MODEL", _OLLAMA_MODEL),
        "ollama_embed_model": env.get("OLLAMA_EMBED_MODEL", _OLLAMA_EMBED_MODEL),
        "system_prompt_base": env.get("SYSTEM_PROMPT_BASE", _SYSTEM_PROMPT_BASE),
        "chat_system_prompt": env.get("CHAT_SYSTEM_PROMPT", _CHAT_SYSTEM_PROMPT),
        "ollama_chat_options": env.get("OLLAMA_CHAT_OPTIONS", json.dumps(_OLLAMA_CHAT_OPTIONS, indent=2)),
        "ollama_analyze_options": env.get("OLLAMA_ANALYZE_OPTIONS", json.dumps(_OLLAMA_ANALYZE_OPTIONS, indent=2)),
        "gemini_models": [
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro",
        ],
        "ollama_models": [
            "qwen3:4b", "qwen3:8b", "qwen3:14b", "qwen3:30b",
        ],
        "ollama_embedding_models": [
            "qwen3-embedding:8b", "embeddinggemma:300m" , "nomic-embed-text:v1.5"
        ],
    })


@app.route("/settings", methods=["POST"])
def update_settings():
    body = request.get_json(silent=True)
    if not body or not isinstance(body, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    provider = str(body.get("provider", _LLM_PROVIDER)).strip().lower()
    if provider not in ("gemini", "ollama"):
        return jsonify({"error": "Invalid provider"}), 400

    gemini_api_key = str(body.get("gemini_api_key", "")).strip()
    ollama_url = str(body.get("ollama_url", _OLLAMA_URL)).strip() or _OLLAMA_URL
    ollama_model = str(body.get("ollama_model", _OLLAMA_MODEL)).strip() or _OLLAMA_MODEL
    ollama_embed_model = str(body.get("ollama_embed_model", _OLLAMA_EMBED_MODEL)).strip() or _OLLAMA_EMBED_MODEL
    system_prompt_base = str(body.get("system_prompt_base", _SYSTEM_PROMPT_BASE)).strip()
    chat_system_prompt = str(body.get("chat_system_prompt", _CHAT_SYSTEM_PROMPT)).strip()
    ollama_chat_options = str(body.get("ollama_chat_options", json.dumps(_OLLAMA_CHAT_OPTIONS))).strip()
    ollama_analyze_options = str(body.get("ollama_analyze_options", json.dumps(_OLLAMA_ANALYZE_OPTIONS))).strip()

    updates = {
        "LLM_PROVIDER": provider,
        "OLLAMA_URL": ollama_url,
        "OLLAMA_MODEL": ollama_model,
        "OLLAMA_EMBED_MODEL": ollama_embed_model,
        "GEMINI_API_KEY": gemini_api_key,
        "SYSTEM_PROMPT_BASE": system_prompt_base,
        "CHAT_SYSTEM_PROMPT": chat_system_prompt,
        "OLLAMA_CHAT_OPTIONS": ollama_chat_options,
        "OLLAMA_ANALYZE_OPTIONS": ollama_analyze_options,
    }

    try:
        _write_env_file(updates)
        _reload_provider_settings()
    except Exception as exc:
        return jsonify({"error": f"Could not write .env: {exc}"}), 500

    return jsonify({"ok": True, "provider": provider}), 200


@app.route("/provider")
def get_provider():
    """Return the active LLM provider and its available chat models."""
    if _LLM_PROVIDER == "ollama":
        models = [{"id": m, "label": m} for m in sorted(_VALID_CHAT_MODELS_OLLAMA)]
        default = _OLLAMA_MODEL
    else:
        models = [
            {"id": "gemini-2.5-flash", "label": "2.5 Flash (fast)"},
            {"id": "gemini-2.5-pro",   "label": "2.5 Pro (deep)"},
            {"id": "gemini-1.5-flash", "label": "1.5 Flash"},
            {"id": "gemini-1.5-pro",   "label": "1.5 Pro"},
        ]
        default = _MODEL_NAME
    return jsonify({"provider": _LLM_PROVIDER, "models": models, "default_model": default})


@app.route("/ollama/status")
def ollama_status():
    try:
        models = _ollama_list_models()
        return jsonify({"running": True, "models": models}), 200
    except Exception as exc:
        return jsonify({"running": False, "models": [], "error": str(exc)}), 200


@app.route("/ollama/pull", methods=["POST"])
def ollama_pull():
    body = request.get_json(silent=True) or {}
    model = str(body.get("model", "")).strip()
    if not model:
        return jsonify({"error": "Model parameter required"}), 400

    def generate():
        yield json.dumps({"type": "started", "message": f"Pulling model {model}..."}) + "\n"
        try:
            client = _get_ollama_client()
            for chunk in client.pull(model, stream=True):
                if hasattr(chunk, "message") and chunk.message:
                    text = str(chunk.message).strip()
                    if text:
                        yield json.dumps({"type": "progress", "line": text}) + "\n"
                elif hasattr(chunk, "status"):
                    yield json.dumps({"type": "progress", "line": str(chunk.status)}) + "\n"
            yield json.dumps({"type": "complete", "model": model}) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


_OLLAMA_SERVE_PROCESS = None


@app.route("/ollama/serve", methods=["POST"])
def ollama_serve():
    global _OLLAMA_SERVE_PROCESS
    if _OLLAMA_SERVE_PROCESS and _OLLAMA_SERVE_PROCESS.poll() is None:
        return jsonify({"ok": True, "message": "Ollama serve already running", "pid": _OLLAMA_SERVE_PROCESS.pid}), 200
    try:
        _OLLAMA_SERVE_PROCESS = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
            text=True,
        )
        return jsonify({"ok": True, "message": "Ollama serve started", "pid": _OLLAMA_SERVE_PROCESS.pid}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/entries/search")
def search_entries_autocomplete():
    q    = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([]), 200
    db   = get_db()
    like = f"%{q}%"
    rows = db.execute(
        "SELECT id, name, url, category FROM entries WHERE parent_id IS NULL"
        " AND (name LIKE ? OR url LIKE ?) ORDER BY name LIMIT 20",
        (like, like),
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/chat", methods=["POST"])
def chat():
    body       = request.get_json(silent=True) or {}
    question   = (body.get("question") or "").strip()
    session_id = body.get("session_id")
    model_name = (body.get("model") or _default_chat_model()).strip()
    pinned_ids = [int(x) for x in (body.get("pinned_ids") or []) if str(x).isdigit()]

    if not question:
        return jsonify({"error": "question required"}), 400
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    if _LLM_PROVIDER == "gemini" and not _API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500
    if model_name not in _VALID_CHAT_MODELS:
        model_name = _default_chat_model()

    # Pre-flight: validate session exists (uses request-context DB, safe here)
    pre_db = get_db()
    session_row = pre_db.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if not session_row:
        return jsonify({"error": "Session not found"}), 404
    session_title   = session_row["title"]
    history_rows    = pre_db.execute(
        "SELECT role, text FROM chat_messages WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()
    history_data = [(r["role"], r["text"]) for r in history_rows]

    def generate():
        # Open a dedicated connection — the Flask request context is gone by the
        # time the generator runs, so we must NOT use get_db() / g here.
        sdb = sqlite3.connect(DB_PATH)
        sdb.row_factory = sqlite3.Row
        nonlocal session_title
        try:
            sources, context_parts = [], []

            if pinned_ids:
                # ── Pinned-entry mode: skip RAG, use caller-selected entries ──
                ph         = ",".join("?" * len(pinned_ids))
                entry_rows = sdb.execute(
                    f"SELECT * FROM entries WHERE id IN ({ph})", pinned_ids  # nosec B608 – ph contains only '?' placeholders
                ).fetchall()
                for row in entry_rows:
                    chunk_rows = sdb.execute(
                        "SELECT chunk_text FROM entry_chunks WHERE entry_id = ? ORDER BY chunk_index",
                        (row["id"],),
                    ).fetchall()
                    if chunk_rows:
                        chunk_text = "\n\n".join(r["chunk_text"] for r in chunk_rows)
                    else:
                        chunk_text = (row["content"] or "").strip()
                    sources.append({"id": row["id"], "name": row["name"],
                                    "url": row["url"], "pinned": True})
                    context_parts.append(f"## {row['name']}\nURL: {row['url']}\n\n{chunk_text}")
            else:
                # ── RAG retrieval ──────────────────────────────────────────
                try:
                    ollama_logger.debug("CHAT EMBED QUERY — question=%d chars", len(question))
                    query_emb = _get_embedding(question, task_type="RETRIEVAL_QUERY")
                except Exception as exc:
                    yield json.dumps({"type": "error", "message": f"Embedding failed: {exc}"}) + "\n"
                    return

                chunks = sdb.execute(
                    "SELECT entry_id, chunk_text, embedding FROM entry_chunks"
                ).fetchall()

                total_entries   = sdb.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                embedded_ids    = set(c["entry_id"] for c in chunks)
                missing_count   = total_entries - len(embedded_ids) if total_entries else 0

                if total_entries > 0 and missing_count > 0:
                    logger.warning(
                        "Chat RAG: %d / %d entries have no embeddings — "
                        "run POST /entries/embed-required to rebuild",
                        missing_count, total_entries,
                    )
                    yield json.dumps({
                        "type": "no_rag",
                        "message": f"{missing_count} of {total_entries} entries have no embeddings — "
                                   "chat answers may be incomplete. Re-embed to enable full RAG.",
                        "entry_count": missing_count,
                    }) + "\n"
                elif total_entries == 0:
                    logger.info("Chat RAG: no entries in the knowledge base yet")

                entry_scores: dict = {}
                for chunk in chunks:
                    try:
                        emb = json.loads(chunk["embedding"])
                        sim = _cosine_sim(query_emb, emb)
                        eid = chunk["entry_id"]
                        if sim > entry_scores.get(eid, (-1, ""))[0]:
                            entry_scores[eid] = (sim, chunk["chunk_text"])
                    except Exception:
                        continue

                top_entries = sorted(
                    [(eid, sc, txt) for eid, (sc, txt) in entry_scores.items() if sc > 0.2],
                    key=lambda x: -x[1],
                )[:4]

                if top_entries:
                    top_ids    = [eid for eid, _, _ in top_entries]
                    ph         = ",".join("?" * len(top_ids))
                    entry_rows = sdb.execute(f"SELECT * FROM entries WHERE id IN ({ph})", top_ids).fetchall()  # nosec B608 – ph contains only '?' placeholders
                    entry_map  = {r["id"]: r for r in entry_rows}
                    for eid, score, chunk_text in top_entries:
                        row = entry_map.get(eid)
                        if not row:
                            continue
                        sources.append({"id": eid, "name": row["name"], "url": row["url"],
                                         "score": round(score, 3)})
                        context_parts.append(f"## {row['name']}\nURL: {row['url']}\n\n{chunk_text}")

            yield json.dumps({"type": "sources", "entries": sources}) + "\n"

            context_text = "\n\n---\n\n".join(context_parts)[:24000] if context_parts \
                else "No relevant knowledge base entries found."

            if pinned_ids:
                system_prompt = (
                    "You are a cyber-security expert assistant. "
                    "The user has pinned specific articles/entries for this question. "
                    "Answer ONLY using the pinned entries provided below — do not draw on any other knowledge. "
                    "Cite the entry names you used."
                    "Do not use any internal data you have, just use the PINNED ENTRIES provided."
                    "You are here to help answer the user's question using the PINNED ENTRIES. no addtional info and no corrections to user"
                    "If the answer is not in the pinned entries, say so explicitly.\n\n"
                    f"PINNED ENTRIES:\n{context_text}"
                )
            else:
                system_prompt = _CHAT_SYSTEM_PROMPT.format(context=context_text)

            # ── Stream LLM response ────────────────────────────────────────
            try:
                if _LLM_PROVIDER == "ollama":
                    messages = [{"role": "system", "content": system_prompt}]
                    for role, text in history_data:
                        messages.append({"role": role if role != "assistant" else "assistant", "content": text})
                    messages.append({"role": "user", "content": question})

                    ollama_logger.debug(
                        "CHAT REQUEST — model=%s, messages=%d, system=%d chars, question=%d chars",
                        model_name, len(messages), len(system_prompt), len(question),
                    )

                    try:
                        chat_client = _get_ollama_client()
                        chat_stream = chat_client.chat(
                            model=model_name,
                            messages=messages,
                            stream=True,
                            think='high',
                            options=_OLLAMA_CHAT_OPTIONS,
                        )
                    except _ollama_mod.ResponseError as e:
                        raise RuntimeError(f"Ollama chat error: {e}") from e
                    except Exception as e:
                        if "connect" in str(e).lower() or "refused" in str(e).lower():
                            raise EnvironmentError(
                                f"Cannot connect to Ollama at {_OLLAMA_URL}. "
                                f"Make sure Ollama is running (ollama serve) and the model is pulled:\n"
                                f"  ollama pull {model_name}"
                            ) from e
                        raise

                    full_response = []
                    last_chunk = None
                    for chunk in chat_stream:
                        text = chunk.message.content or ""
                        if text:
                            # Strip <think>…</think> from streamed reasoning
                            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
                            if text:
                                full_response.append(text)
                                yield json.dumps({"type": "chunk", "text": text}) + "\n"
                        last_chunk = chunk
                    assembled = "".join(full_response)
                    # Clean any partial <think> tags that spanned chunks
                    assembled = re.sub(r"<think>.*?</think>", "", assembled, flags=re.DOTALL).strip()
                    if last_chunk:
                        ollama_logger.info(_extract_ollama_stats(last_chunk))
                    ollama_logger.debug("CHAT RESPONSE (%d chars): %s", len(assembled), assembled[:500])
                else:
                    # Gemini streaming
                    gemini_contents = []
                    for role, text in history_data:
                        gemini_role = "model" if role == "assistant" else "user"
                        gemini_contents.append({"role": gemini_role, "parts": [{"text": text}]})
                    gemini_contents.append({"role": "user", "parts": [{"text": question}]})

                    stream = _genai_client.models.generate_content_stream(
                        model=model_name,
                        contents=gemini_contents,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.3,
                            max_output_tokens=2048,
                            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                        ),
                    )
                    full_response = []
                    for chunk in stream:
                        text = chunk.text or ""
                        if text:
                            full_response.append(text)
                            yield json.dumps({"type": "chunk", "text": text}) + "\n"
                    assembled = "".join(full_response)

                sdb.execute(
                    "INSERT INTO chat_messages (session_id, role, text, sources) VALUES (?,?,?,?)",
                    (session_id, "user", question, "[]"),
                )
                sdb.execute(
                    "INSERT INTO chat_messages (session_id, role, text, sources) VALUES (?,?,?,?)",
                    (session_id, "assistant", assembled, json.dumps(sources)),
                )
                if not session_title or session_title.strip().lower() == "untitled":
                    session_title = question[:60]
                    sdb.execute(
                        "UPDATE chat_sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
                        (session_title, session_id),
                    )
                else:
                    sdb.execute(
                        "UPDATE chat_sessions SET updated_at = datetime('now') WHERE id = ?",
                        (session_id,),
                    )
                sdb.commit()
            except Exception as exc:
                logger.error("Chat LLM error: %s", exc)
                yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
                return

            yield json.dumps({"type": "done", "title": session_title}) + "\n"

        finally:
            sdb.close()

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


# ---------------------------------------------------------------------------
# Log viewer endpoints
# ---------------------------------------------------------------------------

@app.route("/logs")
def get_log_entries():
    since = request.args.get("since", 0, type=int)
    return jsonify(_mem_log.get_since(since)), 200


@app.route("/logs", methods=["DELETE"])
def clear_log_entries():
    _mem_log.clear()
    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
# Ensure database exists and is migrated to the latest schema before serving
init_db()

_debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# Backup on startup and every 12 hours (keep last 10 backups)
# When running with the Flask reloader, only run backups in the reloader child.
if not _debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _make_db_backup("startup")
    _start_backup_scheduler(12)

_start_rss_scheduler()
app.run(port=8000, debug=_debug, use_reloader=_debug)
