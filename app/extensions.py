"""Flask extension singletons.

Extensions are instantiated here (unbound) and attached to the app inside
:func:`app.create_app`. Every module imports them from this file — never from
the application package root — which keeps the import graph acyclic.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

#: Deterministic constraint names. Without these, SQLite constraints are
#: anonymous and Alembic cannot ALTER them (batch mode needs names); with
#: them, the same migrations replay cleanly on PostgreSQL later.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model (SQLAlchemy 2.0 style)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


db = SQLAlchemy(model_class=Base)
migrate = Migrate()
csrf = CSRFProtect()

login_manager = LoginManager()
login_manager.login_view = "auth.login"  # auth blueprint lands in Phase 3
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "warning"
# The user_loader is registered in app/models/user.py, next to the User model.


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
    """Per-connection SQLite hardening; a no-op for other backends.

    * ``foreign_keys=ON`` — SQLite ships with FK enforcement OFF; the schema
      relies on foreign keys and cascade rules, so it must be on for every
      connection.
    * ``journal_mode=WAL`` + ``synchronous=NORMAL`` — readers don't block
      writers, which matters once automation POSTs defects while someone
      is browsing the UI.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
