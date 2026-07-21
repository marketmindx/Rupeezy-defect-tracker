"""Defect module forms.

Optional foreign-key selects use ``0`` as the "none" sentinel (coerced by
``_opt_int``); enum selects submit the member *name* and the route converts
to the enum. Choices for reference data are populated per-request in the
route (``_populate_form_choices``).
"""
from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField
from wtforms import (
    BooleanField,
    DateField,
    HiddenField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length
from wtforms.validators import Optional as OptionalValidator
from wtforms.validators import ValidationError as WTValidationError
from wtforms.widgets import CheckboxInput, ListWidget

from app.models.enums import (
    Criticality,
    Environment,
    Platform,
    Priority,
    RegressionStatus,
    Severity,
)


def _opt_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _enum_choices(enum_cls, *, optional: bool = False):
    choices = [(member.name, member.value) for member in enum_cls]
    if optional:
        choices.insert(0, ("", "—"))
    return choices


class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()


class DefectForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(3, 300)])
    description = TextAreaField(
        "Description", validators=[OptionalValidator(), Length(max=10000)],
        render_kw={"rows": 4},
    )
    expected_result = TextAreaField(
        "Expected result", validators=[OptionalValidator(), Length(max=10000)],
        render_kw={"rows": 3},
    )
    actual_result = TextAreaField(
        "Actual result", validators=[OptionalValidator(), Length(max=10000)],
        render_kw={"rows": 3},
    )
    steps_to_reproduce = TextAreaField(
        "Steps to reproduce", validators=[OptionalValidator(), Length(max=10000)],
        render_kw={"rows": 4, "placeholder": "1. …\n2. …"},
    )

    platform = SelectField("Platform", choices=_enum_choices(Platform), validators=[DataRequired()])
    environment = SelectField(
        "Environment", choices=_enum_choices(Environment), default=Environment.QA.name
    )
    app_version = StringField("App version", validators=[OptionalValidator(), Length(max=50)])
    build_number = StringField("Build number", validators=[OptionalValidator(), Length(max=50)])
    os_version = StringField("OS version", validators=[OptionalValidator(), Length(max=50)])
    device_name = StringField("Device", validators=[OptionalValidator(), Length(max=100)])

    severity = SelectField("Severity", choices=_enum_choices(Severity), validators=[DataRequired()])
    priority = SelectField("Priority", choices=_enum_choices(Priority), validators=[DataRequired()])
    criticality = SelectField(
        "Criticality", choices=_enum_choices(Criticality, optional=True),
        validators=[OptionalValidator()],
    )

    module_id = SelectField("Module", coerce=_opt_int)
    feature_id = SelectField("Feature", coerce=_opt_int, validate_choice=False)
    story_id = SelectField("Story", coerce=_opt_int)
    sprint_id = SelectField("Sprint", coerce=_opt_int)
    assigned_qa_id = SelectField("Assigned QA", coerce=_opt_int)
    assigned_developer_id = SelectField("Assigned developer", coerce=_opt_int)

    eta = DateField("ETA", validators=[OptionalValidator()])
    regression_required = BooleanField("Regression required")
    regression_status = SelectField(
        "Regression status", choices=_enum_choices(RegressionStatus, optional=True),
        validators=[OptionalValidator()],
    )

    labels = MultiCheckboxField("Labels", coerce=int)
    tags = StringField(
        "Tags", validators=[OptionalValidator(), Length(max=200)],
        render_kw={"placeholder": "comma, separated, tags"},
    )
    submit = SubmitField("Save defect")

    def validate_module_id(self, field) -> None:
        if not field.data:
            raise WTValidationError("Choose a module.")


class CommentForm(FlaskForm):
    body = TextAreaField(
        "Comment", validators=[DataRequired(), Length(1, 5000)],
        render_kw={"rows": 3, "placeholder": "Add a comment…"},
    )
    parent_id = HiddenField()
    submit = SubmitField("Comment")


class AttachmentUploadForm(FlaskForm):
    files = MultipleFileField("Attachments")
    submit = SubmitField("Upload")
