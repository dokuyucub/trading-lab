.PHONY: install install-locked lock test cov lint fmt typecheck check hooks doctor clean

# Gelistirme kurulumu (guncel surumler)
install:
	pip install -e ".[dev]"

# CI ile AYNI surumler. "Bende calisiyordu" durumunu ortadan kaldirir.
install-locked:
	pip install -r requirements.lock
	pip install --no-deps -e .

# Bagimlilik degistiyse kilidi tazele ve commit et.
lock:
	uv pip compile pyproject.toml --extra dev --python-version 3.12 \
		--output-file requirements.lock

test:
	pytest

cov:
	pytest --cov=tlab --cov-report=term-missing:skip-covered

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff check --fix .
	ruff format .

typecheck:
	mypy

# Push etmeden once calistirilacak tek komut. CI'nin yaptiginin aynisi.
check: lint typecheck test

# Yerel kapilari git kancasi olarak kur.
hooks:
	pre-commit install

doctor:
	tlab doctor

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
