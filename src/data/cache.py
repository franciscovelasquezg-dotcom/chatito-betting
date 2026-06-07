"""
Caché local en disco para datos de API-Football.
TTL de 6 horas — evita llamadas repetidas al mismo equipo/fixture.
"""

import json
import os
import time
from pathlib import Path
from loguru import logger

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
TTL = 6 * 3600  # 6 horas en segundos


def _path(key: str) -> Path:
    safe = key.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_")
    return CACHE_DIR / f"{safe}.json"


def get(key: str) -> dict | None:
    p = _path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - data["_ts"] > TTL:
            p.unlink()
            return None
        return data["payload"]
    except Exception:
        return None


def set(key: str, payload: dict) -> None:
    p = _path(key)
    try:
        p.write_text(
            json.dumps({"_ts": time.time(), "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Cache write error {key}: {e}")


def clear_expired() -> None:
    removed = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if time.time() - data["_ts"] > TTL:
                f.unlink()
                removed += 1
        except Exception:
            f.unlink()
    if removed:
        logger.info(f"Cache: {removed} entradas expiradas eliminadas")
