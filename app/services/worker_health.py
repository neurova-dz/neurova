"""Quick liveness probes for the admin system page."""

from __future__ import annotations

import os
import time
from pathlib import Path

from flask import current_app
from sqlalchemy import text

from app.extensions import celery, db


def ping_db() -> dict:
    t0 = time.perf_counter()
    try:
        db.session.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": int((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def ping_redis() -> dict:
    try:
        import redis

        url = current_app.config.get("CELERY_BROKER_URL")
        if not url:
            return {"ok": False, "error": "no broker URL"}
        r = redis.Redis.from_url(url, socket_timeout=2)
        t0 = time.perf_counter()
        r.ping()
        return {"ok": True, "latency_ms": int((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def ping_celery() -> dict:
    try:
        insp = celery.control.inspect(timeout=1.5)
        pong = insp.ping() or {}
        return {"ok": bool(pong), "workers": list(pong.keys()) if pong else []}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def model_files_present() -> dict:
    paths = {
        "brain": current_app.config.get("BRAIN_MODEL_PATH"),
        "retina": current_app.config.get("RETINA_MODEL_PATH"),
        "retina_thresholds": current_app.config.get("RETINA_THRESHOLDS_PATH"),
    }
    out = {}
    for name, path in paths.items():
        if not path:
            out[name] = {"ok": False, "path": None}
            continue
        p = Path(path)
        out[name] = {
            "ok": p.exists() and p.is_file(),
            "path": str(path),
            "size_bytes": p.stat().st_size if p.exists() and p.is_file() else 0,
        }
    return out


def system_summary() -> dict:
    return {
        "db": ping_db(),
        "redis": ping_redis(),
        "celery": ping_celery(),
        "models": model_files_present(),
        "env": current_app.config.get("NEUROVA_ENV", "development"),
        "pid": os.getpid(),
    }
