"""Utilidades compartidas del pipeline (solo biblioteca estándar)."""
from __future__ import annotations

import os
import ssl
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"

# Bbox de trabajo de Argentina (W,S,E,N). El recorte fino se hace después con el límite del IGN.
ARG_BBOX = "-73.6,-55.1,-53.6,-21.7"


def load_env(path: Path = ROOT / ".env") -> None:
    """Carga variables KEY=VALUE del .env sin pisar las que ya existen."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()


def fetch(url: str, dest: Path, retries: int = 4, timeout: int = 120) -> int:
    """Descarga url a dest de forma atómica (archivo .part + rename). Devuelve los bytes escritos."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fire-calendar-pipeline/0.1"})
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r, open(tmp, "wb") as f:
                n = 0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    n += len(chunk)
            tmp.replace(dest)
            return n
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * attempt)
    raise RuntimeError(f"falló {url}: {last_err}")


def get_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "fire-calendar-pipeline/0.1"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode()
