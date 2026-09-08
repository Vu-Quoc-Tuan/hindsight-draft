"""Server-side environment bootstrap for local and deployed API runtimes."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_project_environment(dotenv_path: str | Path | None = None) -> bool:
    """Load project-local values without overriding deployment environment."""
    path = Path(dotenv_path) if dotenv_path is not None else PROJECT_ROOT / ".env"
    return bool(load_dotenv(dotenv_path=path, override=False))
