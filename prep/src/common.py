"""Utilidades comunes del pipeline de preprocesamiento FIRMS.

Convenciones:
- Todas las rutas de `config/params.yaml` son relativas a `prep/`.
- Cada script de etapa construye un `RunContext` con `RunContext.from_cli(__file__)`.
- Los artefactos intermedios se escriben de forma atómica en `prep/data/interim/`.
- Los conteos y tiempos de cada etapa se guardan en `data/interim/stats/<etapa>.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform

# Los boundaries del IGN son GeoJSON con features enormes; GDAL los rechaza
# con el límite por defecto. Debe quedar antes de abrir cualquier capa.
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd
import yaml

PREP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PREP_ROOT / "config" / "params.yaml"


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

def load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    path = Path(path)
    if not path.is_absolute():
        path = (PREP_ROOT / path).resolve()
    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"Config inválida: {path}")
    return cfg


def save_resolved_config(cfg: dict[str, Any], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)
    os.replace(tmp, dest)


def params_sha256(cfg: dict[str, Any]) -> str:
    payload = json.dumps(cfg, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Rutas y contexto de corrida
# ---------------------------------------------------------------------------

@dataclass
class Paths:
    prep_root: Path
    cfg: dict[str, Any]

    def get(self, *keys: str) -> Path:
        node: Any = self.cfg["paths"]
        for key in keys:
            node = node[key]
        return (self.prep_root / str(node)).resolve()

    def ensure(self, *keys: str) -> Path:
        path = self.get(*keys)
        path.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class RunContext:
    cfg: dict[str, Any]
    prep_root: Path
    stage: str
    smoke: bool = False
    smoke_case: str | None = None
    force: bool = False
    report_only: bool = False
    gpu: Any = None
    paths: Paths = field(init=False)
    stats: "Stats" = field(init=False)
    log: logging.Logger = field(init=False)
    started_at: datetime = field(init=False)
    run_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.paths = Paths(self.prep_root, self.cfg)
        self.started_at = datetime.now(timezone.utc)
        self.run_id = self.started_at.strftime("%Y%m%dT%H%M%SZ") + f"-{self.stage}"
        self.log = _build_logger(self.stage, self.log_dir())
        self.stats = Stats(self)

    # -- carpetas ----------------------------------------------------------
    def _smoke_root(self) -> Path:
        case = self.smoke_case or "default"
        return self.prep_root / "data" / "smoke" / case

    def interim_dir(self) -> Path:
        path = self._smoke_root() / "interim" if self.smoke else self.paths.get("interim")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def processed_dir(self) -> Path:
        path = self._smoke_root() / "processed" if self.smoke else self.paths.get("processed")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def qgis_dir(self) -> Path:
        path = self._smoke_root() / "qgis" if self.smoke else self.paths.get("qgis")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def stats_dir(self) -> Path:
        path = self._smoke_root() / "stats" if self.smoke else self.paths.get("stats")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def log_dir(self) -> Path:
        path = self.prep_root / "data" / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def aux_dir(self) -> Path:
        # Los auxiliares (AP, boundaries, landcover) son globales, no del smoke.
        path = self.paths.get("interim") / "aux"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def duckdb_tmp_dir(self) -> Path:
        base = self.paths.get("interim") / "duckdb_tmp"
        if self.smoke:
            base = self._smoke_root() / "interim" / "duckdb_tmp"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def interim(self, name: str) -> Path:
        return self.interim_dir() / name

    def processed(self, name: str) -> Path:
        return self.processed_dir() / name

    # -- CLI ---------------------------------------------------------------
    @classmethod
    def from_cli(cls, stage: str, argv: list[str] | None = None) -> "RunContext":
        parser = argparse.ArgumentParser(description=f"Etapa {stage} del preprocesamiento FIRMS")
        parser.add_argument("--config", default=str(DEFAULT_CONFIG))
        parser.add_argument("--smoke", action="store_true")
        parser.add_argument("--smoke-case", default=None)
        parser.add_argument("--smoke-years", default=None,
                            help="Años de archivo para el smoke, separados por coma (ej. 2025)")
        parser.add_argument("--smoke-api", default=None,
                            help="Ventana API para el smoke: YYYY-MM-DD:YYYY-MM-DD")
        parser.add_argument("--years", default=None,
                            help="Filtro de años para corrida normal, separados por coma")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--report-only", action="store_true",
                            help="Sólo valida y regenera report.md con las salidas existentes")
        parser.add_argument("--gpu", action="store_true",
                            help="Habilita GPU (por defecto CPU; ver benchmark en params.yaml)")
        parser.add_argument("--no-gpu", action="store_true")
        args = parser.parse_args(argv)

        cfg = load_config(args.config)
        if args.smoke:
            cfg.setdefault("run", {}).setdefault("smoke", {})
            cfg["run"]["smoke"]["enabled"] = True
            if args.smoke_years:
                cfg["run"]["smoke"]["years"] = [int(y) for y in args.smoke_years.split(",")]
            if args.smoke_api:
                cfg["run"]["smoke"]["api_window"] = args.smoke_api.split(":")
        if args.years:
            cfg.setdefault("run", {})["years"] = [int(y) for y in args.years.split(",")]
        if args.gpu:
            cfg.setdefault("gpu", {})["enabled"] = True
            # Forzar GPU también en lotes chicos, para experimentos.
            cfg["gpu"]["min_bin_points"] = 0
            cfg["gpu"]["min_type_inference_rows"] = 0
        if args.no_gpu:
            cfg.setdefault("gpu", {})["enabled"] = False

        ctx = cls(
            cfg=cfg,
            prep_root=PREP_ROOT,
            stage=stage,
            smoke=args.smoke,
            smoke_case=args.smoke_case,
            force=args.force,
            report_only=args.report_only,
        )
        ctx.log.info("Etapa %s | smoke=%s | case=%s | config=%s",
                     stage, ctx.smoke, ctx.smoke_case, args.config)
        return ctx

    # -- GPU ---------------------------------------------------------------
    def init_gpu(self) -> Any:
        from gpu import detect_gpu  # import local para no exigir CUDA
        self.gpu = detect_gpu(self.cfg)
        if self.gpu.available:
            self.log.info("GPU activa: %s (%.1f GB)", self.gpu.name, self.gpu.vram_gb)
        else:
            self.log.warning("GPU no disponible: %s", self.gpu.reason)
        return self.gpu


class Stats:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self._t0 = time.perf_counter()
        self.metrics: dict[str, Any] = {}
        self.tables: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.timings: dict[str, float] = {}

    def add(self, key: str, value: Any) -> None:
        self.metrics[key] = value

    def table(self, key: str, rows: Iterable[Any]) -> None:
        self.tables[key] = list(rows)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        self.ctx.log.warning(message)

    @contextmanager
    def timing(self, label: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.timings[label] = round(time.perf_counter() - start, 3)

    def flush(self) -> Path:
        payload = {
            "stage": self.ctx.stage,
            "run_id": self.ctx.run_id,
            "smoke": self.ctx.smoke,
            "smoke_case": self.ctx.smoke_case,
            "started_at": self.ctx.started_at.isoformat(),
            "duration_s": round(time.perf_counter() - self._t0, 3),
            "params_sha256": params_sha256(self.ctx.cfg),
            "git_commit": git_commit(self.ctx.prep_root.parent),
            "platform": platform.platform(),
            "versions": versions(),
            "metrics": self.metrics,
            "tables": self.tables,
            "timings_s": self.timings,
            "warnings": self.warnings,
        }
        dest = self.ctx.stats_dir() / f"{self.ctx.stage}.json"
        atomic_write_json(dest, payload)
        return dest


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _build_logger(stage: str, log_dir: Path) -> logging.Logger:
    logger = logging.getLogger(f"prep.{stage}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    file_handler = logging.FileHandler(log_dir / f"{stage}.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# DuckDB
# ---------------------------------------------------------------------------

def open_duckdb(ctx: RunContext) -> duckdb.DuckDBPyConnection:
    cfg = ctx.cfg.get("run", {}).get("duckdb", {})
    con = duckdb.connect()
    con.execute(f"SET threads={int(cfg.get('threads', 8))}")
    con.execute(f"SET memory_limit='{cfg.get('memory_limit', '6GB')}'")
    con.execute(f"SET temp_directory='{ctx.duckdb_tmp_dir()}'")
    con.execute(f"SET preserve_insertion_order={str(bool(cfg.get('preserve_insertion_order', True))).lower()}")
    return con


# ---------------------------------------------------------------------------
# Archivos y hashes
# ---------------------------------------------------------------------------

def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(dest: Path, payload: dict[str, Any]) -> None:
    ensure_parent(dest)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, dest)


def write_parquet_atomic(df: pd.DataFrame, dest: Path, **kwargs: Any) -> None:
    ensure_parent(dest)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    df.to_parquet(tmp, index=False, compression="zstd", **kwargs)
    os.replace(tmp, dest)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns)


# ---------------------------------------------------------------------------
# Metadatos
# ---------------------------------------------------------------------------

def versions() -> dict[str, str]:
    packages = {
        "duckdb": "duckdb", "pandas": "pandas", "pyarrow": "pyarrow",
        "numpy": "numpy", "scipy": "scipy", "shapely": "shapely",
        "pyproj": "pyproj", "geopandas": "geopandas", "pyogrio": "pyogrio",
        "rasterio": "rasterio", "pyyaml": "pyyaml", "pytest": "pytest",
        "cupy": "cupy-cuda12x", "cuml": "cuml-cu12", "cudf": "cudf-cu12",
        "cugraph": "cugraph-cu12", "cuspatial": "cuspatial-cu12",
    }
    out: dict[str, str] = {}
    for label, dist in packages.items():
        try:
            out[label] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            out[label] = "not-installed"
    return out


def git_commit(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


# ---------------------------------------------------------------------------
# Smoke / filtros
# ---------------------------------------------------------------------------

def smoke_years(ctx: RunContext) -> list[int] | None:
    if not ctx.smoke:
        years = ctx.cfg.get("run", {}).get("years")
        return list(years) if years else None
    return ctx.cfg.get("run", {}).get("smoke", {}).get("years")


def smoke_api_window(ctx: RunContext) -> tuple[str, str] | None:
    if not ctx.smoke:
        return None
    window = ctx.cfg.get("run", {}).get("smoke", {}).get("api_window")
    if not window:
        return None
    return str(window[0]), str(window[1])
