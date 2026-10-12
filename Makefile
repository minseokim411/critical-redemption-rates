PY ?= python

.PHONY: all model figures summary test

all: model figures summary test

model:
	$(PY) scripts/run_model.py

figures:
	$(PY) scripts/make_figures.py

summary:
	$(PY) scripts/make_summary.py --sync

test:
	$(PY) -m pytest -q
