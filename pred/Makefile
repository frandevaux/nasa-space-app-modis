PY := ./.venv/bin/python
CONFIG := config/params.yaml

.PHONY: setup gpu-check inventory static hotspots patches train tensorboard eval classic report forecast-check smoke all test

setup:
	uv venv .venv --python 3.12
	uv pip install --python $(PY) -r requirements.txt
	uv pip install --python $(PY) torch --index-url https://download.pytorch.org/whl/cu124
	$(PY) src/gpu_check.py

gpu-check:
	$(PY) src/gpu_check.py

inventory:
	$(PY) src/00_inventory.py --config $(CONFIG)

static:
	$(PY) src/01_build_static.py --config $(CONFIG)

hotspots:
	$(PY) src/02_build_hotspots.py --config $(CONFIG)

patches:
	$(PY) src/03_build_patches.py --config $(CONFIG)

train:
	$(PY) src/06_train.py --config $(CONFIG)

tensorboard:
	./.venv/bin/tensorboard --logdir data/runs

eval:
	$(PY) src/07_evaluate.py --config $(CONFIG)

classic:
	$(PY) src/08_classic_fires_events.py --config $(CONFIG)

report:
	$(PY) src/07_evaluate.py --config $(CONFIG) --report-only

forecast-check:
	$(PY) src/forecast_adapter.py --config $(CONFIG) --check

smoke:
	$(PY) src/00_inventory.py --config $(CONFIG) --smoke
	$(PY) src/01_build_static.py --config $(CONFIG) --smoke
	$(PY) src/02_build_hotspots.py --config $(CONFIG) --smoke
	$(PY) src/03_build_patches.py --config $(CONFIG) --smoke
	$(PY) src/06_train.py --config $(CONFIG) --smoke
	$(PY) src/07_evaluate.py --config $(CONFIG) --smoke

all: static hotspots patches train eval classic report

test:
	$(PY) -m pytest tests -q
