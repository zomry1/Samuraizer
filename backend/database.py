"""
Samuraizer – Database module.
Handles SQLite initialisation, schema migrations, request-scoped connections,
and shared row-conversion helpers.
"""

import json
import sqlite3
import time

from flask import g

from backend.config import DB_PATH
from backend.logging_setup import logger


# ---------------------------------------------------------------------------
# Request-scoped connection (Flask `g`)
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA busy_timeout=30000")
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db:
        db.close()


# ---------------------------------------------------------------------------
# Schema initialisation & migrations
# ---------------------------------------------------------------------------
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
        db.execute("""
            CREATE TABLE IF NOT EXISTS rss_feeds (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url           TEXT    UNIQUE NOT NULL,
                name          TEXT    NOT NULL DEFAULT '',
                last_checked  TEXT    DEFAULT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
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
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    DEFAULT NULL,
                model      TEXT    NOT NULL DEFAULT 'gemini-2.5-flash',
                created_at TEXT    DEFAULT (datetime('now')),
                updated_at TEXT    DEFAULT (datetime('now'))
            )
        """)
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
# Row conversion helpers
# ---------------------------------------------------------------------------
def row_to_dict(row, db=None) -> dict:
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


def bulk_list_ids(db, entry_ids: list[int]) -> dict[int, list[int]]:
    """Return {entry_id: [list_id, ...]} for all given entry ids."""
    if not entry_ids:
        return {}
    placeholders = ",".join("?" * len(entry_ids))
    rows = db.execute(
        f"SELECT entry_id, list_id FROM list_entries WHERE entry_id IN ({placeholders})",  # nosec B608
        entry_ids,
    ).fetchall()
    result: dict[int, list[int]] = {eid: [] for eid in entry_ids}
    for r in rows:
        result[r["entry_id"]].append(r["list_id"])
    return result


def get_or_create_list(db, name: str) -> int:
    """Return the id of a list with the given name, creating it if needed."""
    row = db.execute("SELECT id FROM lists WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO lists (name) VALUES (?)", (name,))
    db.commit()
    return cur.lastrowid


def add_entries_to_list(db, list_id: int, entry_ids: list[int]) -> None:
    """Insert entries into a list, ignoring duplicates."""
    if not entry_ids:
        return
    db.executemany(
        "INSERT OR IGNORE INTO list_entries (list_id, entry_id) VALUES (?, ?)",
        [(list_id, eid) for eid in entry_ids],
    )
    db.commit()


def sqlite_retry(fn, retries: int = 8, delay: float = 0.15):
    """Retry a DB operation on 'database is locked' errors."""
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
