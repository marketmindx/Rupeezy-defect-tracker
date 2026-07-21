"""Sprint / Story / Epic routes, including the expandable story tree.

Viewing is open to every signed-in user; creating and editing agile
entities is Admin/QA work.
"""
from __future__ import annotations

from typing import Any, Dict

import sqlalchemy as sa
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.exceptions import AppError
from app.extensions import db
from app.forms.agile import EpicForm, SprintForm, StoryForm
from app.models import Epic, Sprint, SprintStatus, Story, StoryStatus, UserRole
from app.services.agile import EpicService, SprintService, StoryService
from app.utils.security import role_required

sprints_bp = Blueprint("sprints", __name__, url_prefix="/sprints")

_manage = role_required(UserRole.ADMIN, UserRole.QA)


def _story_reference() -> "Dict[str, Any]":
    return {
        "epics": list(db.session.scalars(sa.select(Epic).order_by(Epic.id.desc()))),
        "sprints": list(
            db.session.scalars(sa.select(Sprint).order_by(Sprint.number.desc()).limit(24))
        ),
    }


def _populate_story_choices(form: StoryForm, ref: "Dict[str, Any]") -> None:
    form.epic_id.choices = [(0, "—")] + [
        (epic.id, f"{epic.key} · {epic.name[:40]}") for epic in ref["epics"]
    ]
    form.sprint_id.choices = [(0, "—")] + [
        (sprint.id, sprint.name) for sprint in ref["sprints"]
    ]


# ---------------------------------------------------------------------------
# sprints
# ---------------------------------------------------------------------------

@sprints_bp.get("/")
def list_sprints():
    return render_template("sprints/list.html", rows=SprintService().list_overview())


@sprints_bp.route("/new", methods=["GET", "POST"])
@_manage
def create_sprint():
    form = SprintForm()
    if form.validate_on_submit():
        try:
            sprint = SprintService().create_sprint(
                actor=current_user,
                name=form.name.data,
                number=form.number.data,
                goal=form.goal.data,
                start_date=form.start_date.data,
                end_date=form.end_date.data,
                status=SprintStatus[form.status.data],
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"Sprint '{sprint.name}' created.", "success")
            return redirect(url_for("sprints.detail", sprint_id=sprint.id))
    return render_template("sprints/sprint_form.html", form=form, sprint=None,
                           heading="New sprint")


@sprints_bp.route("/<int:sprint_id>/edit", methods=["GET", "POST"])
@_manage
def edit_sprint(sprint_id: int):
    service = SprintService()
    sprint = service.get(sprint_id)
    form = SprintForm(obj=sprint)
    if request.method == "GET":
        form.status.data = sprint.status.name
    if form.validate_on_submit():
        try:
            service.update_sprint(
                actor=current_user,
                sprint_id=sprint.id,
                name=form.name.data,
                number=form.number.data,
                goal=form.goal.data,
                start_date=form.start_date.data,
                end_date=form.end_date.data,
                status=SprintStatus[form.status.data],
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash("Sprint updated.", "success")
            return redirect(url_for("sprints.detail", sprint_id=sprint.id))
    return render_template("sprints/sprint_form.html", form=form, sprint=sprint,
                           heading=f"Edit {sprint.name}")


@sprints_bp.get("/<int:sprint_id>")
def detail(sprint_id: int):
    return render_template("sprints/detail.html", **SprintService().detail_context(sprint_id))


# ---------------------------------------------------------------------------
# story tree
# ---------------------------------------------------------------------------

@sprints_bp.get("/stories/")
def tree():
    return render_template(
        "sprints/tree.html",
        groups=StoryService().tree(),
        highlight=request.args.get("story", type=int),
    )


@sprints_bp.route("/stories/new", methods=["GET", "POST"])
@_manage
def create_story():
    form = StoryForm()
    ref = _story_reference()
    _populate_story_choices(form, ref)
    if form.validate_on_submit():
        try:
            story = StoryService().create_story(
                actor=current_user,
                title=form.title.data,
                description=form.description.data,
                epic_id=form.epic_id.data or None,
                sprint_id=form.sprint_id.data or None,
                status=StoryStatus[form.status.data],
                story_points=form.story_points.data,
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"{story.key} created.", "success")
            return redirect(url_for("sprints.tree", story=story.id))
    return render_template("sprints/story_form.html", form=form, story=None,
                           heading="New story")


@sprints_bp.route("/stories/<int:story_id>/edit", methods=["GET", "POST"])
@_manage
def edit_story(story_id: int):
    service = StoryService()
    story = service.get(story_id)
    form = StoryForm(obj=story)
    ref = _story_reference()
    _populate_story_choices(form, ref)
    if request.method == "GET":
        form.status.data = story.status.name
        form.epic_id.data = story.epic_id or 0
        form.sprint_id.data = story.sprint_id or 0
    if form.validate_on_submit():
        try:
            service.update_story(
                actor=current_user,
                story_id=story.id,
                title=form.title.data,
                description=form.description.data,
                epic_id=form.epic_id.data or None,
                sprint_id=form.sprint_id.data or None,
                status=StoryStatus[form.status.data],
                story_points=form.story_points.data,
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"{story.key} updated.", "success")
            return redirect(url_for("sprints.tree", story=story.id))
    return render_template("sprints/story_form.html", form=form, story=story,
                           heading=f"Edit {story.key}")


# ---------------------------------------------------------------------------
# epics
# ---------------------------------------------------------------------------

@sprints_bp.route("/epics/new", methods=["GET", "POST"])
@_manage
def create_epic():
    form = EpicForm()
    if form.validate_on_submit():
        try:
            epic = EpicService().create_epic(
                actor=current_user, name=form.name.data, description=form.description.data
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"{epic.key} created.", "success")
            return redirect(url_for("sprints.tree"))
    return render_template("sprints/epic_form.html", form=form, epic=None,
                           heading="New epic")


@sprints_bp.route("/epics/<int:epic_id>/edit", methods=["GET", "POST"])
@_manage
def edit_epic(epic_id: int):
    service = EpicService()
    epic = service.get(epic_id)
    form = EpicForm(obj=epic)
    if form.validate_on_submit():
        try:
            service.update_epic(
                actor=current_user, epic_id=epic.id,
                name=form.name.data, description=form.description.data,
            )
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"{epic.key} updated.", "success")
            return redirect(url_for("sprints.tree"))
    return render_template("sprints/epic_form.html", form=form, epic=epic,
                           heading=f"Edit {epic.key}")
