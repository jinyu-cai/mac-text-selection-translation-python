UV ?= uv
PYTHON = .venv/bin/python
APP = dist/Text Selection Translation Python.app
SIGN_ID ?= -
export UV_CACHE_DIR ?= $(CURDIR)/.cache/uv

.PHONY: setup run beta-run test check app sign clean
setup:
	$(UV) sync --locked --extra dev
run:
	$(PYTHON) -m mactranslator.desktop.app
beta-run:
	$(PYTHON) -m mactranslator.desktop.app --experimental-dictionary
test:
	$(PYTHON) -m pytest -q
check:
	.venv/bin/ruff check src tests
	$(PYTHON) -m compileall -q src
app:
	rm -rf build dist
	cd packaging && MACOSX_DEPLOYMENT_TARGET=14.0 ../$(PYTHON) setup.py py2app --dist-dir ../dist --bdist-base ../build
sign:
	codesign --force --deep --sign "$(SIGN_ID)" "$(APP)"
	codesign --verify --deep --strict "$(APP)"
clean:
	rm -rf build dist
