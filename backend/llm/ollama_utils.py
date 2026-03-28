"""
Samuraizer – Ollama SDK helpers.
Lazy client creation, model listing, status checks, pre-flight diagnostics.
"""

import time

import ollama as _ollama_mod

import backend.config as cfg
from backend.logging_setup import ollama_logger


# ---------------------------------------------------------------------------
# Lazy Ollama client singleton
# ---------------------------------------------------------------------------
_ollama_client: _ollama_mod.Client | None = None


def get_ollama_client() -> _ollama_mod.Client:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = _ollama_mod.Client(host=cfg.OLLAMA_URL)
    return _ollama_client


def reset_ollama_client():
    """Force re-creation on next use (e.g. after URL change)."""
    global _ollama_client
    _ollama_client = None


# Re-export the module-level ResponseError for callers that need to catch it.
OllamaResponseError = _ollama_mod.ResponseError


# ---------------------------------------------------------------------------
# Model listing & status
# ---------------------------------------------------------------------------
def ollama_list_models() -> list[dict]:
    client = get_ollama_client()
    data = client.list()
    models = []

    if hasattr(data, "models"):
        entries = data.models or []
    elif isinstance(data, (list, tuple)) and len(data) == 2 and data[0] == "models":
        entries = data[1] or []
    else:
        try:
            entries = list(data)
        except Exception:
            entries = []

    for m in entries:
        if isinstance(m, dict):
            name = m.get("name") or m.get("model")
            size = m.get("size", None)
            status = m.get("status", "installed")
        else:
            name = getattr(m, "name", None) or getattr(m, "model", None)
            size = getattr(m, "size", None)
            status = getattr(m, "status", "installed")

        status = status or "installed"
        models.append({"name": name, "size": size, "status": status})
    return models


def ollama_model_status(model_name: str) -> dict:
    """Check if a model is currently loaded.
    Returns {"loaded": bool, "size_gb": float|None, "detail": str}."""
    try:
        models = ollama_list_models()
        base = model_name.split(":")[0]
        for m in models:
            if m.get("name", "").startswith(base):
                size = m.get("size")
                if isinstance(size, str) and size.lower().endswith("gb"):
                    try:
                        size_gb = float(size[:-2])
                    except Exception:
                        size_gb = None
                elif isinstance(size, (int, float)):
                    size_gb = float(size) / (1024 ** 3)
                else:
                    size_gb = None
                return {"loaded": True,
                        "size_gb": round(size_gb, 1) if size_gb is not None else None,
                        "detail": m.get("name", model_name)}
        return {"loaded": False, "size_gb": None, "detail": model_name}
    except Exception:
        return {"loaded": False, "size_gb": None, "detail": model_name}


def ollama_pre_flight_logs() -> list[str]:
    """Diagnostic messages about Ollama readiness (pre-LLM-call)."""
    if cfg.LLM_PROVIDER != "ollama":
        return []
    logs = []
    status = ollama_model_status(cfg.OLLAMA_MODEL)
    if status["loaded"]:
        logs.append(f"Ollama model {status['detail']} is loaded ({status['size_gb']} GB)")
    else:
        logs.append(
            f"Ollama model {cfg.OLLAMA_MODEL} is not loaded "
            "\u2014 it will be loaded on first request (this may take a while)"
        )
    logs.append(
        f"Analyzing with Ollama ({cfg.OLLAMA_MODEL}) "
        "\u2014 duration depends on your local hardware"
    )
    return logs


def extract_ollama_stats(resp) -> str:
    """Build a human-readable stats line from an Ollama ChatResponse."""
    prompt_eval_s = (resp.prompt_eval_duration or 0) / 1e9
    eval_s        = (resp.eval_duration or 0) / 1e9
    load_s        = (resp.load_duration or 0) / 1e9
    total_s       = (resp.total_duration or 0) / 1e9
    eval_count    = resp.eval_count or 0
    prompt_count  = resp.prompt_eval_count or 0
    tok_per_s     = eval_count / eval_s if eval_s > 0 else 0
    return (
        f"Ollama stats \u2014 total: {total_s:.1f}s, "
        f"load: {load_s:.1f}s, "
        f"prompt eval: {prompt_eval_s:.1f}s ({prompt_count} tokens), "
        f"generation: {eval_s:.1f}s ({eval_count} tokens, {tok_per_s:.1f} tok/s)"
    )
