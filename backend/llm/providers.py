"""
Samuraizer – LLM call implementations (Gemini + Ollama) and shared helpers.
"""

import re
import json
import time

import json_repair
from google.genai import types as genai_types

import backend.config as cfg
from backend.logging_setup import logger, ollama_logger
from backend.llm.prompts import build_system_prompt, CHAT_SYSTEM_PROMPT
from backend.llm.ollama_utils import (
    get_ollama_client,
    OllamaResponseError,
    extract_ollama_stats,
)


# ---------------------------------------------------------------------------
# JSON schema for structured Ollama output
# ---------------------------------------------------------------------------
OLLAMA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets":  {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string"},
        "tags":     {"type": "array", "items": {"type": "string"}},
    },
    "required": ["bullets", "category", "tags"],
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def sanitize_content(content: str, max_chars: int = 120_000) -> str:
    """Strip control chars and cap length for LLM input."""
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", content)
    effective_max = 30_000 if cfg.LLM_PROVIDER == "ollama" else max_chars
    if len(content) > effective_max:
        content = content[:effective_max] + "\n\n[content truncated]"
    return content


def parse_llm_json(raw: str, custom_cats: list, logs: list) -> dict:
    """Extract and validate the structured JSON from an LLM response string."""
    # Strip <think>…</think> blocks (qwen3 reasoning traces)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    logs.append(f"Raw LLM response ({len(raw):,} chars): {raw[:200]}{'…' if len(raw) > 200 else ''}")

    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

    # Extract first complete JSON object via bracket counting
    start = raw.find('{')
    if start == -1:
        raise RuntimeError(f"No JSON object found in response: {raw[:200]}")
    depth = 0
    end = start
    for i, ch in enumerate(raw[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    raw = raw[start:end + 1]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json_repair.loads(raw)
        except Exception as repair_exc:
            raise RuntimeError(f"LLM returned unparseable JSON: {repair_exc} — raw: {raw[:300]}")

    valid = {"tool", "agent", "mcp", "list", "workflow", "cve", "article", "video", "playlist"} | {c["slug"] for c in custom_cats}
    name = str(parsed.get("name", parsed.get("title", ""))).strip()

    # Accept alternate field names for bullets
    bullets_raw = parsed.get("bullets") or parsed.get("key_points") or parsed.get("summary") or parsed.get("highlights") or []
    if isinstance(bullets_raw, str):
        bullets_raw = [bullets_raw]
    bullets = [str(b).strip() for b in bullets_raw if str(b).strip()][:3]

    # Last resort: synthesize bullets from description field
    if not bullets:
        desc = str(parsed.get("description", parsed.get("overview", ""))).strip()
        if desc:
            bullets = [desc[:100]]
            logs.append("No 'bullets' field — synthesized from description")

    category = str(parsed.get("category", "")).strip().lower()
    category = re.sub(r"[^a-z0-9\-]", "-", category).strip("-")
    if category == "skill":
        category = "agent"
    tags = [
        re.sub(r"[^a-z0-9\-]", "", str(t).strip().lower().replace(" ", "-"))
        for t in parsed.get("tags", [])
        if str(t).strip()
    ]
    tags = [t for t in tags if t][:20]

    if not bullets:
        preview = json.dumps(parsed, ensure_ascii=False)[:300]
        raise RuntimeError(f"LLM returned no bullets — parsed JSON: {preview}")
    if category not in valid:
        logs.append(f"Unknown category '{category}' — defaulting to 'article'")
        category = "article"

    logs.append(f"Classified as: {category} — \"{name}\" — tags: {', '.join(tags)}")
    return {"name": name, "bullets": bullets, "category": category, "tags": tags}


# ---------------------------------------------------------------------------
# Gemini implementation
# ---------------------------------------------------------------------------
def call_gemini_impl(content: str, custom_cats: list = []) -> tuple[dict, list[str]]:
    logs = []
    if not cfg.GEMINI_API_KEY:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")

    logs.append(f"Sending {len(content):,} chars to {cfg.GEMINI_MODEL_NAME}...")
    t0 = time.time()

    content = sanitize_content(content)

    response = cfg.genai_client.models.generate_content(
        model=cfg.GEMINI_MODEL_NAME,
        contents=content,
        config=genai_types.GenerateContentConfig(
            system_instruction=build_system_prompt(custom_cats),
            temperature=0.1,
            max_output_tokens=1024,
            response_mime_type="application/json",
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )

    elapsed = time.time() - t0
    raw = response.text.strip()
    logs.append(f"Gemini responded in {elapsed:.1f}s")

    result = parse_llm_json(raw, custom_cats, logs)
    return result, logs


# ---------------------------------------------------------------------------
# Ollama implementation
# ---------------------------------------------------------------------------
def call_ollama(content: str, custom_cats: list = [], purpose: str = "analyze") -> tuple[dict, list[str]]:
    logs = []
    t0 = time.time()

    content = sanitize_content(content)
    if purpose == "chat":
        system_prompt = CHAT_SYSTEM_PROMPT
        options = cfg.OLLAMA_CHAT_OPTIONS
    else:
        system_prompt = build_system_prompt(custom_cats)
        options = cfg.OLLAMA_ANALYZE_OPTIONS

    ollama_logger.debug(
        "REQUEST — model=%s, purpose=%s, system_prompt=%d chars, content=%d chars",
        cfg.OLLAMA_MODEL, purpose, len(system_prompt), len(content),
    )
    logs.append(f"Sending {len(content):,} chars to Ollama ({cfg.OLLAMA_MODEL})...")

    try:
        client = get_ollama_client()
        stream = client.chat(
            model=cfg.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": content},
            ],
            stream=True,
            think=True,
            format=OLLAMA_JSON_SCHEMA,
            options=options,
        )
    except OllamaResponseError as e:
        raise RuntimeError(f"Ollama error: {e}") from e
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            raise EnvironmentError(
                f"Cannot connect to Ollama at {cfg.OLLAMA_URL}. "
                f"Make sure Ollama is running (ollama serve) and the model is pulled:\n"
                f"  ollama pull {cfg.OLLAMA_MODEL}"
            ) from e
        raise

    # Stream response, accumulate tokens
    chunks = []
    last_resp = None
    for chunk in stream:
        token = chunk.message.content or ""
        if token:
            chunks.append(token)
        last_resp = chunk

    raw = "".join(chunks).strip()
    elapsed = time.time() - t0

    stats_line = extract_ollama_stats(last_resp) if last_resp else f"Ollama responded in {elapsed:.1f}s"
    logs.append(f"Ollama responded in {elapsed:.1f}s ({len(raw):,} chars)")
    logs.append(stats_line)

    ollama_logger.info(stats_line)
    ollama_logger.debug("RESPONSE (%d chars): %s", len(raw), raw[:2000])
    if len(raw) > 2000:
        ollama_logger.debug("RESPONSE (continued): %s", raw[2000:])

    result = parse_llm_json(raw, custom_cats, logs)
    return result, logs


# ---------------------------------------------------------------------------
# Dispatcher (keeps the call_gemini name so call-sites stay uniform)
# ---------------------------------------------------------------------------
def call_gemini(content: str, custom_cats: list = []) -> tuple[dict, list[str]]:
    if cfg.LLM_PROVIDER == "ollama":
        return call_ollama(content, custom_cats)
    return call_gemini_impl(content, custom_cats)
