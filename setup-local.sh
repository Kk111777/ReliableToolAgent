#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_DIR/.cache/uv}"
if ! command -v uv >/dev/null 2>&1; then
  echo '需要 uv：请先按 https://docs.astral.sh/uv/getting-started/installation/ 安装。'
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12.14 .venv
fi
uv pip install --python .venv/bin/python -r requirements-local.lock
uv pip check --python .venv/bin/python
