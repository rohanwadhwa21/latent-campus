"""Load YAML configs from the repo's configs/ directory."""

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "configs"
DATA_DIR = REPO_ROOT / "data"

# Raw HTML cache lives outside the repo by default because this project sits in
# an iCloud-synced ~/Desktop, which evicts large cached files to dataless
# placeholders under disk pressure (reads then time out). A symlink inside the
# synced tree is itself unreliable — iCloud removes it — so we resolve the
# location from an env var instead. Override with LATENT_CAMPUS_RAW_DIR.
RAW_DIR = Path(os.environ.get("LATENT_CAMPUS_RAW_DIR", DATA_DIR / "raw")).expanduser()


@cache
def load_config(name: str) -> dict[str, Any]:
    """Load configs/<name>.yaml as a dict."""
    path = CONFIG_DIR / f"{name}.yaml"
    with path.open() as f:
        return yaml.safe_load(f)


def semesters() -> list[str]:
    return load_config("semesters")["semesters"]


def scraping_policy() -> dict[str, Any]:
    return load_config("sources")["scraping"]
