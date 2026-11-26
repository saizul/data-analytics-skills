"""Shared helpers: import skill scripts by path, run them as CLIs, locate fixtures."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_script(skill: str, filename: str):
    path = SKILLS / skill / "scripts" / filename
    name = f"skill_{skill.replace('-', '_')}_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_script(skill: str, filename: str, *args: str, stdin: str | None = None):
    path = SKILLS / skill / "scripts" / filename
    return subprocess.run(
        [sys.executable, str(path), *args],
        capture_output=True,
        text=True,
        input=stdin,
        timeout=60,
        check=False,
        encoding="utf-8",
    )


def write_csv(tmp_path: Path, text: str, name: str = "data.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path
