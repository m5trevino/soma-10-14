#!/usr/bin/env python3
"""Profile store — save, load, delete profiles in turn-key-profile/."""

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent


def _read_base_path() -> Path:
    """Read base path from data/.base_path (relative to the project root)."""
    base_file = PROJECT_ROOT / "data" / ".base_path"
    if base_file.exists():
        return Path(base_file.read_text().strip())
    return PROJECT_ROOT


BASE_PATH = _read_base_path()
PROFILES_DIR = BASE_PATH / "turn-key-profile"


def save_profile(name: str, profile: dict) -> Path:
    """Save a profile to turn-key-profile/${name}.json. Creates directory if missing."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PROFILES_DIR / name
    filepath.write_text(json.dumps(profile, indent=2))
    return filepath


def load_profile(name: str) -> dict | None:
    """Load a profile from turn-key-profile/${name}.json."""
    filepath = PROFILES_DIR / name
    if not filepath.exists():
        return None
    return json.loads(filepath.read_text())


def delete_profile(name: str) -> bool:
    """Delete a profile from turn-key-profile/. Returns True if deleted, False if not found."""
    filepath = PROFILES_DIR / name
    if not filepath.exists():
        return False
    filepath.unlink()
    return True


def list_profiles() -> list[str]:
    """List all .json files in turn-key-profile/."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(f.name for f in PROFILES_DIR.glob("*.json"))
