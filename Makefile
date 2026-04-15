PYTHON ?= python3.10

# Python Code Style
reformat:
	$(PYTHON) -m ruff format . --line-length 99 --ignore E501
stylecheck:
	$(PYTHON) -m ruff format . --line-length 99 --ignore E501
stylediff:
	$(PYTHON) -m ruff format . --line-length 99 --ignore E501 --diff
