"""
Samuraizer – Entry CRUD, tags, suggest, autocomplete search routes.
"""

import json
import re

from flask import Blueprint, request, jsonify

import backend.config as cfg
from backend.logging_setup import logger
from backend.database import get_db, row_to_dict, bulk_list_ids
from backend.llm.providers import call_gemini
from backend.llm.embeddings import store_entry_embedding

bp = Blueprint("entries", __name__)


@bp.route("/entries", methods=["GET"])
def list_entries():
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip().lower()
    tag = request.args.get("tag", "").strip().lower()
    list_id = request.args.get("list_id", "").strip()
    read_filter = request.args.get("read", "").strip()
    useful_only = request.args.get("useful", "").strip()
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
    list_map = bulk_list_ids(db, entry_ids)

    matched_child_map: dict[int, list[int]] = {}
    if tag or search:
        parent_ids = [r["id"] for r in rows if r["category"] in ("playlist", "list", "blog")]
        if parent_ids:
            ph = ",".join("?" * len(parent_ids))
            cq = f"SELECT id, parent_id FROM entries WHERE parent_id IN ({ph})"  # nosec B608
            cp = list(parent_ids)
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
        d = row_to_dict(r)
        d["list_ids"] = list_map.get(r["id"], [])
        if r["category"] in ("playlist", "list", "blog"):
            d["matched_child_ids"] = matched_child_map.get(r["id"], [])
        result.append(d)
    return jsonify(result), 200


@bp.route("/entries/<int:entry_id>/read", methods=["PATCH"])
def toggle_read(entry_id):
    db = get_db()
    row = db.execute("SELECT read FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    new_read = 0 if row["read"] else 1
    db.execute("UPDATE entries SET read = ? WHERE id = ?", (new_read, entry_id))
    db.commit()
    return jsonify({"id": entry_id, "read": bool(new_read)}), 200


@bp.route("/entries/<int:entry_id>", methods=["PATCH"])
def update_entry(entry_id):
    body = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    custom_slugs = {r["slug"] for r in db.execute("SELECT slug FROM custom_categories").fetchall()}
    valid_cats = cfg.BUILTIN_CATS | custom_slugs
    updates = {}
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
    set_clause = ", ".join(f"{k} = ?" for k in updates)  # nosec B608
    db.execute(f"UPDATE entries SET {set_clause} WHERE id = ?", [*updates.values(), entry_id])  # nosec B608
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return jsonify(row_to_dict(row, db)), 200


@bp.route("/entries/<int:entry_id>", methods=["DELETE"])
def delete_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM entries WHERE parent_id = ?", (entry_id,))
    db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    db.commit()
    return "", 204


@bp.route("/entries/<int:entry_id>/content", methods=["GET"])
def get_content(entry_id):
    row = get_db().execute(
        "SELECT content FROM entries WHERE id = ?", (entry_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"content": row["content"] or ""}), 200


@bp.route("/entries/<int:entry_id>/retry-summary", methods=["POST"])
def retry_summary(entry_id):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    content = row["content"] or ""
    if not content.strip():
        return jsonify({"error": "No content stored — cannot retry"}), 400
    custom_cats = [dict(r) for r in db.execute("SELECT slug, label FROM custom_categories ORDER BY id").fetchall()]
    try:
        result, _ = call_gemini(content, custom_cats)
        result["category"] = "video"
        tags = [t for t in result["tags"] if t != "summary-failed"]
        db.execute(
            "UPDATE entries SET name=?, bullets=?, category=?, tags=? WHERE id=?",
            (result["name"], json.dumps(result["bullets"]), "video",
             json.dumps(tags), entry_id),
        )
        db.commit()
        try:
            store_entry_embedding(db, entry_id, result["name"], result["bullets"], tags, content)
        except Exception as exc:
            logger.error("Retry embed failed for %d: %s", entry_id, exc)
        row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return jsonify(row_to_dict(row, db)), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/entries/<int:entry_id>/children", methods=["GET"])
def get_children(entry_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (entry_id,)
    ).fetchall()
    return jsonify([row_to_dict(r, db) for r in rows]), 200


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
@bp.route("/tags", methods=["GET"])
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
@bp.route("/suggest", methods=["GET"])
def suggest():
    exclude = request.args.get("exclude", "")
    db = get_db()
    q = "SELECT * FROM entries WHERE read = 0 AND source = 'manual'"
    params: list = []
    if exclude:
        q += " AND id != ?"
        params.append(int(exclude))
    q += " ORDER BY RANDOM() LIMIT 1"
    row = db.execute(q, params).fetchone()
    if not row:
        return jsonify(None), 200
    d = row_to_dict(row, db)
    if row["content"]:
        d["preview"] = row["content"][:400].strip()
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# Autocomplete search
# ---------------------------------------------------------------------------
@bp.route("/entries/search")
def search_entries_autocomplete():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([]), 200
    db = get_db()
    like = f"%{q}%"
    rows = db.execute(
        "SELECT id, name, url, category FROM entries WHERE parent_id IS NULL"
        " AND (name LIKE ? OR url LIKE ?) ORDER BY name LIMIT 20",
        (like, like),
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200
