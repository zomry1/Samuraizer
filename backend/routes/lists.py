"""
Samuraizer – Lists and custom categories routes.
"""

import re
import json

from flask import Blueprint, request, jsonify

import backend.config as cfg
from backend.database import get_db

bp = Blueprint("lists", __name__)


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------
@bp.route("/lists", methods=["GET"])
def get_lists():
    db = get_db()
    rows = db.execute("""
        SELECT l.id, l.name, l.created_at,
               COUNT(le.entry_id) as entry_count
        FROM lists l
        LEFT JOIN list_entries le ON le.list_id = l.id
        GROUP BY l.id ORDER BY l.created_at DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@bp.route("/lists", methods=["POST"])
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


@bp.route("/lists/<int:list_id>", methods=["PATCH"])
def rename_list(list_id):
    body = request.get_json(silent=True)
    name = (body or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    db = get_db()
    db.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id))
    db.commit()
    return jsonify({"id": list_id, "name": name}), 200


@bp.route("/lists/<int:list_id>", methods=["DELETE"])
def delete_list(list_id):
    db = get_db()
    db.execute("DELETE FROM lists WHERE id = ?", (list_id,))
    db.commit()
    return "", 204


@bp.route("/lists/<int:list_id>/entries", methods=["POST"])
def add_to_list(list_id):
    body = request.get_json(silent=True)
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


@bp.route("/lists/<int:list_id>/entries/<int:entry_id>", methods=["DELETE"])
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
@bp.route("/categories", methods=["GET"])
def get_categories():
    rows = get_db().execute("SELECT * FROM custom_categories ORDER BY created_at").fetchall()
    return jsonify([dict(r) for r in rows]), 200


@bp.route("/categories", methods=["POST"])
def create_category():
    body = request.get_json(silent=True) or {}
    label = body.get("label", "").strip()
    color = body.get("color", "#94a3b8").strip()
    if not label:
        return jsonify({"error": "label required"}), 400
    slug = re.sub(r"[^a-z0-9\-]", "", label.lower().replace(" ", "-"))
    if not slug:
        return jsonify({"error": "invalid label"}), 400
    if slug in cfg.BUILTIN_CATS:
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


@bp.route("/categories/<slug>", methods=["DELETE"])
def delete_category(slug):
    db = get_db()
    db.execute("DELETE FROM custom_categories WHERE slug = ?", (slug,))
    db.commit()
    return "", 204
