PY := .venv/bin/python
export PYTHONPATH := src

.PHONY: all data test clean-results

all: data test

data:
	$(PY) -m bess.data

test:
	$(PY) -m pytest -q
