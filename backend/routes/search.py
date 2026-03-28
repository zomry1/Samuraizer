"""
Samuraizer – Semantic search and embedding management routes.
"""

import json
import time
import sqlite3

from flask import Blueprint, request, jsonify, Response, stream_with_context

import backend.config as cfg
from backend.logging_setup import logger
from backend.database import get_db, sqlite_retry
from backend.llm.embeddings import (
    get_embedding,
    cosine_sim,
    fetch_embedding_health,
    store_entry_embedding,
    current_embedding_target,
)

bp = Blueprint("search", __name__)


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------
@bp.route("/search/semantic", methods=["GET"])
def semantic_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([]), 200
    if cfg.LLM_PROVIDER == "gemini" and not cfg.GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500
    logger.info("Semantic search: %r", q)
    try:
        query_emb = get_embedding(q, task_type="RETRIEVAL_QUERY")
    except Exception as exc:
        logger.error("Embed query failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    db = get_db()
    chunks = db.execute("SELECT entry_id, embedding FROM entry_chunks").fetchall()
    if not chunks:
        return jsonify([]), 200

    # Best cosine score per entry across all its chunks
    entry_scores: dict = {}
    for chunk in chunks:
        try:
            emb = json.loads(chunk["embedding"])
            sim = cosine_sim(query_emb, emb)
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

    top_ids = [eid for eid, _ in top_pairs]
    score_map = {eid: s for eid, s in top_pairs}
    ph = ",".join("?" * len(top_ids))
    rows = db.execute(f"SELECT * FROM entries WHERE id IN ({ph})", top_ids).fetchall()  # nosec B608
    entry_map = {r["id"]: r for r in rows}

    from backend.database import bulk_list_ids, row_to_dict
    list_map = bulk_list_ids(db, top_ids)

    results = []
    for eid in top_ids:
        row = entry_map.get(eid)
        if not row:
            continue
        d = row_to_dict(row)
        d["list_ids"] = list_map.get(eid, [])
        d["score"] = round(score_map[eid], 3)
        results.append(d)

    logger.info("Semantic search %r → %d results", q, len(results))
    return jsonify(results), 200


# ---------------------------------------------------------------------------
# Embedding health status
# ---------------------------------------------------------------------------
@bp.route("/embeddings/status")
def embeddings_status():
    try:
        data = fetch_embedding_health()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(data), 200


# ---------------------------------------------------------------------------
# Embed-all (streaming)
# ---------------------------------------------------------------------------
def _embed_all_runner(all_mode=False):
    if cfg.LLM_PROVIDER == "gemini" and not cfg.GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500

    db = get_db()

    cfg.embed_all_status = {
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
            cfg.embed_all_status.update({
                "active": False,
                "message": f"Database integrity check failed: {check}",
                "updated_at": time.time(),
            })
            return jsonify({"error": "Database integrity check failed. Please restore from backup."}), 500
    except sqlite3.OperationalError as exc:
        if "database is locked" in str(exc).lower():
            cfg.embed_all_status.update({
                "active": False,
                "message": f"Database is locked: {exc}",
                "updated_at": time.time(),
            })
            return jsonify({"error": "Database is locked. Please retry in a moment."}), 503
        cfg.embed_all_status.update({
            "active": False,
            "message": f"Database unreadable: {exc}",
            "updated_at": time.time(),
        })
        return jsonify({"error": f"Database is malformed: {exc}. Try restoring from backup."}), 500
    except sqlite3.DatabaseError as exc:
        cfg.embed_all_status.update({
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
        health = fetch_embedding_health()
        missing_ids = health["missing_ids"]
        if missing_ids:
            placeholders = ",".join(["?"] * len(missing_ids))
            sql = "SELECT * FROM entries WHERE id IN (" + placeholders + ")"  # nosec B608
            rows = db.execute(sql, missing_ids).fetchall()
        else:
            rows = []

    total = len(rows)
    provider, model = current_embedding_target()
    if all_mode:
        logger.info("embed-all: %d entries to embed (full re-embed for %s/%s)", total, provider, model)
        cfg.embed_all_status["message"] = f"Full re-embed for {provider}/{model}"
    else:
        logger.info("embed-all: %d entries need embedding for %s/%s", total, provider, model)
        cfg.embed_all_status["message"] = f"{total} entries to embed for {provider}/{model}"

    rows_data = [dict(r) for r in rows]
    cfg.embed_all_status.update({"total": total, "updated_at": time.time()})

    def generate():
        sdb = sqlite3.connect(cfg.DB_PATH, timeout=30, check_same_thread=False)
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
                    store_entry_embedding(sdb, row["id"], model_name, bullets, tags, content)
                    sqlite_retry(lambda: sdb.commit())
                    done += 1
                except sqlite3.OperationalError as exc:
                    if "database is locked" in str(exc).lower():
                        logger.warning("embed-all row %d locked, retrying: %s", row.get("id"), exc)
                        time.sleep(1)
                        continue
                    logger.error("embed-all row %d DB error: %s", row.get("id"), exc)
                    cfg.embed_all_status.update({
                        "active": False,
                        "message": f"Database error: {exc}",
                        "updated_at": time.time(),
                    })
                    yield json.dumps({"type": "error", "message": f"Database error: {exc}"}) + "\n"
                    return
                except sqlite3.DatabaseError as exc:
                    logger.error("embed-all row %d DB error: %s", row.get("id"), exc)
                    cfg.embed_all_status.update({
                        "active": False,
                        "message": f"Database error: {exc}",
                        "updated_at": time.time(),
                    })
                    yield json.dumps({"type": "error", "message": f"Database error: {exc}"}) + "\n"
                    return
                except Exception as exc:
                    logger.error("embed-all row %d: %s", row.get("id"), exc)
                    failed += 1
                cfg.embed_all_status.update({
                    "done": done,
                    "failed": failed,
                    "message": f"Re-embedding {done}/{total} (failed {failed})",
                    "updated_at": time.time(),
                })
                yield json.dumps({"type": "progress", "done": done, "failed": failed, "total": total, "name": model_name}) + "\n"

            logger.info("embed-all: done=%d failed=%d", done, failed)
            cfg.embed_all_status.update({
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


@bp.route("/entries/embed-all", methods=["POST"])
def embed_all():
    all_mode = request.args.get("all", "false").lower() in ("1", "true", "yes")
    return _embed_all_runner(all_mode)


@bp.route("/entries/embed-required", methods=["POST"])
def embed_required():
    return _embed_all_runner(False)


@bp.route("/entries/embed-all/status", methods=["GET"])
def embed_all_status():
    return jsonify(cfg.embed_all_status), 200
