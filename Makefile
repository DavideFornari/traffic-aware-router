.PHONY: venv lint format test app

VENV := .venv

ifeq ($(OS),Windows_NT)
	PYTHON := $(VENV)/Scripts/python.exe
else
	PYTHON := $(VENV)/bin/python
endif

# .[dev] only, matching CI (.github/workflows/ci.yml) exactly — lint/format/test
# never need folium/streamlit/matplotlib, and CI shouldn't either (see CLAUDE.md).
venv:
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"
	$(PYTHON) -m pre_commit install

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

test:
	$(PYTHON) -m pytest

# README's "Try it" path (pip install -e ".[dev,viz,app]" && streamlit run
# app/main.py) as a single command, so both documented setups actually work.
app: venv
	$(PYTHON) -m pip install -e ".[dev,viz,app]"
	$(PYTHON) -m streamlit run app/main.py
