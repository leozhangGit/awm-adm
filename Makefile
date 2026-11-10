PYTHON ?= python3
UV := .venv/bin/uv
PY := .venv/bin/python

.PHONY: bootstrap check test build schemas isolate dev-api dev-console engine-demo check-lean runtime-setup up status stop

bootstrap:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install --cache-dir .cache/pip uv==0.13.7
	$(UV) sync --locked --reinstall-package uv --cache-dir .cache/uv --python .venv/bin/python --no-python-downloads
	cd console && npm ci --ignore-scripts

check:
	.venv/bin/ruff check src tests scripts
	.venv/bin/ruff format --check src tests scripts
	$(PY) scripts/check_boundaries.py
	$(PY) scripts/check_public_release.py
	$(PY) -m awm_adm check-config config/default.toml
	$(PY) -m awm_adm schemas --output contracts/schemas --check
	$(PY) -m pytest -q
	cd console && npm run format:check && npm test
	cd console && npm run build

test:
	$(PY) -m pytest -q

engine-demo:
	$(PY) scripts/engine_demo.py

check-lean:
	@test -n "$$AWM_ADM_LEAN" && test -x "$$AWM_ADM_LEAN" || (echo 'Set AWM_ADM_LEAN to an absolute Lean 4.19.0 executable'; exit 2)
	$(PY) -m pytest tests/ported/test_certificates.py -q

build:
	$(PY) -m hatchling build -t wheel
	cd console && npm run build

schemas:
	$(PY) -m awm_adm schemas --output contracts/schemas
	$(PY) scripts/export_openapi.py

isolate:
	$(PY) scripts/check_isolated.py --python $(PYTHON)

dev-api:
	.venv/bin/awm-adm dev-serve --config config/default.toml

dev-console:
	cd console && npm run dev

runtime-setup:
	$(PYTHON) scripts/setup_runtime.py

up: runtime-setup
	docker compose up -d --build --wait --wait-timeout 60

status:
	docker compose ps

stop:
	docker compose stop
