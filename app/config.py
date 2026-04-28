from __future__ import annotations
from pathlib import Path
import os

_ENV_LOADED = False


def load_env_file(path: str | None = None, override: bool = False) -> Path | None:
    """Load KEY=VALUE entries from a local .env file without requiring python-dotenv.

    This keeps the suite portable on Streamlit Community, local Windows/Mac/Linux,
    and simple VPS installs. Existing shell environment variables win by default.
    """
    global _ENV_LOADED
    if _ENV_LOADED and not override:
        return None

    root = Path(__file__).resolve().parents[1]
    env_path = Path(path).expanduser().resolve() if path else root / ".env"
    if not env_path.exists():
        _ENV_LOADED = True
        return None

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
    _ENV_LOADED = True
    return env_path


def env(name: str, default: str = "") -> str:
    load_env_file()
    return os.getenv(name, default)
