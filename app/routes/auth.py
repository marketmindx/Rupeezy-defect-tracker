"""Sign in / sign out."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from app.exceptions import AuthenticationError
from app.forms.auth import LoginForm
from app.services.auth import AuthService
from app.utils.security import public_route, safe_next_url

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
@public_route
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = AuthService().authenticate(form.identifier.data, form.password.data)
        except AuthenticationError as exc:
            flash(exc.message, "danger")
        else:
            login_user(user, remember=form.remember_me.data)
            flash(f"Welcome back, {user.full_name.split()[0]}!", "success")
            target = safe_next_url(request.args.get("next")) or url_for("main.index")
            return redirect(target)
    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))
