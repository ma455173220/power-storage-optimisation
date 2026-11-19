PY := .venv/bin/python
export PYTHONPATH := src

.PHONY: all env data test run bench report

all: data test run bench report

env:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements.lock

data:
	$(PY) -m bess.data

test:
	$(PY) -m pytest -q

run:
	$(PY) -m bess.run

bench:
	$(PY) -m bess.bench

report:
	$(PY) -m bess.report
