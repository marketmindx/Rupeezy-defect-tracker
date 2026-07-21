"""Developer directory and profile pages (read-only, any signed-in user)."""
from __future__ import annotations

from flask import Blueprint, render_template

from app.services.developers import DeveloperService

developers_bp = Blueprint("developers", __name__, url_prefix="/developers")


@developers_bp.get("/")
def directory():
    return render_template("developers/list.html", **DeveloperService().directory())


@developers_bp.get("/<int:user_id>")
def profile(user_id: int):
    return render_template("developers/detail.html", **DeveloperService().profile(user_id))
