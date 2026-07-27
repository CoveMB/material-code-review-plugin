PYTHON ?= python3
SKILL_DIR := skills/material-code-review
SIMPLIFY_SKILL_DIR := skills/material-code-simplification
EVALUATOR_DIR := scripts/material_review_evaluation
DIST_DIR ?= dist
VERSION := 1.2.0
SIMPLIFY_VERSION := 1.1.0
FULL_ZIP := $(DIST_DIR)/material-code-review-plugin-$(VERSION).zip
STANDALONE_ZIP := $(DIST_DIR)/material-code-review-codex-skill-$(VERSION).zip
SIMPLIFY_STANDALONE_ZIP := $(DIST_DIR)/material-code-simplification-codex-skill-$(SIMPLIFY_VERSION).zip

.PHONY: validate package package-simplification package-check test compile json shell clean evaluate-review

validate:
	$(MAKE) clean
	$(PYTHON) scripts/validate_package.py --package-root .
	$(PYTHON) $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py
	$(PYTHON) -m py_compile $(SKILL_DIR)/scripts/reviewctl.py $(SIMPLIFY_SKILL_DIR)/scripts/simplifyctl.py $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py scripts/validate_package.py scripts/package_plugin.py scripts/package_simplification_skill.py scripts/evaluate_material_review.py $(EVALUATOR_DIR)/*.py
	$(MAKE) clean
	$(PYTHON) -c 'import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path(".").rglob("*.json")]; print("JSON OK")'
	bash -n bin/material-reviewctl bin/material-review-evaluate
	$(PYTHON) -B -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v
	$(PYTHON) -B -m unittest discover -s $(SIMPLIFY_SKILL_DIR)/tests -p 'test_*.py' -v
	$(PYTHON) -B -m unittest discover -s scripts/tests -p 'test_*.py' -v
	$(MAKE) clean
	$(PYTHON) scripts/validate_package.py --package-root .
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
	$(PYTHON) scripts/validate_package.py --package-root .
	$(PYTHON) $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py

compile:
	$(PYTHON) -m py_compile $(SKILL_DIR)/scripts/reviewctl.py $(SIMPLIFY_SKILL_DIR)/scripts/simplifyctl.py $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py scripts/validate_package.py scripts/package_plugin.py scripts/package_simplification_skill.py scripts/evaluate_material_review.py $(EVALUATOR_DIR)/*.py

json:
	$(PYTHON) -c 'import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path(".").rglob("*.json")]; print("JSON OK")'

shell:
	bash -n bin/material-reviewctl bin/material-review-evaluate

evaluate-review:
	@test -n "$(BASE_REF)" -a -n "$(CANDIDATE_REF)" -a -n "$(BENCHMARK)" -a -n "$(MODEL)" -a -n "$(REASONING_EFFORT)" || { echo "BASE_REF, CANDIDATE_REF, BENCHMARK, MODEL, and REASONING_EFFORT are required" >&2; exit 2; }
	$(PYTHON) scripts/evaluate_material_review.py compare --base-ref "$(BASE_REF)" --candidate-ref "$(CANDIDATE_REF)" --benchmark "$(BENCHMARK)" --model "$(MODEL)" --reasoning-effort "$(REASONING_EFFORT)"

test:
	$(PYTHON) -B -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v
	$(PYTHON) -B -m unittest discover -s $(SIMPLIFY_SKILL_DIR)/tests -p 'test_*.py' -v
	$(PYTHON) -B -m unittest discover -s scripts/tests -p 'test_*.py' -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
