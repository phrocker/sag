.PHONY: generate test lint build clean

PYTHON ?= $(shell [ -f .venv/bin/python3 ] && echo .venv/bin/python3 || echo python3)
GRAMMAR_SRC := ../src/main/antlr4/SAG.g4
GENERATED_DIR := src/sag/generated

ANTLR4_VERSION ?= 4.13.1
ANTLR4_CMD = import sys; sys.argv[1:] = ['-Dlanguage=Python3', '-visitor', '-no-listener', 'SAG.g4']; from antlr4_tool_runner import tool; tool()

generate:
	mkdir -p $(GENERATED_DIR)
	cp $(GRAMMAR_SRC) $(GENERATED_DIR)/SAG.g4
	PYBIN=$$($(PYTHON) -c "import sys; print(sys.executable)") && \
		cd $(GENERATED_DIR) && ANTLR4_TOOLS_ANTLR_VERSION=$(ANTLR4_VERSION) $$PYBIN -c "$(ANTLR4_CMD)"
	touch $(GENERATED_DIR)/__init__.py

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m ruff check src/ tests/

build:
	$(PYTHON) -m build

clean:
	rm -rf $(GENERATED_DIR)/*.py $(GENERATED_DIR)/*.interp $(GENERATED_DIR)/*.tokens $(GENERATED_DIR)/SAG.g4
	rm -rf dist/ *.egg-info build/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
