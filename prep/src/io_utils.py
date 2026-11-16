"""Descubrimiento de CSV, manifests y escritura atómica de parquet."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from common import RunContext, sha256_file, smoke_api_window, smoke_years

COUNTRY_YEAR_RE = re.compile(r"_(\d{4})_Argentina\.csv$")
API_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d+)d\.csv$")


def _excluded(name: str, cfg: dict[str, Any]) -> bool:
    ingest = cfg.get("ingest", {})
    if any(name.startswith(p) for p in ingest.get("exclude_basename_prefixes", ["._"])):
        return True
    if any(name.endswith(s) for s in ingest.get("exclude_suffixes", [".aux.xml"])):
        return True
    return False


def discover_files(ctx: RunContext) -> pd.DataFrame:
    cfg = ctx.cfg
    raw_root = ctx.paths.get("raw_firms")
    rows: list[dict[str, Any]] = []
    smoke = ctx.smoke
    years = set(smoke_years(ctx) or [])
    api_window = smoke_api_window(ctx)

    for group, spec in cfg["ingest"]["groups"].items():
        pattern = spec["glob"]
        matched = sorted(raw_root.glob(pattern))
        for path in matched:
            if not path.is_file() or _excluded(path.name, cfg):
                continue
            source = "country" if pattern.startswith("country/") else "api"
            # Un smoke de API es API-only: no mezclar archivos country.
            if smoke and api_window is not None and source == "country":
                continue
            record: dict[str, Any] = {
                "group": group,
                "path": str(path),
                "source": source,
                "sensor": spec["sensor"],
                "product": spec["product"],
                "priority": int(cfg["ingest"]["product_priority"][spec["product"]]),
                "size_bytes": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
                "file_start_date": None,
                "window_days": None,
                "sha256": None,
            }
            if source == "country":
                m = COUNTRY_YEAR_RE.search(path.name)
                if not m:
                    continue
                year = int(m.group(1))
                record["file_year"] = year
                record["file_start_date"] = date(year, 1, 1).isoformat()
                record["window_days"] = 366
                if smoke and years and year not in years:
                    continue
                if not smoke and years and year not in years:
                    continue
            else:
                m = API_DATE_RE.search(path.name)
                if not m:
                    continue
                end = date.fromisoformat(m.group(1))
                ndays = int(m.group(2))
                start = end - timedelta(days=ndays - 1)
                record["file_start_date"] = start.isoformat()
                record["file_end_date"] = end.isoformat()
                record["window_days"] = ndays
                if smoke:
                    if api_window is None:
                        # Smoke de archivo: no mezclar API 2026.
                        continue
                    win_start, win_end = (date.fromisoformat(x) for x in api_window)
                    if end < win_start or start > win_end:
                        continue
                elif years and end.year not in years:
                    continue
            rows.append(record)

    manifest = pd.DataFrame(rows)
    if manifest.empty:
        raise RuntimeError("No se encontraron CSV con los filtros actuales")
    manifest = manifest.sort_values(["priority", "path"], kind="stable").reset_index(drop=True)
    manifest["source_file"] = manifest["path"].map(lambda p: Path(p).name)
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _manifest_hash(manifest: pd.DataFrame) -> str:
    import hashlib
    cols = ["path", "size_bytes", "mtime_ns", "group", "priority"]
    payload = manifest[cols].to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def add_file_hashes(manifest: pd.DataFrame, enabled: bool = True) -> pd.DataFrame:
    if not enabled:
        return manifest
    manifest = manifest.copy()
    manifest["sha256"] = [sha256_file(Path(p)) for p in manifest["path"]]
    return manifest


def check_expected_counts(manifest: pd.DataFrame, cfg: dict[str, Any],
                          strict: bool | None = None) -> dict[str, Any]:
    groups_cfg = cfg["ingest"]["groups"]
    strict = cfg["ingest"].get("strict_file_counts", True) if strict is None else strict
    counts = manifest.groupby("group").size().to_dict()
    mismatches = {}
    for group, group_cfg in groups_cfg.items():
        expected = int(group_cfg.get("expected", 0))
        found = int(counts.get(group, 0))
        if expected != found:
            mismatches[group] = {"expected": expected, "found": found}
    if mismatches and strict:
        raise RuntimeError(f"Conteos de archivos inesperados: {mismatches}")
    return {"counts": counts, "mismatches": mismatches}


def iter_parquet_batches(path: Path, columns: list[str] | None = None,
                         batch_size: int = 200_000) -> Iterator[pd.DataFrame]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=batch_size, columns=columns):
        yield batch.to_pandas()


def copy_query_to_parquet(con, query: str, dest: Path,
                          row_group_size: int = 100_000) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    sql = (
        f"COPY ({query}) TO '{tmp}' "
        f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {int(row_group_size)})"
    )
    con.execute(sql)
    os.replace(tmp, dest)


def summary_by(manifest: pd.DataFrame, keys: list[str]) -> list[dict[str, Any]]:
    grouped = manifest.groupby(keys, dropna=False).size().reset_index(name="files")
    return grouped.to_dict(orient="records")
