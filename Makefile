# Makefile raíz — atajos para el repo completo.
# Ejecutá 'make help' para ver los atajos disponibles.

.PHONY: help setup setup-prep setup-pred pipeline-setup download data-aux raw prep pred demo test webtool-install webtool-data webtool

help:
	@echo "Targets disponibles:"
	@echo "  setup           Instala prep/.venv y pred/.venv"
	@echo "  pipeline-setup  Instala pipeline/.venv (scripts de descarga)"
	@echo "  download        Baja datos crudos (requiere .env con MAP_KEY)"
	@echo "  data-aux        Baja auxiliares de prep (AP, límites, landcover)"
	@echo "  raw             Genera data/processed/detections_raw.parquet"
	@echo "  prep            Corre el pipeline de preprocesamiento"
	@echo "  pred            Corre el pipeline de predicción"
	@echo "  demo            Sirve docs/ en http://localhost:8000"
	@echo "  test            Corre los tests de prep y pred"
	@echo "  webtool-install Instala dependencias de la app web (npm ci)"
	@echo "  webtool-data    Genera los datos de webtool/public/data"
	@echo "  webtool         Levanta la app web en http://localhost:3000"

setup: setup-prep setup-pred

setup-prep:
	cd prep && make setup

setup-pred:
	cd pred && make setup

pipeline-setup:
	cd pipeline && uv venv .venv --python 3.12
	cd pipeline && uv pip install --python .venv/bin/python -r requirements.txt

download:
	@test -f .env || (echo "Falta .env: copiá .env.example y completá MAP_KEY" && exit 1)
	cd pipeline && ./.venv/bin/python download_boundaries.py
	cd pipeline && ./.venv/bin/python download_country.py
	cd pipeline && ./.venv/bin/python download_api.py
	cd pipeline && ./.venv/bin/python download_climate.py
	@echo "FWI opcional: cd pipeline && ./.venv/bin/python download_copernicus.py"

data-aux:
	cd prep && make aux

raw:
	cd pipeline && ./.venv/bin/python load_raw.py

prep:
	cd prep && make all

pred:
	cd pred && make all

demo:
	python3 -m http.server 8000 --directory docs

test:
	cd prep && make test
	cd pred && make test

webtool-install:
	@command -v npm >/dev/null || (echo "Falta npm: instalá Node.js 20+ en este entorno" && exit 1)
	cd webtool && npm ci

webtool-data:
	cd pipeline && ./.venv/bin/python ../webtool/scripts/build_data.py

webtool:
	@command -v npm >/dev/null || (echo "Falta npm: instalá Node.js 20+ en este entorno" && exit 1)
	cd webtool && npm run dev
