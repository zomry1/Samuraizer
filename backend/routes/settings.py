"""
Samuraizer – Settings, provider info, and Ollama management routes.
"""

import json
import subprocess
import os

from flask import Blueprint, request, jsonify, Response, stream_with_context

import backend.config as cfg
from backend.llm import prompts
from backend.llm.ollama_utils import get_ollama_client, ollama_list_models
from backend.services.env_file import read_env_file, write_env_file, reload_provider_settings

bp = Blueprint("settings", __name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@bp.route("/settings", methods=["GET"])
def get_settings():
    env = read_env_file()
    return jsonify({
        "provider": env.get("LLM_PROVIDER", cfg.LLM_PROVIDER),
        "gemini_api_key": env.get("GEMINI_API_KEY", ""),
        "ollama_url": env.get("OLLAMA_URL", cfg.OLLAMA_URL),
        "ollama_model": env.get("OLLAMA_MODEL", cfg.OLLAMA_MODEL),
        "ollama_embed_model": env.get("OLLAMA_EMBED_MODEL", cfg.OLLAMA_EMBED_MODEL),
        "system_prompt_base": env.get("SYSTEM_PROMPT_BASE", prompts.SYSTEM_PROMPT_BASE),
        "chat_system_prompt": env.get("CHAT_SYSTEM_PROMPT", prompts.CHAT_SYSTEM_PROMPT),
        "ollama_chat_options": env.get("OLLAMA_CHAT_OPTIONS", json.dumps(cfg.OLLAMA_CHAT_OPTIONS, indent=2)),
        "ollama_analyze_options": env.get("OLLAMA_ANALYZE_OPTIONS", json.dumps(cfg.OLLAMA_ANALYZE_OPTIONS, indent=2)),
        "gemini_models": [
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro",
        ],
        "ollama_models": [
            "qwen3:4b", "qwen3:8b", "qwen3:14b", "qwen3:30b",
        ],
        "ollama_embedding_models": [
            "qwen3-embedding:8b", "embeddinggemma:300m", "nomic-embed-text:v1.5"
        ],
    })


@bp.route("/settings", methods=["POST"])
def update_settings():
    body = request.get_json(silent=True)
    if not body or not isinstance(body, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    provider = str(body.get("provider", cfg.LLM_PROVIDER)).strip().lower()
    if provider not in ("gemini", "ollama"):
        return jsonify({"error": "Invalid provider"}), 400

    gemini_api_key = str(body.get("gemini_api_key", "")).strip()
    ollama_url = str(body.get("ollama_url", cfg.OLLAMA_URL)).strip() or cfg.OLLAMA_URL
    ollama_model = str(body.get("ollama_model", cfg.OLLAMA_MODEL)).strip() or cfg.OLLAMA_MODEL
    ollama_embed_model = str(body.get("ollama_embed_model", cfg.OLLAMA_EMBED_MODEL)).strip() or cfg.OLLAMA_EMBED_MODEL
    system_prompt_base = str(body.get("system_prompt_base", prompts.SYSTEM_PROMPT_BASE)).strip()
    chat_system_prompt = str(body.get("chat_system_prompt", prompts.CHAT_SYSTEM_PROMPT)).strip()
    ollama_chat_options = str(body.get("ollama_chat_options", json.dumps(cfg.OLLAMA_CHAT_OPTIONS))).strip()
    ollama_analyze_options = str(body.get("ollama_analyze_options", json.dumps(cfg.OLLAMA_ANALYZE_OPTIONS))).strip()

    updates = {
        "LLM_PROVIDER": provider,
        "OLLAMA_URL": ollama_url,
        "OLLAMA_MODEL": ollama_model,
        "OLLAMA_EMBED_MODEL": ollama_embed_model,
        "GEMINI_API_KEY": gemini_api_key,
        "SYSTEM_PROMPT_BASE": system_prompt_base,
        "CHAT_SYSTEM_PROMPT": chat_system_prompt,
        "OLLAMA_CHAT_OPTIONS": ollama_chat_options,
        "OLLAMA_ANALYZE_OPTIONS": ollama_analyze_options,
    }

    try:
        write_env_file(updates)
        reload_provider_settings()
    except Exception as exc:
        return jsonify({"error": f"Could not write .env: {exc}"}), 500

    return jsonify({"ok": True, "provider": provider}), 200


# ---------------------------------------------------------------------------
# Provider info
# ---------------------------------------------------------------------------
@bp.route("/provider")
def get_provider():
    if cfg.LLM_PROVIDER == "ollama":
        models = [{"id": m, "label": m} for m in sorted(cfg.VALID_CHAT_MODELS_OLLAMA)]
        default = cfg.OLLAMA_MODEL
    else:
        models = [
            {"id": "gemini-2.5-flash", "label": "2.5 Flash (fast)"},
            {"id": "gemini-2.5-pro",   "label": "2.5 Pro (deep)"},
            {"id": "gemini-1.5-flash", "label": "1.5 Flash"},
            {"id": "gemini-1.5-pro",   "label": "1.5 Pro"},
        ]
        default = cfg.GEMINI_MODEL_NAME
    return jsonify({"provider": cfg.LLM_PROVIDER, "models": models, "default_model": default})


# ---------------------------------------------------------------------------
# Ollama management
# ---------------------------------------------------------------------------
@bp.route("/ollama/status")
def ollama_status():
    try:
        models = ollama_list_models()
        return jsonify({"running": True, "models": models}), 200
    except Exception as exc:
        return jsonify({"running": False, "models": [], "error": str(exc)}), 200


@bp.route("/ollama/pull", methods=["POST"])
def ollama_pull():
    body = request.get_json(silent=True) or {}
    model = str(body.get("model", "")).strip()
    if not model:
        return jsonify({"error": "Model parameter required"}), 400

    def generate():
        yield json.dumps({"type": "started", "message": f"Pulling model {model}..."}) + "\n"
        try:
            client = get_ollama_client()
            for chunk in client.pull(model, stream=True):
                if hasattr(chunk, "message") and chunk.message:
                    text = str(chunk.message).strip()
                    if text:
                        yield json.dumps({"type": "progress", "line": text}) + "\n"
                elif hasattr(chunk, "status"):
                    yield json.dumps({"type": "progress", "line": str(chunk.status)}) + "\n"
            yield json.dumps({"type": "complete", "model": model}) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@bp.route("/ollama/serve", methods=["POST"])
def ollama_serve():
    if cfg.OLLAMA_SERVE_PROCESS and cfg.OLLAMA_SERVE_PROCESS.poll() is None:
        return jsonify({
            "ok": True,
            "message": "Ollama serve already running",
            "pid": cfg.OLLAMA_SERVE_PROCESS.pid,
        }), 200
    try:
        cfg.OLLAMA_SERVE_PROCESS = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
            text=True,
        )
        return jsonify({
            "ok": True,
            "message": "Ollama serve started",
            "pid": cfg.OLLAMA_SERVE_PROCESS.pid,
        }), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
