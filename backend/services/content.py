"""
Samuraizer – Content fetchers.
GitHub repos, YouTube videos/playlists, web articles.
"""

import os
import re
import time

import requests
import trafilatura

import backend.config as cfg


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
GH_REPO_RE = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?(?:/.*)?$"
)
_GH_RAW = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
_GH_TREE = "https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
_GH_BRANCHES = ["main", "master", "develop"]


def fetch_github_content(url: str) -> tuple[str, list[str]]:
    m = GH_REPO_RE.match(url)
    owner, repo = m.group("owner"), m.group("repo")
    logs, parts = [], []
    default_branch = "main"

    logs.append(f"GitHub repo detected: {owner}/{repo}")

    for branch in _GH_BRANCHES:
        try:
            r = requests.get(_GH_RAW.format(owner=owner, repo=repo, branch=branch),
                             headers=cfg.GITHUB_HEADERS, timeout=15)
            if r.status_code == 200:
                parts.append(f"# README\n\n{r.text}")
                default_branch = branch
                logs.append(f"README fetched from branch '{branch}' ({len(r.text):,} chars)")
                break
        except requests.RequestException as exc:
            logs.append(f"Branch '{branch}' failed: {exc}")

    if not any("README fetched" in l for l in logs):
        logs.append("No README found — continuing with file tree only")

    try:
        r = requests.get(_GH_TREE.format(owner=owner, repo=repo, branch=default_branch),
                         headers=cfg.GITHUB_HEADERS, timeout=15)
        if r.status_code == 200:
            paths = [i["path"] for i in r.json().get("tree", []) if i.get("type") == "blob"]
            parts.append(f"# File Tree\n\n```\n{chr(10).join(paths[:200])}\n```")
            logs.append(f"File tree fetched ({len(paths)} files)")
        else:
            logs.append(f"File tree returned HTTP {r.status_code}")
    except Exception as exc:
        logs.append(f"File tree fetch failed: {exc}")

    if not parts:
        raise RuntimeError("No content retrieved")

    content = "\n\n---\n\n".join(parts)
    logs.append(f"Total content size: {len(content):,} chars")
    return content, logs


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------
YT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:"
    r"youtube\.com/watch\?(?:.*&)?v=(?P<v1>[A-Za-z0-9_-]{11})"
    r"|youtu\.be/(?P<v2>[A-Za-z0-9_-]{11})"
    r"|youtube\.com/shorts/(?P<v3>[A-Za-z0-9_-]{11})"
    r")"
)
YT_PLAYLIST_RE = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?(?:.*&)?list=(?P<list>[A-Za-z0-9_-]+)"
)
YT_OEMBED = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
YT_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def extract_video_id(url: str) -> str | None:
    m = YT_RE.search(url)
    if not m:
        return None
    return m.group("v1") or m.group("v2") or m.group("v3")


def extract_playlist_id(url: str) -> str | None:
    m = YT_PLAYLIST_RE.search(url)
    return m.group("list") if m else None


def fetch_youtube_content(url: str) -> tuple[str, list[str], str]:
    logs = []
    video_id = extract_video_id(url)
    if not video_id:
        raise RuntimeError("Could not extract YouTube video ID from URL")

    logs.append(f"YouTube video detected (id={video_id})")

    # Fetch title via oEmbed
    title = f"YouTube video {video_id}"
    try:
        r = requests.get(YT_OEMBED.format(video_id=video_id), timeout=10)
        if r.status_code == 200:
            data = r.json()
            title = data.get("title", title)
            author = data.get("author_name", "")
            logs.append(f'Title: "{title}" by {author}')
    except Exception as exc:
        logs.append(f"oEmbed fetch failed (non-fatal): {exc}")

    # Fetch transcript
    transcript_api_key = cfg.TRANSCRIPT_API_KEY
    if not transcript_api_key:
        raise RuntimeError("TRANSCRIPTAPI key not set in .env")

    headers = {"Authorization": f"Bearer {transcript_api_key}"}
    transcript_text = None
    last_error = None
    for attempt in range(3):
        try:
            tr = requests.get(
                "https://transcriptapi.com/api/v2/youtube/transcript",
                params={"video_url": video_id, "format": "text", "include_timestamp": "false"},
                headers=headers,
                timeout=30,
            )
            if tr.status_code == 200:
                data = tr.json()
                transcript_text = data.get("transcript", "")
                logs.append(f"Transcript fetched ({len(transcript_text):,} chars)")
                break
            elif tr.status_code in (408, 503):
                wait = 2 ** attempt
                logs.append(f"Transcript API returned {tr.status_code}, retrying in {wait}s\u2026")
                time.sleep(wait)
                last_error = f"HTTP {tr.status_code}"
            elif tr.status_code == 429:
                retry_after = int(tr.headers.get("Retry-After", 5))
                logs.append(f"Transcript API rate-limited, retrying in {retry_after}s\u2026")
                time.sleep(retry_after)
                last_error = "rate limited"
            elif tr.status_code == 404:
                raise RuntimeError("No transcript available for this video")
            elif tr.status_code == 402:
                raise RuntimeError("Transcript API credits exhausted \u2014 top up at transcriptapi.com")
            elif tr.status_code == 401:
                raise RuntimeError("TRANSCRIPTAPI key is invalid")
            else:
                raise RuntimeError(f"Transcript API error: HTTP {tr.status_code} \u2014 {tr.text[:200]}")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Transcript API request failed: {exc}")

    if not transcript_text:
        raise RuntimeError(f"Failed to fetch transcript after 3 attempts ({last_error})")

    content = f"# {title}\n\nYouTube URL: {url}\n\n## Transcript\n\n{transcript_text}"
    logs.append(f"Total content size: {len(content):,} chars")
    return content, logs, title


