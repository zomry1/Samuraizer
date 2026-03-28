"""
Samuraizer – URL / PDF / playlist / blog-listing processing generators.
Each generator owns its own DB connection and yields {type: log|result|error} events.
"""

import os
import json
import hashlib
import sqlite3

import requests
import fitz  # PyMuPDF
from urllib.parse import urlparse
from scrapling import Fetcher as ScraplingFetcher

import backend.config as cfg
from backend.logging_setup import logger
from backend.database import row_to_dict, get_or_create_list, add_entries_to_list
from backend.llm.providers import call_gemini
from backend.llm.embeddings import store_entry_embedding
from backend.llm.ollama_utils import ollama_pre_flight_logs
from backend.services.content import (
    GH_REPO_RE,
    extract_video_id,
    extract_playlist_id,
    fetch_github_content,
    fetch_youtube_content,
    fetch_article_content,
    is_blog_listing_url,
    extract_blog_links,
    YT_OEMBED,
)


# ---------------------------------------------------------------------------
# Playlist processor
# ---------------------------------------------------------------------------
def process_playlist(url: str):
    def log(msg):
        logger.info("[%s] %s", url, msg)
        return {"type": "log", "msg": msg}

    db = sqlite3.connect(cfg.DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        custom_cats = [dict(r) for r in db.execute("SELECT slug, label FROM custom_categories ORDER BY id").fetchall()]
        row = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        if row:
            yield log("Cache hit — returning saved playlist")
            children = db.execute(
                "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (row["id"],)
            ).fetchall()
            d = row_to_dict(row, db)
            d["children"] = [row_to_dict(c, db) for c in children]
            yield {"type": "result", "entry": d}
            return

        yield log("Playlist URL detected — fetching video list")

        try:
            from pytubefix import Playlist
            pl = Playlist(url)
            pl_title = pl.title
            video_urls = list(pl.video_urls)[:50]
            yield log(f'Playlist: "{pl_title}" — {len(video_urls)} videos')
        except Exception as exc:
            yield {"type": "error", "msg": f"Failed to fetch playlist: {exc}"}
            return

        video_summaries = []
        new_entry_ids = []

        for i, vid_url in enumerate(video_urls):
            yield log(f"[{i+1}/{len(video_urls)}] {vid_url}")
            existing = db.execute("SELECT * FROM entries WHERE url = ?", (vid_url,)).fetchone()
            if existing:
                yield log(f"  \u21a9 already in KB: {existing['name']}")
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
                content, fetch_logs = fetch_youtube_content(vid_url)
                vid_id_str = extract_video_id(vid_url)
                try:
                    r = requests.get(YT_OEMBED.format(video_id=vid_id_str), timeout=5)
                    if r.status_code == 200:
                        vid_name = r.json().get("title", vid_name)
                except Exception:
                    pass
                for msg in fetch_logs:
                    yield log(f"  {msg}")
                for msg in ollama_pre_flight_logs():
                    yield log(f"  {msg}")
                result, gemini_logs = call_gemini(content, custom_cats)
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
                    store_entry_embedding(db, cur.lastrowid, result["name"],
                                          result["bullets"], result["tags"], content)
                    yield log("  embedding stored")
                except Exception as exc:
                    yield log(f"  embedding skipped: {exc}")
                new_entry_ids.append(cur.lastrowid)
                video_summaries.append(result)
                yield log(f"  \u2713 {result['name']}")
            except Exception as exc:
                yield log(f"  \u2717 {exc} — saving placeholder")
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

        yield log("Generating playlist summary\u2026")
        summary_text = f"# Playlist: {pl_title}\n\n"
        for i, vs in enumerate(video_summaries):
            summary_text += f"## Video {i+1}: {vs['name']}\n"
            for b in vs["bullets"]:
                summary_text += f"- {b}\n"
            summary_text += f"Tags: {', '.join(vs['tags'])}\n\n"

        try:
            pl_result, gemini_logs = call_gemini(summary_text, custom_cats)
            pl_result["category"] = "playlist"
            pl_result["name"] = pl_title or url
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
            store_entry_embedding(db, playlist_id, pl_result["name"],
                                  pl_result["bullets"], pl_result["tags"], summary_text)
            yield log("Embedding stored")
        except Exception as exc:
            yield log(f"Embedding skipped: {exc}")

        row = db.execute("SELECT * FROM entries WHERE id = ?", (playlist_id,)).fetchone()
        children = db.execute(
            "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (playlist_id,)
        ).fetchall()
        d = row_to_dict(row, db)
        d["children"] = [row_to_dict(c, db) for c in children]
        yield {"type": "result", "entry": d}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Blog listing processor
# ---------------------------------------------------------------------------
def process_blog_listing(url: str, selected_urls: list | None = None, listing_title: str | None = None):
    def log(msg):
        logger.info("[blog-list] %s", msg)
        return {"type": "log", "msg": msg}

    db = sqlite3.connect(cfg.DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        site_host = (urlparse(url).hostname or "").replace("www.", "")
        site_name = site_host or listing_title or url
        custom_cats = [dict(r) for r in db.execute(
            "SELECT slug, label FROM custom_categories ORDER BY id"
        ).fetchall()]
        existing_parent = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        link_title_map: dict[str, str] = {}

        if selected_urls is None:
            if existing_parent:
                yield log("Cache hit — returning saved listing")
                yield {"type": "result", "entry": row_to_dict(existing_parent, db)}
                return

        if selected_urls is not None:
            article_urls = selected_urls
            listing_title = listing_title or url
        else:
            yield log("Blog listing detected — fetching page\u2026")
            try:
                page = ScraplingFetcher().get(url, timeout=20)
            except Exception as exc:
                yield {"type": "error", "msg": f"Failed to fetch listing page: {exc}"}
                return

            links = extract_blog_links(url, page)
            if len(links) < 2:
                yield {"type": "error", "msg": "No article links detected on this page"}
                return

            article_urls = [lnk["url"] for lnk in links]
            link_title_map = {lnk["url"]: (lnk.get("title") or "").strip() for lnk in links}
            title_els = page.css("title")
            listing_title = (title_els[0].text if title_els else "") or urlparse(url).path or url

        site_name = site_host or listing_title or url

        yield log(f"Analyzing {len(article_urls)} articles — '{listing_title}'")

        article_summaries = []
        new_entry_ids = []

        for idx, art_url in enumerate(article_urls, 1):
            yield log(f"[{idx}/{len(article_urls)}] {art_url}")
            content = ""
            try:
                cached = db.execute("SELECT * FROM entries WHERE url = ?", (art_url,)).fetchone()
                if cached:
                    yield log("  \u21a9 already in KB")
                    e = row_to_dict(cached, db)
                    cached_name = (e.get("name") or "").strip()
                    link_name = link_title_map.get(art_url, "")
                    new_entry_ids.append(cached["id"])
                    article_summaries.append({
                        "name": link_name or cached_name or art_url,
                        "bullets": json.loads(cached["bullets"]) if isinstance(cached["bullets"], str) else e["bullets"],
                        "tags": json.loads(cached["tags"]) if isinstance(cached["tags"], str) else e["tags"],
                    })
                    continue

                content, fetch_logs, page_title = fetch_article_content(art_url, return_title=True)
                for msg in fetch_logs:
                    yield log(f"  {msg}")
                for msg in ollama_pre_flight_logs():
                    yield log(f"  {msg}")
                result, gemini_logs = call_gemini(content, custom_cats)
                result["category"] = "article"
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
                        store_entry_embedding(db, cur.lastrowid, result["name"],
                                              result["bullets"], result["tags"], content)
                        yield log("  embedding stored")
                    except Exception as exc:
                        yield log(f"  embedding skipped: {exc}")
                    new_entry_ids.append(cur.lastrowid)
                article_summaries.append(result)
                yield log(f"  \u2713 {result['name']}")
            except Exception as exc:
                yield log(f"  \u2717 {exc} — skipping")
                article_summaries.append({"name": art_url, "bullets": [], "tags": []})

        if not article_summaries:
            yield {"type": "error", "msg": "No articles could be processed"}
            return

        yield log("Generating listing summary\u2026")
        summary_text = f"# Blog: {listing_title}\n\n"
        summary_text += f"Website: {site_name}\nURL: {url}\n\n"
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
            list_result, gemini_logs = call_gemini(summary_text, custom_cats)
            list_result["category"] = "blog"
            list_result["name"] = site_name
            for msg in gemini_logs:
                yield log(msg)
        except Exception as exc:
            yield {"type": "error", "msg": f"Listing summary failed: {exc}"}
            return

        if existing_parent:
            listing_id = existing_parent["id"]
            db.execute(
                "UPDATE entries SET name = ?, bullets = ?, category = ?, tags = ? WHERE id = ?",
                (list_result["name"], json.dumps(list_result["bullets"]),
                 "blog", json.dumps(list_result["tags"]), listing_id),
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
                store_entry_embedding(db, listing_id, list_result["name"],
                                      list_result["bullets"], list_result["tags"], summary_text)
                yield log("Listing embedding stored")
            except Exception as exc:
                yield log(f"Listing embedding skipped: {exc}")

        if listing_id and new_entry_ids:
            db.executemany(
                "UPDATE entries SET parent_id = ? WHERE id = ?",
                [(listing_id, eid) for eid in new_entry_ids],
            )
            db.commit()

        if new_entry_ids:
            auto_list_name = site_name or listing_title or url
            auto_list_id = get_or_create_list(db, auto_list_name)
            add_entries_to_list(db, auto_list_id, new_entry_ids)
            yield log(f"Added {len(new_entry_ids)} articles to list '{auto_list_name}'")

        children = [row_to_dict(r, db) for r in db.execute(
            "SELECT * FROM entries WHERE parent_id = ? ORDER BY id", (listing_id,)
        ).fetchall()] if listing_id else []

        parent_row = db.execute("SELECT * FROM entries WHERE id = ?", (listing_id,)).fetchone()
        if parent_row:
            entry = row_to_dict(parent_row, db)
            entry["children"] = children
            yield {"type": "result", "entry": entry}
        else:
            yield {"type": "error", "msg": "Failed to save listing entry"}

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Single URL processor
# ---------------------------------------------------------------------------
def process_url(url: str, source: str = "manual"):
    if extract_playlist_id(url):
        yield from process_playlist(url)
        return

    if is_blog_listing_url(url):
        yield from process_blog_listing(url)
        return

    def log(msg):
        logger.info("[%s] %s", url, msg)
        return {"type": "log", "msg": msg}

    db = sqlite3.connect(cfg.DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        custom_cats = [dict(r) for r in db.execute("SELECT slug, label FROM custom_categories ORDER BY id").fetchall()]
        row = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        if row:
            bullets_raw = row["bullets"] or "[]"
            if not row["name"] or bullets_raw in ("", "[]"):
                db.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
                db.commit()
                yield log("Removed incomplete cached entry — re-analyzing")
            else:
                yield log("Cache hit — returning saved entry")
                yield {"type": "result", "entry": row_to_dict(row, db)}
                return

        yield log("Starting analysis")

        deterministic_name = None
        deterministic_category = None
        try:
            if extract_video_id(url):
                content, fetch_logs, page_title = fetch_youtube_content(url)
                deterministic_name = page_title or url
                deterministic_category = "video"
            elif GH_REPO_RE.match(url):
                content, fetch_logs = fetch_github_content(url)
                gh_match = GH_REPO_RE.match(url)
                deterministic_name = f"{gh_match.group('repo')}" if gh_match else url
            else:
                content, fetch_logs, page_title = fetch_article_content(url, return_title=True)
                deterministic_name = page_title or url
            for msg in fetch_logs:
                yield log(msg)
        except Exception as exc:
            msg = f"Fetch failed: {exc}"
            logger.error("[%s] %s", url, msg)
            yield {"type": "error", "msg": msg}
            return

        for msg in ollama_pre_flight_logs():
            yield log(msg)

        try:
            result, gemini_logs = call_gemini(content, custom_cats)
            for msg in gemini_logs:
                yield log(msg)
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
            store_entry_embedding(db, cur.lastrowid, result["name"],
                                  result["bullets"], result["tags"], content)
            yield log("Embedding stored")
        except Exception as exc:
            yield log(f"Embedding skipped: {exc}")

        row = db.execute("SELECT * FROM entries WHERE url = ?", (url,)).fetchone()
        yield {"type": "result", "entry": row_to_dict(row, db)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PDF processor
# ---------------------------------------------------------------------------
def extract_pdf_text(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    parts = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "".join(parts)


def process_pdf(file_bytes: bytes, filename: str):
    def log(msg):
        logger.info("[pdf:%s] %s", filename, msg)
        return {"type": "log", "msg": msg}

    sha = hashlib.sha256(file_bytes).hexdigest()
    synthetic_url = f"pdf:{sha}"

    db = sqlite3.connect(cfg.DB_PATH)
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
            yield {"type": "result", "entry": row_to_dict(row, db)}
            return

        yield log("Extracting text from PDF")
        try:
            content = extract_pdf_text(file_bytes)
        except Exception as exc:
            yield {"type": "error", "msg": f"PDF extraction failed: {exc}"}
            return

        if not content.strip():
            yield {"type": "error", "msg": "No extractable text — scanned/image-only PDFs are not supported"}
            return

        yield log(f"Extracted {len(content):,} characters")

        for msg in ollama_pre_flight_logs():
            yield log(msg)

        try:
            result, gemini_logs = call_gemini(content, custom_cats)
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

        cur = db.execute(
            "INSERT INTO entries (url, name, bullets, category, tags, content, source, pdf_data) VALUES (?,?,?,?,?,?,?,?)",
            (synthetic_url, entry_name, json.dumps(result["bullets"]),
             "pdf", json.dumps(result["tags"]), content, "pdf", file_bytes),
        )
        db.commit()
        yield log("Saved to knowledge base")

        try:
            store_entry_embedding(db, cur.lastrowid, entry_name,
                                  result["bullets"], result["tags"], content)
            yield log("Embedding stored")
        except Exception as exc:
            yield log(f"Embedding skipped: {exc}")

        row = db.execute("SELECT * FROM entries WHERE url = ?", (synthetic_url,)).fetchone()
        yield {"type": "result", "entry": row_to_dict(row, db)}
    finally:
        db.close()
