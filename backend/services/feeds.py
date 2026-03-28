"""
Samuraizer – RSS feed and YouTube channel polling + schedulers.
"""

import json
import sqlite3
import threading

import feedparser

import backend.config as cfg
from backend.logging_setup import logger
from backend.database import get_or_create_list, add_entries_to_list
from backend.services.content import extract_video_id, YT_FEED_URL
from backend.services.processors import process_url


# ---------------------------------------------------------------------------
# RSS feed polling
# ---------------------------------------------------------------------------
def poll_rss_feed(db, feed_id: int, feed_url: str) -> int:
    """Fetch and parse one RSS/Atom feed; analyse new entries. Returns count added."""
    try:
        parsed = feedparser.parse(feed_url)
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", feed_url, exc)
        return 0

    feed_row = db.execute("SELECT name FROM rss_feeds WHERE id = ?", (feed_id,)).fetchone()
    feed_title = (feed_row["name"] if feed_row and feed_row["name"] else "") or \
                 getattr(getattr(parsed, "feed", None), "title", "") or feed_url
    auto_list_id = get_or_create_list(db, feed_title)

    added = 0
    new_ids = []
    for item in parsed.entries:
        url = item.get("link", "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        existing = db.execute("SELECT id FROM entries WHERE url = ?", (url,)).fetchone()
        if existing:
            add_entries_to_list(db, auto_list_id, [existing["id"]])
            continue
        try:
            entry_id = None
            for event in process_url(url, source="rss"):
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
        add_entries_to_list(db, auto_list_id, new_ids)

    db.execute(
        "UPDATE rss_feeds SET last_checked = datetime('now') WHERE id = ?",
        (feed_id,),
    )
    db.commit()
    logger.info("RSS feed %s polled: %d new entries added to list '%s'", feed_url, added, feed_title)
    return added


def poll_all_feeds():
    """Poll all registered RSS feeds (background scheduler entry point)."""
    db = sqlite3.connect(cfg.DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        feeds = db.execute("SELECT id, url FROM rss_feeds").fetchall()
        for feed in feeds:
            poll_rss_feed(db, feed["id"], feed["url"])
    except Exception as exc:
        logger.error("RSS poll error: %s", exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# YouTube channel polling
# ---------------------------------------------------------------------------
def poll_yt_channel(db, row) -> int:
    """Fetch the latest videos for a YouTube channel. Returns count added."""
    channel_id = row["channel_id"]
    channel_name = row["name"] or channel_id
    feed_url = YT_FEED_URL.format(channel_id=channel_id)

    try:
        parsed = feedparser.parse(feed_url)
    except Exception as exc:
        logger.warning("YT channel feed fetch failed for %s: %s", channel_id, exc)
        return 0

    auto_list_id = get_or_create_list(db, channel_name)

    added = 0
    new_ids = []
    for item in parsed.entries:
        url = item.get("link", "").strip()
        if not url or not extract_video_id(url):
            continue
        existing = db.execute("SELECT id FROM entries WHERE url = ?", (url,)).fetchone()
        if existing:
            add_entries_to_list(db, auto_list_id, [existing["id"]])
            continue
        try:
            entry_id = None
            for event in process_url(url, source="youtube"):
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
        add_entries_to_list(db, auto_list_id, new_ids)

    db.execute(
        "UPDATE yt_channels SET last_checked = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    db.commit()
    logger.info("YT channel %s polled: %d new videos added to list '%s'",
                channel_name, added, channel_name)
    return added


def poll_all_yt_channels():
    """Poll all subscribed YouTube channels."""
    db = sqlite3.connect(cfg.DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        channels = db.execute("SELECT id, channel_id, name FROM yt_channels").fetchall()
        for ch in channels:
            poll_yt_channel(db, ch)
    except Exception as exc:
        logger.error("YT channel poll error: %s", exc)
    finally:
        db.close()


def analyze_selected_yt_videos(channel_db_id: int, urls: list[str]):
    """Background task: analyse specific YT video URLs for a channel."""
    db = sqlite3.connect(cfg.DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            "SELECT id, channel_id, name FROM yt_channels WHERE id = ?", (channel_db_id,)
        ).fetchone()
        if not row:
            return
        auto_list_id = get_or_create_list(db, row["name"] or row["channel_id"])
        new_ids = []
        for url in urls:
            existing = db.execute("SELECT id FROM entries WHERE url = ?", (url,)).fetchone()
            if existing:
                add_entries_to_list(db, auto_list_id, [existing["id"]])
                continue
            try:
                entry_id = None
                for event in process_url(url, source="youtube"):
                    if event.get("type") == "result":
                        entry_id = event["entry"]["id"]
                if entry_id:
                    new_ids.append(entry_id)
            except Exception as exc:
                logger.warning("Selected YT video skipped (%s): %s", url, exc)
        if new_ids:
            add_entries_to_list(db, auto_list_id, new_ids)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def start_rss_scheduler():
    """Recurring background timer: polls all RSS feeds and YT channels every hour."""
    def _run():
        poll_all_feeds()
        poll_all_yt_channels()
        t = threading.Timer(3600, _run)
        t.daemon = True
        t.start()

    initial = threading.Timer(60, _run)
    initial.daemon = True
    initial.start()
    logger.info("RSS/YT scheduler started (first poll in 60s, then every 3600s)")
