.PHONY: check format format-check tests build build-linux build-windows
check:
	uv run ruff check src tests scripts
	uv run ty check src
	uv run basedpyright
format:
	uv run ruff format src tests scripts
format-check:
	uv run ruff format --check src tests scripts
tests:
	uv run pytest --cov --cov-report=term-missing
build build-linux build-windows:
	uv run python scripts/build_native.py
