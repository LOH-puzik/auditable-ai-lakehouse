"""Small runtime helpers for CLI environment defaults."""

from __future__ import annotations

import os
from pathlib import Path


def env_value(
    name: str, default: str | None = None, *, env_path: Path = Path(".env")
) -> str | None:
    """Read a setting from the process environment or a local .env file."""
    value = os.getenv(name)
    if value is not None:
        return value

    if not env_path.exists():
        return default

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        if key.strip() != name:
            continue
        return _strip_env_quotes(raw_value.strip())

    return default


def env_flag(name: str, *, default: bool) -> bool:
    """Read a boolean flag from env/.env using common true values."""
    value = env_value(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
