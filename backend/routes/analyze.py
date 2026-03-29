"""
Samuraizer – Analyze routes.
/analyze, /analyze-pdf, /analyze-blog, /scan-blog, /entries/<id>/pdf
"""

import json
import sqlite3

from flask import Blueprint, request, jsonify, Response, stream_with_context
from scrapling import Fetcher as ScraplingFetcher

import backend.config as cfg
from backend.logging_setup import logger
from backend.database import row_to_dict
from backend.services.processors import process_url, process_pdf, process_file_upload, process_blog_listing
from backend.services.content import extract_blog_links

bp = Blueprint("analyze", __name__)


@bp.route("/analyze", methods=["POST"])
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
            for event in process_url(url):
                if event["type"] == "log":
                    yield json.dumps({"url": url, "log": event["msg"]}) + "\n"
                elif event["type"] == "result":
                    yield json.dumps({"url": url, "entry": event["entry"]}) + "\n"
                elif event["type"] == "error":
                    yield json.dumps({"url": url, "error": event["msg"]}) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


@bp.route("/analyze-pdf", methods=["POST"])
def analyze_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename or not uploaded.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a .pdf"}), 400
    filename = uploaded.filename
    file_bytes = uploaded.read()
    logger.info("Analyze-PDF request: %s (%d bytes)", filename, len(file_bytes))

    def generate():
        for event in process_pdf(file_bytes, filename):
            if event["type"] == "log":
                yield json.dumps({"url": filename, "log": event["msg"]}) + "\n"
            elif event["type"] == "result":
                yield json.dumps({"url": filename, "entry": event["entry"]}) + "\n"
            elif event["type"] == "error":
                yield json.dumps({"url": filename, "error": event["msg"]}) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@bp.route("/analyze-file", methods=["POST"])
def analyze_file():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "Filename missing"}), 400

    filename = uploaded.filename
    file_bytes = uploaded.read()
    logger.info("Analyze-file request: %s (%d bytes)", filename, len(file_bytes))

    def generate():
        for event in process_file_upload(file_bytes, filename):
            if event["type"] == "log":
                yield json.dumps({"url": filename, "log": event["msg"]}) + "\n"
            elif event["type"] == "result":
                yield json.dumps({"url": filename, "entry": event["entry"]}) + "\n"
            elif event["type"] == "error":
                yield json.dumps({"url": filename, "error": event["msg"]}) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@bp.route("/entries/<int:entry_id>/pdf", methods=["GET", "OPTIONS"])
def download_pdf(entry_id):
    db = sqlite3.connect(cfg.DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("SELECT url, name, pdf_data FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        if not row["pdf_data"]:
            return jsonify({"error": "No PDF stored for this entry"}), 404
        filename = (row["name"] or f"entry-{entry_id}").replace("/", "_") + ".pdf"
        filename = filename.encode("latin-1", "replace").decode("latin-1")
        disposition = "attachment" if request.args.get("dl") else "inline"
        return Response(
            bytes(row["pdf_data"]),
            mimetype="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        )
    finally:
        db.close()


@bp.route("/scan-blog", methods=["POST"])
def scan_blog():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON body"}), 400
    url = str(body.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Missing or invalid url"}), 400
    try:
        page = ScraplingFetcher().get(url, timeout=20)
        links = extract_blog_links(url, page)
        title_els = page.css("title")
        blog_title = (title_els[0].text if title_els else "") or url
        return jsonify({"title": blog_title, "links": links})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/analyze-blog", methods=["POST"])
def analyze_blog():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON body"}), 400
    url = str(body.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Missing or invalid url"}), 400

    selected_urls = body.get("selected_urls")
    listing_title = body.get("listing_title")

    logger.info("Analyze-blog request: %s (%s articles selected)",
                url, len(selected_urls) if selected_urls else "all")

    def generate():
        for event in process_blog_listing(url, selected_urls=selected_urls, listing_title=listing_title):
            if event["type"] == "log":
                yield json.dumps({"url": url, "log": event["msg"]}) + "\n"
            elif event["type"] == "result":
                yield json.dumps({"url": url, "entry": event["entry"]}) + "\n"
            elif event["type"] == "error":
                yield json.dumps({"url": url, "error": event["msg"]}) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")
