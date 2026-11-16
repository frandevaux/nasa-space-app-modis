"""Capa GPU opcional (RAPIDS 25.04 / CuPy) con fallback CPU.

Reglas:
- La GPU nunca cambia el resultado: clustering y kNN deben dar la misma
  partición que el camino CPU. `benchmark()` lo verifica.
- Si CUDA no inicializa, `GPUContext.available = False` y los scripts usan CPU.
- No se importa cupy/cuml en el arranque: sólo cuando se pide GPU.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class GPUContext:
    available: bool
    reason: str
    name: str = ""
    vram_gb: float = 0.0
    device: int = 0
    cupy: Any = None
    cuml: Any = None
    cudf: Any = None
    cugraph: Any = None
    cuspatial: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_cuml(self) -> bool:
        return self.cuml is not None


def detect_gpu(cfg: dict[str, Any]) -> GPUContext:
    gpu_cfg = cfg.get("gpu", {})
    if not gpu_cfg.get("enabled", True):
        return GPUContext(False, "gpu.enabled=false")

    try:
        import cupy as cp
    except Exception as exc:  # noqa: BLE001
        return GPUContext(False, f"cupy no importable: {exc}")

    try:
        count = cp.cuda.runtime.getDeviceCount()
    except Exception as exc:  # noqa: BLE001
        return GPUContext(False, f"CUDA no inicializa: {exc}")

    if count == 0:
        return GPUContext(False, "cuda device count = 0")

    device = int(gpu_cfg.get("device", 0))
    try:
        props = cp.cuda.runtime.getDeviceProperties(device)
        name = props["name"].decode() if isinstance(props["name"], bytes) else str(props["name"])
        vram_gb = round(props["totalGlobalMem"] / (1024 ** 3), 2)
        cp.cuda.Device(device).use()
    except Exception as exc:  # noqa: BLE001
        return GPUContext(False, f"no se pudo usar device {device}: {exc}", cupy=cp)

    modules: dict[str, Any] = {}
    reasons: list[str] = []
    for mod_name in ("cuml", "cudf", "cugraph", "cuspatial"):
        try:
            modules[mod_name] = __import__(mod_name)
        except Exception as exc:  # noqa: BLE001
            modules[mod_name] = None
            reasons.append(f"{mod_name}: {exc}")

    reason = "ok" if not reasons else "; ".join(reasons)
    return GPUContext(
        available=True,
        reason=reason,
        name=name,
        vram_gb=vram_gb,
        device=device,
        cupy=cp,
        cuml=modules["cuml"],
        cudf=modules["cudf"],
        cugraph=modules["cugraph"],
        cuspatial=modules["cuspatial"],
    )


# ---------------------------------------------------------------------------
# Clustering exacto por bin: pares (i,j) con d_ij <= r_i + r_j
# ---------------------------------------------------------------------------

def cluster_labels_gpu(x: np.ndarray, y: np.ndarray, r: np.ndarray,
                       tile_points: int = 4096,
                       max_edges: int = 50_000_000,
                       gpu: GPUContext | None = None) -> np.ndarray:
    """Etiquetas de componentes conexas usando distancias pairwise en GPU.

    Para n <= tile_points usa una sola matriz n×n. Para bins más grandes
    procesa por tiles de filas, sin materializar n×n completo.
    """
    if gpu is None or not gpu.available:
        raise RuntimeError("GPU no disponible")
    cp = gpu.cupy
    from cupyx.scipy.sparse import coo_matrix
    from cupyx.scipy.sparse.csgraph import connected_components

    n = int(len(x))
    if n == 0:
        return np.empty(0, dtype=np.int32)
    if n == 1:
        return np.zeros(1, dtype=np.int32)

    xg = cp.asarray(x, dtype=cp.float64)
    yg = cp.asarray(y, dtype=cp.float64)
    rg = cp.asarray(r, dtype=cp.float64)

    row_parts: list[Any] = []
    col_parts: list[Any] = []
    tile = max(256, int(tile_points))
    total_edges = 0

    for start in range(0, n, tile):
        stop = min(start + tile, n)
        dx = xg[start:stop, None] - xg[None, :]
        dy = yg[start:stop, None] - yg[None, :]
        d2 = dx * dx + dy * dy
        thr = rg[start:stop, None] + rg[None, :]
        mask = d2 <= thr * thr
        # Sólo triángulo superior para no duplicar aristas.
        rows_local, cols_global = cp.nonzero(mask)
        if rows_local.size:
            rows_global = rows_local + start
            keep = cols_global > rows_global
            rows_global = rows_global[keep]
            cols_global = cols_global[keep]
            if rows_global.size:
                row_parts.append(rows_global)
                col_parts.append(cols_global)
                total_edges += int(rows_global.size)
                if total_edges > max_edges:
                    raise MemoryError(
                        f"clustering GPU: más de {max_edges} aristas en un bin de {n} puntos"
                    )
        del dx, dy, d2, thr, mask, rows_local, cols_global

    if not row_parts:
        return np.arange(n, dtype=np.int32)

    rows = cp.concatenate(row_parts)
    cols = cp.concatenate(col_parts)
    data = cp.ones(rows.size, dtype=cp.float32)
    graph = coo_matrix((data, (rows, cols)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    return cp.asnumpy(labels).astype(np.int32, copy=False)


# ---------------------------------------------------------------------------
# kNN para inferencia de type y enlace de eventos
# ---------------------------------------------------------------------------

def knn_gpu(reference_xy: np.ndarray, query_xy: np.ndarray, k: int,
            gpu: GPUContext | None = None,
            chunk_size: int = 200_000) -> tuple[np.ndarray, np.ndarray]:
    """kNN exacto (brute force) con cuML.

    Devuelve (distancias, índices) con forma (n_query, k).
    """
    if gpu is None or not gpu.available or not gpu.has_cuml:
        raise RuntimeError("cuML no disponible")
    from cuml.neighbors import NearestNeighbors

    ref = np.ascontiguousarray(reference_xy, dtype=np.float32)
    n_ref = len(ref)
    if n_ref == 0:
        raise ValueError("referencia vacía")
    kk = int(min(k, n_ref))
    model = NearestNeighbors(n_neighbors=kk, algorithm="brute", metric="euclidean",
                             output_type="numpy")
    model.fit(ref)

    dists: list[np.ndarray] = []
    idxs: list[np.ndarray] = []
    for start in range(0, len(query_xy), chunk_size):
        chunk = np.ascontiguousarray(query_xy[start:start + chunk_size], dtype=np.float32)
        d, i = model.kneighbors(chunk)
        dists.append(np.asarray(d))
        idxs.append(np.asarray(i))
    return np.vstack(dists), np.vstack(idxs)


# ---------------------------------------------------------------------------
# Benchmark y equivalencia CPU/GPU
# ---------------------------------------------------------------------------

def _canonical_labels(labels: np.ndarray) -> np.ndarray:
    out = np.empty(len(labels), dtype=np.int64)
    mapping: dict[int, int] = {}
    for idx, label in enumerate(labels):
        key = int(label)
        if key not in mapping:
            mapping[key] = len(mapping)
        out[idx] = mapping[key]
    return out


def _cpu_cluster(x: np.ndarray, y: np.ndarray, r: np.ndarray) -> np.ndarray:
    from scipy.spatial import cKDTree
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = len(x)
    if n <= 1:
        return np.zeros(n, dtype=np.int32)
    points = np.column_stack([x, y])
    tree = cKDTree(points)
    pairs = tree.query_pairs(2.0 * float(r.max()), output_type="ndarray")
    if pairs.size == 0:
        return np.arange(n, dtype=np.int32)
    rows = pairs[:, 0]
    cols = pairs[:, 1]
    dist = np.hypot(x[rows] - x[cols], y[rows] - y[cols])
    keep = dist <= (r[rows] + r[cols])
    rows, cols = rows[keep], cols[keep]
    if rows.size == 0:
        return np.arange(n, dtype=np.int32)
    graph = coo_matrix((np.ones(rows.size, dtype=np.int8), (rows, cols)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    return labels.astype(np.int32, copy=False)


def benchmark(gpu: GPUContext, n: int = 8_000, seed: int = 42) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    # Cluster sintético: 4 núcleos, radios MODIS/VIIRS mezclados.
    centers = np.array([[0, 0], [5_000, 0], [0, 5_000], [5_000, 5_000]], dtype=float)
    x = np.concatenate([c[0] + rng.normal(0, 300, n // 4) for c in centers])
    y = np.concatenate([c[1] + rng.normal(0, 300, n // 4) for c in centers])
    r = rng.choice([707.0, 265.0, 970.0], size=n).astype(float)

    t0 = time.perf_counter()
    cpu_labels = _canonical_labels(_cpu_cluster(x, y, r))
    cpu_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    gpu_labels = _canonical_labels(cluster_labels_gpu(x, y, r, gpu=gpu))
    gpu_s = time.perf_counter() - t0

    equal = bool(np.array_equal(cpu_labels, gpu_labels))

    result: dict[str, Any] = {
        "device": gpu.name,
        "vram_gb": gpu.vram_gb,
        "cluster": {
            "n": n,
            "cpu_s": round(cpu_s, 4),
            "gpu_s": round(gpu_s, 4),
            "identical": equal,
            "n_clusters_cpu": int(len(np.unique(cpu_labels))),
            "n_clusters_gpu": int(len(np.unique(gpu_labels))),
        },
    }

    if gpu.has_cuml:
        ref = rng.normal(0, 1, (100_000, 2)).astype(np.float32)
        qry = ref[:20_000] + rng.normal(0, 0.1, (20_000, 2)).astype(np.float32)
        from scipy.spatial import cKDTree
        t0 = time.perf_counter()
        tree = cKDTree(ref)
        d_cpu, _ = tree.query(qry, k=8)
        cpu_knn_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        d_gpu, _ = knn_gpu(ref, qry, 8, gpu=gpu)
        gpu_knn_s = time.perf_counter() - t0
        result["knn"] = {
            "n_ref": len(ref),
            "n_query": len(qry),
            "k": 8,
            "cpu_s": round(cpu_knn_s, 4),
            "gpu_s": round(gpu_knn_s, 4),
            "max_abs_diff": float(np.max(np.abs(d_cpu[:, 0] - d_gpu[:, 0]))),
        }
    return result


if __name__ == "__main__":
    from common import load_config

    cfg = load_config()
    # El benchmark siempre corre, aunque el default sea CPU.
    cfg.setdefault("gpu", {})["enabled"] = True
    ctx = detect_gpu(cfg)
    print(f"GPU available={ctx.available} name={ctx.name!r} vram={ctx.vram_gb} GB")
    print(f"reason={ctx.reason}")
    if ctx.available:
        print(json_dumps := __import__("json").dumps(benchmark(ctx), indent=2))