def resolve_yt_channel(url: str) -> tuple[str, str]:
    """Return (channel_id, channel_name) for a YouTube channel URL."""
    try:
        from pytubefix import Channel
        ch = Channel(url)
        channel_id = ch.channel_id
        channel_name = ch.channel_name or ch.title or url
        if not channel_id:
            raise RuntimeError("Could not resolve channel ID")
        return channel_id, channel_name
    except Exception as exc:
        raise RuntimeError(f"Failed to resolve YouTube channel: {exc}")


# ---------------------------------------------------------------------------
# Web articles
# ---------------------------------------------------------------------------
def fetch_article_content(url: str, return_title: bool = False):
    logs = ["Article URL detected \u2014 fetching with trafilatura"]
    t0 = time.time()

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise RuntimeError("Failed to download page")
    logs.append(f"Page downloaded in {time.time() - t0:.1f}s \u2014 extracting text")

    text = trafilatura.extract(downloaded, include_tables=True, no_fallback=False)
    if not text or len(text.strip()) < 80:
        raise RuntimeError("Extracted content too short or empty")

    logs.append(f"Text extracted ({len(text):,} chars)")
    if return_title:
        meta = trafilatura.extract_metadata(downloaded)
        title = (meta.title or "").strip() if meta else ""
        return text, logs, title
    return text, logs


# ---------------------------------------------------------------------------
# Blog listing detection + link extraction
# ---------------------------------------------------------------------------
BLOG_PATH_RE = re.compile(
    r"/(blog|posts?|articles?|news|research|writings?|thoughts?|insights?)"
    r"(?:/(?:page/\d+/?)?)?$",
    re.IGNORECASE,
)
_SKIP_PATH_RE = re.compile(
    r"/(tag|author|category|categories|search|feed|rss|page/\d)",
    re.IGNORECASE,
)
_SKIP_EXT_RE = re.compile(r"\.(pdf|zip|png|jpg|jpeg|gif|svg|ico|css|js)$", re.IGNORECASE)


def is_blog_listing_url(url: str) -> bool:
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    if not path or path == "":
        return False
    return bool(BLOG_PATH_RE.search(url))


def extract_blog_links(base_url: str, page) -> list[dict]:
    """Extract article links from a scrapling page object."""
    from urllib.parse import urlparse, urljoin
    base = urlparse(base_url)
    base_root = f"{base.scheme}://{base.netloc}"
    seen = set()
    result = []

    elements = page.css("a") or []
    for a in elements:
        try:
            attrib = a.attrib or {}
            href = attrib.get("href") or a.get("href") or ""
        except Exception:
            continue
        href = str(href).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        if href.startswith("//"):
            href = base.scheme + ":" + href
        elif href.startswith("/"):
            href = base_root + href
        elif not href.startswith("http"):
            href = urljoin(base_url, href)

        try:
            parsed = urlparse(href)
        except Exception:
            continue
        if parsed.netloc != base.netloc:
            continue
        if _SKIP_PATH_RE.search(parsed.path):
            continue
        if _SKIP_EXT_RE.search(parsed.path):
            continue

        path_clean = parsed.path.strip("/")
        if len(path_clean) < 2 or "/" not in path_clean and len(path_clean) < 5:
            continue

        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if clean in seen or clean == base_url.rstrip("/"):
            continue
        seen.add(clean)

        try:
            anchor = (a.text or "").strip()
            if not anchor:
                anchor = " ".join(t.strip() for t in (a.get_all_text(separator=" ") or "").split() if t.strip())
        except Exception:
            anchor = ""
        result.append({"url": clean, "title": anchor[:150]})

    return result
