"""WSGI entry point for production servers, e.g.::

    gunicorn --workers 2 --bind 127.0.0.1:5001 wsgi:app

Also what the ``flask`` CLI auto-discovers, so `flask db migrate`, `flask
routes`, etc. work from the project root without FLASK_APP being set.
"""
from __future__ import annotations

from app import create_app

app = create_app()
