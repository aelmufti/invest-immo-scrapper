"""Configuration centralisée chargée depuis variables d'env (.env).

Toutes les valeurs sont lisibles par le reste du code via `get_settings()`.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Charge .env (s'il existe) sans écraser les variables déjà définies.
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env", override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "oui"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings:
    """Snapshot immuable de la configuration."""

    def __init__(self) -> None:
        self.root_dir: Path = ROOT_DIR
        self.database_url: str = os.getenv(
            "DATABASE_URL", f"sqlite:///{ROOT_DIR / 'data.db'}"
        )
        self.api_host: str = os.getenv("API_HOST", "127.0.0.1")
        self.api_port: int = _env_int("API_PORT", 8765)
        self.streamlit_port: int = _env_int("STREAMLIT_PORT", 8501)

        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

        # Scheduler (en minutes)
        self.sched_dvf_refresh_min: int = _env_int("SCHED_DVF_REFRESH_MIN", 10080)
        self.sched_connectors_min: int = _env_int("SCHED_CONNECTORS_MIN", 360)
        self.sched_rescore_min: int = _env_int("SCHED_RESCORE_MIN", 60)

        # Notifications
        self.notify_desktop_enabled: bool = _env_bool("NOTIFY_DESKTOP_ENABLED", True)
        self.notify_email_enabled: bool = _env_bool("NOTIFY_EMAIL_ENABLED", False)
        self.smtp_host: str = os.getenv("SMTP_HOST", "")
        self.smtp_port: int = _env_int("SMTP_PORT", 587)
        self.smtp_user: str = os.getenv("SMTP_USER", "")
        self.smtp_password: str = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from: str = os.getenv("SMTP_FROM", "")
        self.smtp_to: str = os.getenv("SMTP_TO", "")

        # Connecteurs (couche B)
        self.connector_example_enabled: bool = _env_bool(
            "CONNECTOR_EXAMPLE_ENABLED", False
        )

        # Dossiers utilitaires
        self.logs_dir: Path = ROOT_DIR / "logs"
        self.logs_dir.mkdir(exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def setup_logging(level: str | None = None) -> None:
    """Configure le logging racine. Idempotent."""
    settings = get_settings()
    chosen = (level or settings.log_level or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, chosen, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
