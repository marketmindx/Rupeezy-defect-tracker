"""User management (admin only)."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.exceptions import AppError
from app.forms.users import PasswordResetForm, UserCreateForm, UserEditForm
from app.models.enums import UserRole
from app.services.users import UserService
from app.utils.security import admin_required

users_bp = Blueprint("users", __name__, url_prefix="/users")


@users_bp.get("/")
@admin_required
def list_users():
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    role_param = request.args.get("role", "")
    status = request.args.get("status", "all")

    role = UserRole[role_param] if role_param in UserRole.__members__ else None
    active = {"active": True, "inactive": False}.get(status)

    pagination = UserService().paginate_users(
        page=page,
        per_page=current_app.config["PAGE_SIZE_DEFAULT"],
        search=q or None,
        role=role,
        active=active,
    )
    return render_template(
        "users/list.html",
        pagination=pagination,
        q=q,
        role_param=role_param,
        status=status,
        roles=list(UserRole),
    )


@users_bp.route("/new", methods=["GET", "POST"])
@admin_required
def create_user():
    form = UserCreateForm()
    if form.validate_on_submit():
        try:
            user = UserService().create_user(
                actor=current_user,
                username=form.username.data,
                email=form.email.data,
                full_name=form.full_name.data,
                role=UserRole[form.role.data],
                password=form.password.data,
                is_active=form.is_active.data,
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"User '{user.username}' created.", "success")
            return redirect(url_for("users.list_users"))
    return render_template("users/new.html", form=form)


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id: int):
    service = UserService()
    user = service.get_user(user_id)
    form = UserEditForm(obj=user)
    password_form = PasswordResetForm()
    if request.method == "GET":
        form.role.data = user.role.name

    if form.validate_on_submit():
        old_username = user.username
        try:
            service.update_profile(
                actor=current_user,
                user_id=user.id,
                username=form.username.data,
                email=form.email.data,
                full_name=form.full_name.data,
                role=UserRole[form.role.data],
                is_active=form.is_active.data,
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash("Profile updated.", "success")
            if user.username != old_username:
                flash(
                    f"Sign-in username changed: '{old_username}' → '{user.username}'.",
                    "info",
                )
            return redirect(url_for("users.edit_user", user_id=user.id))
    return render_template("users/edit.html", form=form, password_form=password_form, user=user)


@users_bp.post("/<int:user_id>/password")
@admin_required
def reset_password(user_id: int):
    form = PasswordResetForm()
    if form.validate_on_submit():
        try:
            UserService().reset_password(
                actor=current_user, user_id=user_id, new_password=form.password.data
            )
            flash("Password reset.", "success")
        except AppError as exc:
            flash(exc.message, "danger")
    else:
        for field_name, errors in form.errors.items():
            label = getattr(form, field_name).label.text
            for error in errors:
                flash(f"{label}: {error}", "danger")
    return redirect(url_for("users.edit_user", user_id=user_id))


@users_bp.post("/<int:user_id>/toggle-active")
@admin_required
def toggle_active(user_id: int):
    try:
        user = UserService().toggle_active(actor=current_user, user_id=user_id)
        flash(
            f"'{user.username}' {'re-activated' if user.is_active else 'deactivated'}.",
            "success",
        )
    except AppError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("users.list_users"))


@users_bp.post("/<int:user_id>/delete")
@admin_required
def delete_user(user_id: int):
    try:
        username = UserService().delete_user(actor=current_user, user_id=user_id)
        flash(f"User '{username}' deleted.", "success")
    except AppError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("users.list_users"))
