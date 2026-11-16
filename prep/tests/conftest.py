from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PREP = Path(__file__).resolve().parents[1]
SRC = PREP / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common import PREP_ROOT, RunContext, load_config  # noqa: E402


def load_step(filename: str):
    path = SRC / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture
def ctx(cfg):
    return RunContext(cfg=cfg, prep_root=PREP_ROOT, stage="test")
