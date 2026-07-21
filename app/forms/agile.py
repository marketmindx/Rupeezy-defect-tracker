"""Sprint / Story / Epic forms."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange
from wtforms.validators import Optional as OptionalValidator
from wtforms.validators import ValidationError as WTValidationError

from app.forms.defects import _enum_choices, _opt_int
from app.models.enums import SprintStatus, StoryStatus


class SprintForm(FlaskForm):
    name = StringField("Sprint name", validators=[DataRequired(), Length(2, 120)])
    number = IntegerField(
        "Sprint number", validators=[DataRequired(), NumberRange(min=1)]
    )
    goal = TextAreaField(
        "Goal", validators=[OptionalValidator(), Length(max=2000)], render_kw={"rows": 2}
    )
    start_date = DateField("Start date", validators=[DataRequired()])
    end_date = DateField("End date", validators=[DataRequired()])
    status = SelectField(
        "Status", choices=_enum_choices(SprintStatus), default=SprintStatus.PLANNED.name
    )
    submit = SubmitField("Save sprint")

    def validate_end_date(self, field) -> None:
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise WTValidationError("End date must be on or after the start date.")


class StoryForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(3, 300)])
    description = TextAreaField(
        "Description", validators=[OptionalValidator(), Length(max=10000)],
        render_kw={"rows": 4},
    )
    epic_id = SelectField("Epic", coerce=_opt_int)
    sprint_id = SelectField("Sprint", coerce=_opt_int)
    status = SelectField(
        "Status", choices=_enum_choices(StoryStatus), default=StoryStatus.OPEN.name
    )
    story_points = IntegerField(
        "Story points", validators=[OptionalValidator(), NumberRange(min=0, max=100)]
    )
    submit = SubmitField("Save story")


class EpicForm(FlaskForm):
    name = StringField("Epic name", validators=[DataRequired(), Length(2, 200)])
    description = TextAreaField(
        "Description", validators=[OptionalValidator(), Length(max=10000)],
        render_kw={"rows": 3},
    )
    submit = SubmitField("Save epic")
