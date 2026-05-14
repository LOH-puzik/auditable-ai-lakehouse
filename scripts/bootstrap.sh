#!/usr/bin/env bash
# One-command setup. Run from the repository root.

set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it from https://github.com/astral-sh/uv" >&2
  exit 1
fi

echo "→ Syncing dependencies with uv..."
uv sync --extra dev --extra docs

if [ ! -f .env ]; then
  echo "→ Creating .env from .env.example (fill in real values before anchoring)"
  cp .env.example .env
fi

echo "→ Installing pre-commit hooks..."
uv run pre-commit install || echo "(pre-commit not configured yet — skipping)"

echo "→ Running tests..."
uv run pytest -q

echo "✓ Bootstrap complete."
