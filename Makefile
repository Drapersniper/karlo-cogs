PYTHON ?= python3.10

# Python Code Style
reformat:
	$(PYTHON) -m ruff format . --line-length 99
stylecheck:
	$(PYTHON) -m ruff format . --line-length 99
stylediff:
	$(PYTHON) -m ruff format . --line-length 99 --diff
