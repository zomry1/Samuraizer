"""
Samuraizer – .env file read/write and provider settings reload.
"""

import os
import json

from google import genai

import backend.config as cfg
from backend.llm.ollama_utils import reset_ollama_client
from backend.llm import prompts


def read_env_file() -> dict:
    path = os.path.join(cfg.BASE_DIR, ".env")
    if not os.path.exists(path):
        return {}
    data = {}

    def decode_value(val: str):
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            try:
                return json.loads(val)
            except Exception:
                val = val[1:-1]
        try:
            return bytes(val, "utf-8").decode("unicode_escape")
        except Exception:
            return val

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            data[key.strip()] = decode_value(val.strip())
    return data


def write_env_file(updates: dict):
    path = os.path.join(cfg.BASE_DIR, ".env")
    lines = []
    seen = set()

    def encode_value(val):
        if not isinstance(val, str):
            val = str(val)
        if "\n" in val or "\"" in val or "'" in val or val.strip() != val:
            return json.dumps(val, ensure_ascii=False)
        return val

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    lines.append(line)
                    continue
                key, _ = stripped.split("=", 1)
                key = key.strip()
                if key in updates:
                    lines.append(f"{key}={encode_value(updates[key])}\n")
                    seen.add(key)
                else:
                    lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={encode_value(value)}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def reload_provider_settings():
    """Re-read .env and update all mutable provider config in backend.config."""
    env = read_env_file()
    cfg.LLM_PROVIDER = env.get("LLM_PROVIDER", cfg.LLM_PROVIDER).strip().lower()
    cfg.GEMINI_API_KEY = env.get("GEMINI_API_KEY", cfg.GEMINI_API_KEY).strip()
    cfg.OLLAMA_URL = env.get("OLLAMA_URL", cfg.OLLAMA_URL).strip().rstrip("/")
    cfg.OLLAMA_MODEL = env.get("OLLAMA_MODEL", cfg.OLLAMA_MODEL).strip()
    cfg.OLLAMA_EMBED_MODEL = env.get("OLLAMA_EMBED_MODEL", cfg.OLLAMA_EMBED_MODEL).strip()

    prompts.SYSTEM_PROMPT_BASE = env.get("SYSTEM_PROMPT_BASE", prompts.SYSTEM_PROMPT_BASE)
    prompts.CHAT_SYSTEM_PROMPT = env.get("CHAT_SYSTEM_PROMPT", prompts.CHAT_SYSTEM_PROMPT)

    def _parse_options(value, fallback):
        if not value:
            return fallback
        try:
            opts = json.loads(value)
            if isinstance(opts, dict):
                return opts
        except Exception:
            pass
        return fallback

    cfg.OLLAMA_CHAT_OPTIONS = _parse_options(
        env.get("OLLAMA_CHAT_OPTIONS", json.dumps(cfg.OLLAMA_CHAT_OPTIONS)),
        cfg.OLLAMA_CHAT_OPTIONS,
    )
    cfg.OLLAMA_ANALYZE_OPTIONS = _parse_options(
        env.get("OLLAMA_ANALYZE_OPTIONS", json.dumps(cfg.OLLAMA_ANALYZE_OPTIONS)),
        cfg.OLLAMA_ANALYZE_OPTIONS,
    )

    cfg.genai_client = genai.Client(api_key=cfg.GEMINI_API_KEY) if cfg.GEMINI_API_KEY else None
    cfg.VALID_CHAT_MODELS_OLLAMA = {cfg.OLLAMA_MODEL}
    cfg.VALID_CHAT_MODELS = cfg.VALID_CHAT_MODELS_GEMINI | cfg.VALID_CHAT_MODELS_OLLAMA

    reset_ollama_client()
