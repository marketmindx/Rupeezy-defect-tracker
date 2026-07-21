"""User management forms (admin area)."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp

from app.models.enums import UserRole

_ROLE_CHOICES = [(role.name, role.value) for role in UserRole]


def _username_field() -> StringField:
    """Same rules on create and edit — usernames are renameable."""
    return StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(3, 50),
            Regexp(
                r"^[A-Za-z0-9._-]+$",
                message="Letters, digits, dots, dashes and underscores only.",
            ),
        ],
    )


class UserCreateForm(FlaskForm):
    username = _username_field()
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    full_name = StringField("Full name", validators=[DataRequired(), Length(2, 120)])
    role = SelectField("Role", choices=_ROLE_CHOICES, validators=[DataRequired()])
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, message="At least 8 characters.")],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Create user")


class UserEditForm(FlaskForm):
    username = _username_field()
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    full_name = StringField("Full name", validators=[DataRequired(), Length(2, 120)])
    role = SelectField("Role", choices=_ROLE_CHOICES, validators=[DataRequired()])
    is_active = BooleanField("Active")
    submit = SubmitField("Save changes")


class PasswordResetForm(FlaskForm):
    password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=8, message="At least 8 characters.")],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Reset password")
