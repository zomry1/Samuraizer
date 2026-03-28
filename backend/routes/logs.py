"""
Samuraizer – Log viewer routes.
"""

from flask import Blueprint, request, jsonify

from backend.logging_setup import memory_log_handler

bp = Blueprint("logs", __name__)


@bp.route("/logs")
def get_log_entries():
    since = request.args.get("since", 0, type=int)
    return jsonify(memory_log_handler.get_since(since)), 200


@bp.route("/logs", methods=["DELETE"])
def clear_log_entries():
    memory_log_handler.clear()
    return jsonify({"ok": True}), 200
