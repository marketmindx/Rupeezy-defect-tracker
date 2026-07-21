"""Application logging: console always, rotating file outside of tests."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 10


def configure_logging(app: Flask) -> None:
    """Configure the app logger from LOG_LEVEL / LOG_DIR settings.

    Handlers are cleared first so repeated factory calls (tests) don't
    stack duplicates on the shared underlying logger.
    """
    level = getattr(logging, str(app.config["LOG_LEVEL"]).upper(), logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    app.logger.handlers.clear()
    app.logger.setLevel(level)
    app.logger.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    app.logger.addHandler(console)

    if not app.testing:
        log_dir = Path(app.config["LOG_DIR"])
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "defect_tracker.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        app.logger.addHandler(file_handler)

    logging.getLogger("werkzeug").setLevel(logging.INFO if app.debug else logging.WARNING)
