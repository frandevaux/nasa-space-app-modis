from __future__ import annotations

import numpy as np
import pytest

from gpu import _canonical_labels, _cpu_cluster, cluster_labels_gpu, detect_gpu


def test_gpu_clustering_matches_cpu(cfg):
    # El default es CPU; el test fuerza la GPU para validar equivalencia.
    cfg_gpu = {**cfg, "gpu": {**cfg.get("gpu", {}), "enabled": True}}
    gpu = detect_gpu(cfg_gpu)
    if not gpu.available:
        pytest.skip(f"GPU no disponible: {gpu.reason}")
    rng = np.random.default_rng(7)
    centers = np.array([[0, 0], [4000, 0], [0, 4000]], dtype=float)
    x = np.concatenate([c[0] + rng.normal(0, 250, 500) for c in centers])
    y = np.concatenate([c[1] + rng.normal(0, 250, 500) for c in centers])
    r = rng.choice([707.0, 265.0], size=len(x))
    cpu = _canonical_labels(_cpu_cluster(x, y, r))
    gpu_labels = _canonical_labels(cluster_labels_gpu(x, y, r, gpu=gpu))
    assert np.array_equal(cpu, gpu_labels)
