"""
Samuraizer – Embedding functions.
Chunking, embed via Gemini or Ollama, cosine similarity, chunk storage.
"""

import json
import math
import time

from google.genai import types as genai_types

import backend.config as cfg
from backend.logging_setup import ollama_logger
from backend.database import sqlite_retry
from backend.llm.ollama_utils import get_ollama_client, OllamaResponseError


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks of ~CHUNK_SIZE chars."""
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = start + cfg.CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - cfg.CHUNK_OVERLAP
    return chunks


# ---------------------------------------------------------------------------
# Provider-specific embedding calls
# ---------------------------------------------------------------------------
def get_embedding_gemini(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list:
    result = cfg.genai_client.models.embed_content(
        model=cfg.EMBED_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(task_type=task_type),
    )
    return list(result.embeddings[0].values)


def get_embedding_ollama(text: str, logs: list | None = None) -> list:
    if logs is not None:
        logs.append(f"Requesting embedding from Ollama ({cfg.OLLAMA_EMBED_MODEL})...")
    ollama_logger.debug(
        "EMBED REQUEST — model=%s, input=%d chars: %s",
        cfg.OLLAMA_EMBED_MODEL, len(text), text[:200],
    )
    t0 = time.time()
    try:
        client = get_ollama_client()
        data = client.embed(model=cfg.OLLAMA_EMBED_MODEL, input=text)
    except OllamaResponseError as e:
        ollama_logger.error("EMBED ERROR: %s", e)
        raise RuntimeError(f"Ollama embedding error: {e}") from e
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            ollama_logger.error("EMBED CONNECTION ERROR: %s", e)
            raise EnvironmentError(
                f"Cannot connect to Ollama at {cfg.OLLAMA_URL}. "
                f"Make sure Ollama is running (ollama serve) and the required models are pulled:\n"
                f"  ollama pull {cfg.OLLAMA_EMBED_MODEL}"
            ) from e
        raise
    elapsed = time.time() - t0
    emb = list(data.embeddings[0])
    ollama_logger.debug("EMBED RESPONSE — %d dims in %.1fs", len(emb), elapsed)
    if logs is not None:
        logs.append(f"Embedding received in {elapsed:.1f}s ({len(emb)} dims)")
    return emb


# ---------------------------------------------------------------------------
# Unified embedding dispatcher
# ---------------------------------------------------------------------------
def current_embedding_target():
    provider = cfg.LLM_PROVIDER
    model = cfg.OLLAMA_EMBED_MODEL if provider == "ollama" else cfg.EMBED_MODEL
    return provider, model


def get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list:
    if cfg.LLM_PROVIDER == "ollama":
        return get_embedding_ollama(text)
    return get_embedding_gemini(text, task_type)


# ---------------------------------------------------------------------------
# Embedding status helpers
# ---------------------------------------------------------------------------
def upsert_entry_embedding_status(db, entry_id: int, dim: int, status: str = "ready"):
    provider, model = current_embedding_target()
    db.execute(
        "INSERT INTO entry_embedding_status (entry_id, provider, model, dimension, status, updated_at) "
        "VALUES (?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(entry_id, provider, model) DO UPDATE SET dimension=excluded.dimension, "
        "status=excluded.status, updated_at=excluded.updated_at",
        (entry_id, provider, model, dim, status),
    )


def store_entry_embedding(db, entry_id: int, name: str, bullets: list, tags: list,
                          content: str = "") -> None:
    """Chunk the entry content, embed each chunk, and store in entry_chunks."""
    header = f"{name}. {' '.join(bullets or [])}. {' '.join(tags or [])}."

    def work():
        sqlite_retry(lambda: db.execute("DELETE FROM entry_chunks WHERE entry_id = ?", (entry_id,)))

        text_chunks = chunk_text(content.strip()) if content and content.strip() else []
        emb = None

        if text_chunks:
            for i, chunk in enumerate(text_chunks):
                full_text = f"{header}\n{chunk}"[:8000]
                emb = get_embedding(full_text)
                sqlite_retry(lambda: db.execute(
                    "INSERT INTO entry_chunks (entry_id, chunk_index, chunk_text, embedding) VALUES (?,?,?,?)",
                    (entry_id, i, chunk[:3000], json.dumps(emb)),
                ))
        else:
            emb = get_embedding(header)
            sqlite_retry(lambda: db.execute(
                "INSERT INTO entry_chunks (entry_id, chunk_index, chunk_text, embedding) VALUES (?,?,?,?)",
                (entry_id, 0, header, json.dumps(emb)),
            ))

        upsert_entry_embedding_status(db, entry_id, len(emb), "ready")
        sqlite_retry(lambda: db.commit())

    work()


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------
def cosine_sim(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Embedding health check (no LLM calls — DB only)
# ---------------------------------------------------------------------------
def fetch_embedding_health(db):
    provider, model = current_embedding_target()

    total_entries = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    if total_entries == 0:
        return {
            "ok": True, "total": 0, "embedded": 0, "mismatched": 0,
            "missing": 0, "missing_ids": [], "mismatch_ids": [],
            "provider": provider, "model": model,
        }

    ready_rows = db.execute(
        "SELECT entry_id FROM entry_embedding_status "
        "WHERE provider = ? AND model = ? AND status = 'ready'",
        (provider, model),
    ).fetchall()
    ready_ids = set(r[0] for r in ready_rows)
    all_ids = set(r[0] for r in db.execute("SELECT id FROM entries").fetchall())
    missing_ids = sorted(all_ids - ready_ids)

    return {
        "ok": len(missing_ids) == 0,
        "total": total_entries,
        "embedded": len(ready_ids),
        "mismatched": 0,
        "missing": len(missing_ids),
        "missing_ids": missing_ids,
        "mismatch_ids": [],
        "provider": provider,
        "model": model,
    }
