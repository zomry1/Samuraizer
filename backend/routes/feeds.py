"""
Samuraizer – RSS feed and YouTube channel subscription routes.
"""

import sqlite3
import threading

from flask import Blueprint, request, jsonify

import backend.config as cfg
from backend.database import get_db
from backend.services.content import (
    extract_video_id,
    resolve_yt_channel,
    YT_FEED_URL,
)
from backend.services.feeds import (
    poll_rss_feed,
    poll_yt_channel,
    analyze_selected_yt_videos,
)

bp = Blueprint("feeds", __name__)


# ---------------------------------------------------------------------------
# RSS Feed API routes
# ---------------------------------------------------------------------------
@bp.route("/rss-feeds", methods=["GET"])
def list_rss_feeds():
    db = get_db()
    # NOTE (logic debt): entry_count counts ALL RSS entries globally, not per-feed.
    # Preserved from original code.
    feeds = []
    for r in db.execute(
        "SELECT id, url, name, last_checked, created_at FROM rss_feeds ORDER BY created_at DESC"
    ).fetchall():
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


@bp.route("/rss-feeds", methods=["POST"])
def add_rss_feed():
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
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


@bp.route("/rss-feeds/<int:feed_id>", methods=["DELETE"])
def delete_rss_feed(feed_id):
    db = get_db()
    db.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
    db.commit()
    return "", 204


@bp.route("/rss-feeds/<int:feed_id>/poll", methods=["POST"])
def poll_rss_feed_endpoint(feed_id):
    db = get_db()
    row = db.execute("SELECT id, url FROM rss_feeds WHERE id = ?", (feed_id,)).fetchone()
    if not row:
        return jsonify({"error": "Feed not found"}), 404
    # Use a fresh connection so poll_rss_feed can commit independently
    poll_db = sqlite3.connect(cfg.DB_PATH)
    poll_db.row_factory = sqlite3.Row
    try:
        added = poll_rss_feed(poll_db, row["id"], row["url"])
    finally:
        poll_db.close()
    return jsonify({"added": added}), 200


# ---------------------------------------------------------------------------
# YouTube channel subscriptions
# ---------------------------------------------------------------------------
@bp.route("/yt-channels",                  methods=["OPTIONS"])
@bp.route("/yt-channels/preview",          methods=["OPTIONS"])
@bp.route("/yt-channels/<int:cid>",        methods=["OPTIONS"])
@bp.route("/yt-channels/<int:cid>/poll",   methods=["OPTIONS"])
def yt_channels_options(*args, **kwargs):
    resp = jsonify({})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp, 204


@bp.route("/yt-channels/preview", methods=["POST"])
def preview_yt_channel():
    import feedparser

    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"}), 400
    try:
        channel_id, channel_name = resolve_yt_channel(url)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 400
    feed_url = YT_FEED_URL.format(channel_id=channel_id)
    try:
        parsed = feedparser.parse(feed_url)
    except Exception as exc:
        return jsonify({"error": f"Failed to fetch channel feed: {exc}"}), 500
    videos = []
    for item in parsed.entries:
        video_url = item.get("link", "").strip()
        if not video_url or not extract_video_id(video_url):
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


@bp.route("/yt-channels", methods=["GET"])
def list_yt_channels():
    db = get_db()
    rows = db.execute(
        "SELECT id, channel_id, channel_url, name, last_checked, created_at "
        "FROM yt_channels ORDER BY created_at DESC"
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


@bp.route("/yt-channels", methods=["POST"])
def add_yt_channel():
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    name = str(body.get("name", "")).strip()
    analyze_urls = body.get("analyze_urls")  # list[str] | None
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"}), 400
    try:
        channel_id, resolved_name = resolve_yt_channel(url)
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
        db.execute(
            "UPDATE yt_channels SET last_checked = datetime('now') WHERE id = ?",
            (channel_db_id,),
        )
        db.commit()
        if analyze_urls:
            t = threading.Thread(
                target=analyze_selected_yt_videos,
                args=(channel_db_id, analyze_urls),
                daemon=True,
            )
            t.start()
    return jsonify(dict(row)), 201


@bp.route("/yt-channels/<int:cid>", methods=["DELETE"])
def delete_yt_channel(cid):
    db = get_db()
    db.execute("DELETE FROM yt_channels WHERE id = ?", (cid,))
    db.commit()
    return "", 204


@bp.route("/yt-channels/<int:cid>/poll", methods=["POST"])
def poll_yt_channel_endpoint(cid):
    db = get_db()
    row = db.execute(
        "SELECT id, channel_id, name FROM yt_channels WHERE id = ?", (cid,)
    ).fetchone()
    if not row:
        return jsonify({"error": "Channel not found"}), 404
    poll_db = sqlite3.connect(cfg.DB_PATH)
    poll_db.row_factory = sqlite3.Row
    try:
        added = poll_yt_channel(poll_db, row)
    finally:
        poll_db.close()
    return jsonify({"added": added}), 200
