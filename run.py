"""Development entry point.

Usage::

    python run.py

Host/port come from the HOST / PORT environment variables (see .env.example).
Production deployments should use ``wsgi.py`` behind a real WSGI server
instead of this script.
"""
from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        # 5001 by default: macOS AirPlay Receiver occupies 5000.
        port=int(os.getenv("PORT", "5001")),
        debug=app.config["DEBUG"],
    )
