PYTHON ?= python3
SKILL_DIR := skills/material-code-review
DIST_DIR ?= dist
VERSION := 1.1.0
FULL_ZIP := $(DIST_DIR)/material-code-review-plugin-$(VERSION).zip
STANDALONE_ZIP := $(DIST_DIR)/material-code-review-codex-skill-$(VERSION).zip

.PHONY: validate package package-check test compile json shell clean

validate:
	$(MAKE) clean
	$(PYTHON) scripts/validate_package.py --package-root .
	$(PYTHON) -m py_compile $(SKILL_DIR)/scripts/reviewctl.py scripts/validate_package.py scripts/package_plugin.py
	$(PYTHON) -c 'import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path(".").rglob("*.json")]; print("JSON OK")'
	bash -n bin/material-reviewctl
	$(PYTHON) -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v
	$(MAKE) clean
	$(PYTHON) scripts/validate_package.py --package-root .

package: validate
	mkdir -p $(DIST_DIR)
	$(PYTHON) scripts/package_plugin.py --package-root . --output $(FULL_ZIP) --standalone-output $(STANDALONE_ZIP)
	$(PYTHON) scripts/validate_package.py --package-root . --full-archive $(FULL_ZIP) --standalone-archive $(STANDALONE_ZIP)

package-check:
	$(PYTHON) scripts/validate_package.py --package-root .

compile:
	$(PYTHON) -m py_compile $(SKILL_DIR)/scripts/reviewctl.py scripts/validate_package.py scripts/package_plugin.py

json:
	$(PYTHON) -c 'import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path(".").rglob("*.json")]; print("JSON OK")'

shell:
	bash -n bin/material-reviewctl

test:
	$(PYTHON) -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
