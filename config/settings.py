"""Environment-driven configuration.

A ``.env`` file at the project root (if present) is loaded first, then every
setting is read from environment variables with safe local defaults. The
database is selected purely via ``DATABASE_URL`` so the SQLite → PostgreSQL
migration is a config change, not a code change.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from flask import Flask

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

_INSECURE_DEV_KEY = "dev-only-not-a-secret"
_DEFAULT_DB_URI = f"sqlite:///{BASE_DIR / 'instance' / 'defect_tracker.db'}"


def _env_bool(name: str, *, default: bool = False) -> bool:
    """Parse a boolean environment variable ("1", "true", "yes", "on")."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _engine_options(uri: str) -> dict[str, Any]:
    """Backend-appropriate SQLAlchemy engine tuning.

    SQLite gets a generous busy timeout so concurrent writers queue instead
    of failing with "database is locked"; server databases (PostgreSQL) get
    a health-checked connection pool.
    """
    if uri.startswith("sqlite"):
        return {"connect_args": {"timeout": 15}}
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}


class BaseConfig:
    """Settings shared by every environment."""

    CONFIG_NAME: str = "base"

    APP_NAME: str = os.getenv("APP_NAME", "Rupeezy Defect Tracker")
    APP_VERSION: str = "0.1.0"

    DEBUG: bool = False
    TESTING: bool = False

    # `or` (not a default arg) so an empty SECRET_KEY= line in .env still
    # counts as "not configured" and trips the production guard below.
    SECRET_KEY: str = os.getenv("SECRET_KEY") or _INSECURE_DEV_KEY

    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL") or _DEFAULT_DB_URI
    SQLALCHEMY_ENGINE_OPTIONS: dict[str, Any] = _engine_options(SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    REMEMBER_COOKIE_HTTPONLY: bool = True
    REMEMBER_COOKIE_DURATION: timedelta = timedelta(days=30)

    # Werkzeug's default (scrypt) is missing from LibreSSL-built Pythons,
    # e.g. the macOS system Python 3.9. PBKDF2 is available everywhere;
    # 600k iterations follows current OWASP guidance.
    PASSWORD_HASH_METHOD: str = "pbkdf2:sha256:600000"

    UPLOAD_FOLDER: str = os.getenv("UPLOAD_FOLDER") or str(BASE_DIR / "uploads")
    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024
    #: Attachment extension allowlist (screenshots, videos, logs, docs).
    ALLOWED_UPLOAD_EXTENSIONS: frozenset = frozenset({
        "png", "jpg", "jpeg", "gif", "webp",
        "mp4", "mov", "webm", "mkv",
        "txt", "log", "json", "har", "csv", "zip",
        "pdf",
    })

    PAGE_SIZE_DEFAULT: int = 20
    PAGE_SIZE_MAX: int = 100

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR") or str(BASE_DIR / "logs")

    @classmethod
    def init_app(cls, app: Flask) -> None:
        """Environment-specific validation hook; runs right after binding."""


class DevelopmentConfig(BaseConfig):
    """Local development: debugger, optional SQL echo."""

    CONFIG_NAME = "development"
    DEBUG = True
    SQLALCHEMY_ECHO: bool = _env_bool("SQL_ECHO")


class TestingConfig(BaseConfig):
    """Test runs: in-memory database, CSRF off, quiet logs."""

    CONFIG_NAME = "testing"
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"  # in-memory
    SQLALCHEMY_ENGINE_OPTIONS: dict[str, Any] = {}
    WTF_CSRF_ENABLED = False
    LOG_LEVEL = "WARNING"
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1000"  # fast hashes for tests only


class ProductionConfig(BaseConfig):
    """Hardened settings; refuses to boot without a real SECRET_KEY."""

    CONFIG_NAME = "production"
    SESSION_COOKIE_SECURE: bool = _env_bool("SESSION_COOKIE_SECURE")

    @classmethod
    def init_app(cls, app: Flask) -> None:
        super().init_app(app)
        if app.config["SECRET_KEY"] == _INSECURE_DEV_KEY:
            raise RuntimeError(
                "SECRET_KEY is not set. Generate one with "
                "`python3 -c 'import secrets; print(secrets.token_hex(32))'` "
                "and add it to .env before running with APP_ENV=production."
            )


_CONFIGS: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """Resolve a config class from an explicit name or the APP_ENV variable.

    Raises:
        ValueError: if the name is not a known environment.
    """
    key = (name or os.getenv("APP_ENV") or "development").strip().lower()
    try:
        return _CONFIGS[key]
    except KeyError:
        valid = ", ".join(sorted(_CONFIGS))
        raise ValueError(f"Unknown APP_ENV {key!r} — expected one of: {valid}") from None
