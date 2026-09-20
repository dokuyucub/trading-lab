# Araclar PATH'ten degil, PROJENIN YORUMLAYICISINDAN cagriliyor.
# Sebep somut: makinede eski bir global mypy varsa, `mypy` komutu onu
# bulur ve kilitteki surumden farkli sonuc verir. "Bende calisiyordu"
# hikayelerinin buyuk kismi bu farktan cikiyor.
PY ?= python3

.PHONY: install install-locked lock test cov lint fmt typecheck check hooks doctor clean

# Gelistirme kurulumu (guncel surumler)
install:
	$(PY) -m pip install -e ".[dev]"

# CI ile AYNI surumler. "Bende calisiyordu" durumunu ortadan kaldirir.
install-locked:
	$(PY) -m pip install -r requirements-dev.lock
	$(PY) -m pip install --no-deps -e .

# Iki kilit: calisma zamani (Docker imaji) ve gelistirme (CI, yerel).
# Bagimlilik degistiyse ikisini de tazele ve commit et.
lock:
	$(PY) -m uv pip compile pyproject.toml --python-version 3.12 \
		--output-file requirements.lock
	$(PY) -m uv pip compile pyproject.toml --extra dev --python-version 3.12 \
		--output-file requirements-dev.lock

test:
	$(PY) -m pytest

cov:
	$(PY) -m pytest --cov=tlab --cov-report=term-missing:skip-covered

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

typecheck:
	$(PY) -m mypy

# Push etmeden once calistirilacak tek komut. CI'nin yaptiginin aynisi -
# kapsama esigi dahil, cunku "ayni kapi" demek ancak gercekten ayniysa
# bir sey ifade eder.
check: lint typecheck cov

# Yerel kapilari git kancasi olarak kur.
hooks:
	$(PY) -m pre-commit install

doctor:
	$(PY) -m tlab.cli doctor

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
