from __future__ import annotations

import os
from pathlib import Path
import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "config.yml"


def config_path() -> Path:
    return Path(os.getenv("RADIOCHARTS_CONFIG", str(DEFAULT_CONFIG)))


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        example = path.with_name("config.example.yml")
        if example.exists():
            path = example
        else:
            raise FileNotFoundError(f"Brak konfiguracji: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
