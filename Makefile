.PHONY: venv lint format test

VENV := .venv

ifeq ($(OS),Windows_NT)
	PYTHON := $(VENV)/Scripts/python.exe
else
	PYTHON := $(VENV)/bin/python
endif

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
