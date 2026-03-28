"""
Samuraizer – Chat routes.
/chat, /chat/sessions, /chat/sessions/<id>/messages
"""

import re
import json
import sqlite3

from flask import Blueprint, request, jsonify, Response, stream_with_context
from google.genai import types as genai_types

import backend.config as cfg
from backend.logging_setup import logger, ollama_logger
from backend.database import get_db
from backend.llm.embeddings import get_embedding, cosine_sim
from backend.llm.prompts import CHAT_SYSTEM_PROMPT
from backend.llm.ollama_utils import (
    get_ollama_client,
    OllamaResponseError,
    extract_ollama_stats,
)

bp = Blueprint("chat", __name__)


def _default_chat_model() -> str:
    return cfg.OLLAMA_MODEL if cfg.LLM_PROVIDER == "ollama" else cfg.GEMINI_MODEL_NAME


@bp.route("/chat/sessions", methods=["GET"])
def list_chat_sessions():
    db = get_db()
    rows = db.execute("""
        SELECT cs.id, cs.title, cs.model, cs.created_at, cs.updated_at,
               COUNT(cm.id) AS message_count
        FROM chat_sessions cs
        LEFT JOIN chat_messages cm ON cm.session_id = cs.id
        GROUP BY cs.id
        ORDER BY cs.updated_at DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@bp.route("/chat/sessions", methods=["POST"])
def create_chat_session():
    body = request.get_json(silent=True) or {}
    model = (body.get("model") or "gemini-2.5-flash").strip()
    title = (body.get("title") or "").strip() or "Untitled"
    db = get_db()
    cur = db.execute(
        "INSERT INTO chat_sessions (title, model) VALUES (?,?)", (title, model)
    )
    db.commit()
    row = db.execute("SELECT * FROM chat_sessions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({**dict(row), "message_count": 0}), 201


@bp.route("/chat/sessions/<int:session_id>", methods=["PATCH"])
def rename_chat_session(session_id):
    body = request.get_json(silent=True) or {}
    title = body.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    db = get_db()
    db.execute(
        "UPDATE chat_sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
        (title, session_id),
    )
    db.commit()
    return jsonify({"id": session_id, "title": title}), 200


@bp.route("/chat/sessions/<int:session_id>", methods=["DELETE"])
def delete_chat_session(session_id):
    db = get_db()
    db.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    db.commit()
    return "", 204


@bp.route("/chat/sessions/<int:session_id>/messages", methods=["GET"])
def get_chat_messages(session_id):
    db = get_db()
    row = db.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    msgs = db.execute(
        "SELECT id, role, text, sources, created_at FROM chat_messages "
        "WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()
    result = []
    for m in msgs:
        d = dict(m)
        try:
            d["sources"] = json.loads(d["sources"] or "[]")
        except Exception:
            d["sources"] = []
        result.append(d)
    return jsonify(result), 200


@bp.route("/chat", methods=["POST"])
def chat():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    session_id = body.get("session_id")
    model_name = (body.get("model") or _default_chat_model()).strip()
    pinned_ids = [int(x) for x in (body.get("pinned_ids") or []) if str(x).isdigit()]

    if not question:
        return jsonify({"error": "question required"}), 400
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    if cfg.LLM_PROVIDER == "gemini" and not cfg.GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500
    if model_name not in cfg.VALID_CHAT_MODELS:
        model_name = _default_chat_model()

    pre_db = get_db()
    session_row = pre_db.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if not session_row:
        return jsonify({"error": "Session not found"}), 404
    session_title = session_row["title"]
    history_rows = pre_db.execute(
        "SELECT role, text FROM chat_messages WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()
    history_data = [(r["role"], r["text"]) for r in history_rows]

    def generate():
        sdb = sqlite3.connect(cfg.DB_PATH)
        sdb.row_factory = sqlite3.Row
        nonlocal session_title
        try:
            sources, context_parts = [], []

            if pinned_ids:
                ph = ",".join("?" * len(pinned_ids))
                entry_rows = sdb.execute(
                    f"SELECT * FROM entries WHERE id IN ({ph})", pinned_ids  # nosec B608
                ).fetchall()
                for row in entry_rows:
                    chunk_rows = sdb.execute(
                        "SELECT chunk_text FROM entry_chunks WHERE entry_id = ? ORDER BY chunk_index",
                        (row["id"],),
                    ).fetchall()
                    if chunk_rows:
                        chunk_text = "\n\n".join(r["chunk_text"] for r in chunk_rows)
                    else:
                        chunk_text = (row["content"] or "").strip()
                    sources.append({"id": row["id"], "name": row["name"],
                                    "url": row["url"], "pinned": True})
                    context_parts.append(f"## {row['name']}\nURL: {row['url']}\n\n{chunk_text}")
            else:
                try:
                    ollama_logger.debug("CHAT EMBED QUERY — question=%d chars", len(question))
                    query_emb = get_embedding(question, task_type="RETRIEVAL_QUERY")
                except Exception as exc:
                    yield json.dumps({"type": "error", "message": f"Embedding failed: {exc}"}) + "\n"
                    return

                chunks = sdb.execute(
                    "SELECT entry_id, chunk_text, embedding FROM entry_chunks"
                ).fetchall()

                total_entries = sdb.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                embedded_ids = set(c["entry_id"] for c in chunks)
                missing_count = total_entries - len(embedded_ids) if total_entries else 0

                if total_entries > 0 and missing_count > 0:
                    logger.warning(
                        "Chat RAG: %d / %d entries have no embeddings — "
                        "run POST /entries/embed-required to rebuild",
                        missing_count, total_entries,
                    )
                    yield json.dumps({
                        "type": "no_rag",
                        "message": f"{missing_count} of {total_entries} entries have no embeddings — "
                                   "chat answers may be incomplete. Re-embed to enable full RAG.",
                        "entry_count": missing_count,
                    }) + "\n"
                elif total_entries == 0:
                    logger.info("Chat RAG: no entries in the knowledge base yet")

                entry_scores: dict = {}
                for chunk in chunks:
                    try:
                        emb = json.loads(chunk["embedding"])
                        sim = cosine_sim(query_emb, emb)
                        eid = chunk["entry_id"]
                        if sim > entry_scores.get(eid, (-1, ""))[0]:
                            entry_scores[eid] = (sim, chunk["chunk_text"])
                    except Exception:
                        continue

                top_entries = sorted(
                    [(eid, sc, txt) for eid, (sc, txt) in entry_scores.items() if sc > 0.2],
                    key=lambda x: -x[1],
                )[:4]

                if top_entries:
                    top_ids = [eid for eid, _, _ in top_entries]
                    ph = ",".join("?" * len(top_ids))
                    entry_rows = sdb.execute(f"SELECT * FROM entries WHERE id IN ({ph})", top_ids).fetchall()  # nosec B608
                    entry_map = {r["id"]: r for r in entry_rows}
                    for eid, score, chunk_text in top_entries:
                        row = entry_map.get(eid)
                        if not row:
                            continue
                        sources.append({"id": eid, "name": row["name"], "url": row["url"],
                                        "score": round(score, 3)})
                        context_parts.append(f"## {row['name']}\nURL: {row['url']}\n\n{chunk_text}")

            yield json.dumps({"type": "sources", "entries": sources}) + "\n"

            context_text = "\n\n---\n\n".join(context_parts)[:24000] if context_parts \
                else "No relevant knowledge base entries found."

            if pinned_ids:
                system_prompt = (
                    "You are a cyber-security expert assistant. "
                    "The user has pinned specific articles/entries for this question. "
                    "Answer ONLY using the pinned entries provided below — do not draw on any other knowledge. "
                    "Cite the entry names you used."
                    "Do not use any internal data you have, just use the PINNED ENTRIES provided."
                    "You are here to help answer the user's question using the PINNED ENTRIES. no addtional info and no corrections to user"
                    "If the answer is not in the pinned entries, say so explicitly.\n\n"
                    f"PINNED ENTRIES:\n{context_text}"
                )
            else:
                system_prompt = CHAT_SYSTEM_PROMPT.format(context=context_text)

            # Stream LLM response
            try:
                if cfg.LLM_PROVIDER == "ollama":
                    messages = [{"role": "system", "content": system_prompt}]
                    for role, text in history_data:
                        messages.append({"role": role if role != "assistant" else "assistant", "content": text})
                    messages.append({"role": "user", "content": question})

                    ollama_logger.debug(
                        "CHAT REQUEST — model=%s, messages=%d, system=%d chars, question=%d chars",
                        model_name, len(messages), len(system_prompt), len(question),
                    )

                    try:
                        chat_client = get_ollama_client()
                        chat_stream = chat_client.chat(
                            model=model_name,
                            messages=messages,
                            stream=True,
                            think='high',
                            options=cfg.OLLAMA_CHAT_OPTIONS,
                        )
                    except OllamaResponseError as e:
                        raise RuntimeError(f"Ollama chat error: {e}") from e
                    except Exception as e:
                        if "connect" in str(e).lower() or "refused" in str(e).lower():
                            raise EnvironmentError(
                                f"Cannot connect to Ollama at {cfg.OLLAMA_URL}. "
                                f"Make sure Ollama is running (ollama serve) and the model is pulled:\n"
                                f"  ollama pull {model_name}"
                            ) from e
                        raise

                    full_response = []
                    last_chunk = None
                    for chunk in chat_stream:
                        text = chunk.message.content or ""
                        if text:
                            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
                            if text:
                                full_response.append(text)
                                yield json.dumps({"type": "chunk", "text": text}) + "\n"
                        last_chunk = chunk
                    assembled = "".join(full_response)
                    assembled = re.sub(r"<think>.*?</think>", "", assembled, flags=re.DOTALL).strip()
                    if last_chunk:
                        ollama_logger.info(extract_ollama_stats(last_chunk))
                    ollama_logger.debug("CHAT RESPONSE (%d chars): %s", len(assembled), assembled[:500])
                else:
                    gemini_contents = []
                    for role, text in history_data:
                        gemini_role = "model" if role == "assistant" else "user"
                        gemini_contents.append({"role": gemini_role, "parts": [{"text": text}]})
                    gemini_contents.append({"role": "user", "parts": [{"text": question}]})

                    stream = cfg.genai_client.models.generate_content_stream(
                        model=model_name,
                        contents=gemini_contents,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.3,
                            max_output_tokens=2048,
                            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                        ),
                    )
                    full_response = []
                    for chunk in stream:
                        text = chunk.text or ""
                        if text:
                            full_response.append(text)
                            yield json.dumps({"type": "chunk", "text": text}) + "\n"
                    assembled = "".join(full_response)

                sdb.execute(
                    "INSERT INTO chat_messages (session_id, role, text, sources) VALUES (?,?,?,?)",
                    (session_id, "user", question, "[]"),
                )
                sdb.execute(
                    "INSERT INTO chat_messages (session_id, role, text, sources) VALUES (?,?,?,?)",
                    (session_id, "assistant", assembled, json.dumps(sources)),
                )
                if not session_title or session_title.strip().lower() == "untitled":
                    session_title = question[:60]
                    sdb.execute(
                        "UPDATE chat_sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
                        (session_title, session_id),
                    )
                else:
                    sdb.execute(
                        "UPDATE chat_sessions SET updated_at = datetime('now') WHERE id = ?",
                        (session_id,),
                    )
                sdb.commit()
            except Exception as exc:
                logger.error("Chat LLM error: %s", exc)
                yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
                return

            yield json.dumps({"type": "done", "title": session_title}) + "\n"

        finally:
            sdb.close()

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")
