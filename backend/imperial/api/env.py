"""Load backend/.env into os.environ (dev convenience; real deploys use env)."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | str | None = None) -> None:
    env_file = Path(path) if path else Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
