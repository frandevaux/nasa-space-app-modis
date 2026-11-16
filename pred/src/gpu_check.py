"""Verifica que PyTorch vea la GPU y que una matmul funcione."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR importando torch: {exc}")
        return 1

    print(f"torch={torch.__version__}")
    print(f"cuda_available={torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("ERROR: CUDA no disponible. Revisar driver/wheel cu124.")
        return 1
    print(f"device={torch.cuda.get_device_name(0)}")
    print(f"capability={torch.cuda.get_device_capability(0)}")
    print(f"vram_gb={torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}")

    a = torch.randn(1024, 1024, device="cuda", dtype=torch.float32)
    b = torch.randn(1024, 1024, device="cuda", dtype=torch.float32)
    c = a @ b
    torch.cuda.synchronize()
    print(f"matmul_ok={bool(torch.isfinite(c).all())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
