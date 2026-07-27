PYTHON ?= python3
SKILL_DIR := skills/material-code-review
SIMPLIFY_SKILL_DIR := skills/material-code-simplification
DIST_DIR ?= dist
VERSION := 1.2.0
SIMPLIFY_VERSION := 1.1.0
FULL_ZIP := $(DIST_DIR)/material-code-review-plugin-$(VERSION).zip
STANDALONE_ZIP := $(DIST_DIR)/material-code-review-codex-skill-$(VERSION).zip
SIMPLIFY_STANDALONE_ZIP := $(DIST_DIR)/material-code-simplification-codex-skill-$(SIMPLIFY_VERSION).zip

ifneq ($(wildcard .git),)
PACKAGE_LAYOUT_ARGUMENT :=
DISTRIBUTION_TEST_ENV :=
else
PACKAGE_LAYOUT_ARGUMENT := --distribution-layout
DISTRIBUTION_TEST_ENV := MATERIAL_REVIEW_DISTRIBUTION_LAYOUT=1
endif

ifneq ($(wildcard scripts/evaluate_material_review.py),)
EVALUATOR_PYTHON := scripts/evaluate_material_review.py scripts/material_review_evaluation/*.py
EVALUATOR_WRAPPER := bin/material-review-evaluate
else
EVALUATOR_PYTHON :=
EVALUATOR_WRAPPER :=
endif

.PHONY: validate package package-simplification package-check test compile json shell clean evaluate-review

validate:
	$(MAKE) clean
	$(PYTHON) scripts/validate_package.py --package-root . $(PACKAGE_LAYOUT_ARGUMENT)
	$(PYTHON) $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py
	$(PYTHON) -m py_compile $(SKILL_DIR)/scripts/reviewctl.py $(SIMPLIFY_SKILL_DIR)/scripts/simplifyctl.py $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py scripts/validate_package.py scripts/package_plugin.py scripts/package_simplification_skill.py $(EVALUATOR_PYTHON)
	$(MAKE) clean
	$(PYTHON) -c 'import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path(".").rglob("*.json")]; print("JSON OK")'
	bash -n bin/material-reviewctl $(EVALUATOR_WRAPPER)
	$(PYTHON) -B -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v
	$(PYTHON) -B -m unittest discover -s $(SIMPLIFY_SKILL_DIR)/tests -p 'test_*.py' -v
	$(DISTRIBUTION_TEST_ENV) $(PYTHON) -B -m unittest discover -s scripts/tests -p 'test_*.py' -v
	$(MAKE) clean
	$(PYTHON) scripts/validate_package.py --package-root . $(PACKAGE_LAYOUT_ARGUMENT)
	$(PYTHON) $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py

package: validate
	mkdir -p $(DIST_DIR)
	$(PYTHON) scripts/package_plugin.py --package-root . --output $(FULL_ZIP) --standalone-output $(STANDALONE_ZIP)
	$(PYTHON) scripts/validate_package.py --package-root . --full-archive $(FULL_ZIP) --standalone-archive $(STANDALONE_ZIP)

package-simplification: validate
	mkdir -p $(DIST_DIR)
	$(PYTHON) scripts/package_simplification_skill.py --root . --output $(SIMPLIFY_STANDALONE_ZIP)
	$(PYTHON) $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py --archive $(SIMPLIFY_STANDALONE_ZIP)

package-check:
	$(PYTHON) scripts/validate_package.py --package-root . $(PACKAGE_LAYOUT_ARGUMENT)
	$(PYTHON) $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py

compile:
	$(PYTHON) -m py_compile $(SKILL_DIR)/scripts/reviewctl.py $(SIMPLIFY_SKILL_DIR)/scripts/simplifyctl.py $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py scripts/validate_package.py scripts/package_plugin.py scripts/package_simplification_skill.py $(EVALUATOR_PYTHON)

json:
	$(PYTHON) -c 'import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path(".").rglob("*.json")]; print("JSON OK")'

shell:
	bash -n bin/material-reviewctl $(EVALUATOR_WRAPPER)

evaluate-review:
	@test -n "$(BASE_REF)" -a -n "$(CANDIDATE_REF)" -a -n "$(BENCHMARK)" -a -n "$(MODEL)" -a -n "$(REASONING_EFFORT)" || { echo "BASE_REF, CANDIDATE_REF, BENCHMARK, MODEL, and REASONING_EFFORT are required" >&2; exit 2; }
	$(PYTHON) scripts/evaluate_material_review.py compare --base-ref "$(BASE_REF)" --candidate-ref "$(CANDIDATE_REF)" --benchmark "$(BENCHMARK)" --model "$(MODEL)" --reasoning-effort "$(REASONING_EFFORT)"

test:
	$(PYTHON) -B -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v
	$(PYTHON) -B -m unittest discover -s $(SIMPLIFY_SKILL_DIR)/tests -p 'test_*.py' -v
	$(DISTRIBUTION_TEST_ENV) $(PYTHON) -B -m unittest discover -s scripts/tests -p 'test_*.py' -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
