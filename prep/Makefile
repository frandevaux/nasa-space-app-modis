PY := ./.venv/bin/python
CONFIG := config/params.yaml

.PHONY: setup gpu-check aux smoke-archive smoke-api all test

setup:
	uv venv .venv --python 3.12
	uv pip install --python $(PY) -r requirements.txt
	uv pip install --python $(PY) --extra-index-url https://pypi.nvidia.com \
		--index-strategy unsafe-best-match -r requirements-gpu.txt
	uv pip install --python $(PY) "nvidia-cuda-runtime-cu12==12.8.*"

gpu-check:
	$(PY) src/gpu.py

aux:
	$(PY) src/00_fetch_aux.py --config $(CONFIG)

smoke-archive:
	$(PY) src/01_ingest.py --config $(CONFIG) --smoke --smoke-case archive_2025 --smoke-years 2025
	$(PY) src/02_clean.py --config $(CONFIG) --smoke --smoke-case archive_2025
	$(PY) src/03_conf_class.py --config $(CONFIG) --smoke --smoke-case archive_2025
	$(PY) src/04_fires.py --config $(CONFIG) --smoke --smoke-case archive_2025
	$(PY) src/05_events.py --config $(CONFIG) --smoke --smoke-case archive_2025
	$(PY) src/06_confidence.py --config $(CONFIG) --smoke --smoke-case archive_2025
	$(PY) src/07_export.py --config $(CONFIG) --smoke --smoke-case archive_2025

smoke-api:
	$(PY) src/01_ingest.py --config $(CONFIG) --smoke --smoke-case api_2026_07 --smoke-api 2026-07-25:2026-08-05
	$(PY) src/02_clean.py --config $(CONFIG) --smoke --smoke-case api_2026_07
	$(PY) src/03_conf_class.py --config $(CONFIG) --smoke --smoke-case api_2026_07

all: aux
	$(PY) src/01_ingest.py --config $(CONFIG)
	$(PY) src/02_clean.py --config $(CONFIG)
	$(PY) src/03_conf_class.py --config $(CONFIG)
	$(PY) src/04_fires.py --config $(CONFIG)
	$(PY) src/05_events.py --config $(CONFIG)
	$(PY) src/06_confidence.py --config $(CONFIG)
	$(PY) src/07_export.py --config $(CONFIG)

test:
	$(PY) -m pytest tests -q
