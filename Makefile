.PHONY: quality style test docs verify-project

PROJECT_PYTHON ?= .venv/bin/python

check_dirs := examples src tests

# Check code quality of the source code
quality:
	ruff check $(check_dirs)
	ruff format --check $(check_dirs)

# Format source code automatically
style:
	ruff check $(check_dirs) --fix
	ruff format $(check_dirs)
	
# Run smolagents tests
test:
	pytest ./tests/

# Project-specific checks; no credentials or model requests.
verify-project:
	$(PROJECT_PYTHON) -m pytest -q local_demo benchmark/tau3/tests
	$(PROJECT_PYTHON) scripts/audit_packaging_evidence.py
	$(PROJECT_PYTHON) benchmark/tau3/scripts/audit_frozen_study.py
	$(PROJECT_PYTHON) benchmark/tau3/scripts/study_evidence.py audit --input reports/frozen_study/retail-holdout-v1/public_evidence.json
	$(PROJECT_PYTHON) benchmark/tau3/scripts/audit_study_cases.py --evidence reports/frozen_study/retail-holdout-v1/public_evidence.json --cases reports/frozen_study/retail-holdout-v1/case_index.json
	$(PROJECT_PYTHON) benchmark/tau3/scripts/engineering_evidence.py --audit reports/engineering-v2/integration.json
	$(PROJECT_PYTHON) benchmark/tau3/scripts/measurement_v2.py audit --input reports/engineering-v2/measurement.json --evidence reports/frozen_study/retail-holdout-v1/public_evidence.json --cases reports/frozen_study/retail-holdout-v1/case_index.json
	$(PROJECT_PYTHON) scripts/audit_model_review.py --input reports/model-review-v1/summary.json
	$(PROJECT_PYTHON) scripts/check_markdown_links.py
	$(PROJECT_PYTHON) scripts/check_markdown_links.py 开始这里.md docs/engineering_v2.md docs/engineering_v2.zh-CN.md reports/engineering-v2/README.md reports/engineering-v2/README.zh-CN.md reports/model-review-v1/README.md reports/model-review-v1/README.zh-CN.md
