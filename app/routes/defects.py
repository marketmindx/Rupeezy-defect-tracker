"""Defect module routes: list, create/edit, detail, workflow, comments,
attachments, and secure downloads."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user

from app.exceptions import AppError
from app.extensions import db
from app.forms.defects import AttachmentUploadForm, CommentForm, DefectForm
from app.models import (
    Attachment,
    Criticality,
    Defect,
    DefectStatus,
    Environment,
    Feature,
    Label,
    Module,
    Platform,
    Priority,
    RegressionStatus,
    ResolutionType,
    Severity,
    Sprint,
    Story,
    User,
    UserRole,
)
from app.repositories.defects import DefectFilters
from app.services.defects import DefectService
from app.utils.datetime import local_date_start_utc
from app.utils.security import admin_required

defects_bp = Blueprint("defects", __name__, url_prefix="/defects")


# ---------------------------------------------------------------------------
# parsing / reference-data helpers
# ---------------------------------------------------------------------------

def _enum_by_value(enum_cls, raw: Optional[str]):
    """Display value ("In Progress") → enum member, or None."""
    if not raw:
        return None
    try:
        return enum_cls(raw)
    except ValueError:
        return None


def _parse_date_arg(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_filters() -> DefectFilters:
    args = request.args
    from_day = _parse_date_arg(args.get("created_from"))
    to_day = _parse_date_arg(args.get("created_to"))
    return DefectFilters(
        q=(args.get("q") or "").strip() or None,
        status=_enum_by_value(DefectStatus, args.get("status")),
        state=args.get("state"),
        severity=_enum_by_value(Severity, args.get("severity")),
        priority=_enum_by_value(Priority, args.get("priority")),
        platform=_enum_by_value(Platform, args.get("platform")),
        module_id=args.get("module", type=int),
        sprint_id=args.get("sprint", type=int),
        story_id=args.get("story", type=int),
        developer_id=args.get("developer", type=int),
        qa_id=args.get("qa", type=int),
        reporter_id=args.get("reporter", type=int),
        assignee=args.get("assignee"),
        regression=_enum_by_value(RegressionStatus, args.get("regression")),
        created_from=local_date_start_utc(from_day) if from_day else None,
        created_to=local_date_start_utc(to_day + timedelta(days=1)) if to_day else None,
        sort=args.get("sort", "created"),
        direction="asc" if args.get("dir") == "asc" else "desc",
    )


def _users_by_role(role: UserRole) -> "List[User]":
    return list(
        db.session.scalars(
            sa.select(User)
            .where(User.role == role, User.is_active.is_(True))
            .order_by(User.full_name)
        )
    )


def _reference_data() -> "Dict[str, Any]":
    return {
        "modules": list(db.session.scalars(
            sa.select(Module).where(Module.is_active.is_(True)).order_by(Module.name)
        )),
        "features": list(db.session.scalars(sa.select(Feature).order_by(Feature.name))),
        "stories": list(db.session.scalars(sa.select(Story).order_by(Story.id.desc()).limit(100))),
        "sprints": list(db.session.scalars(sa.select(Sprint).order_by(Sprint.number.desc()).limit(24))),
        "qa_users": _users_by_role(UserRole.QA),
        "developers": _users_by_role(UserRole.DEVELOPER),
        "labels": list(db.session.scalars(sa.select(Label).order_by(Label.name))),
    }


def _populate_form_choices(form: DefectForm, ref: "Dict[str, Any]") -> None:
    form.module_id.choices = [(0, "— choose —")] + [(m.id, m.name) for m in ref["modules"]]
    form.feature_id.choices = [(0, "—")] + [(f.id, f.name) for f in ref["features"]]
    form.story_id.choices = [(0, "—")] + [
        (s.id, f"{s.key} · {s.title[:40]}") for s in ref["stories"]
    ]
    form.sprint_id.choices = [(0, "—")] + [(s.id, s.name) for s in ref["sprints"]]
    form.assigned_qa_id.choices = [(0, "—")] + [(u.id, u.full_name) for u in ref["qa_users"]]
    form.assigned_developer_id.choices = [(0, "—")] + [
        (u.id, u.full_name) for u in ref["developers"]
    ]
    form.labels.choices = [(label.id, label.name) for label in ref["labels"]]


def _prefill_from_defect(form: DefectForm, defect: Defect) -> None:
    """Fix up fields the ``obj=`` constructor can't map (enums, sentinels)."""
    form.platform.data = defect.platform.name
    form.environment.data = defect.environment.name
    form.severity.data = defect.severity.name
    form.priority.data = defect.priority.name
    form.criticality.data = defect.criticality.name if defect.criticality else ""
    form.regression_status.data = (
        defect.regression_status.name if defect.regression_status else ""
    )
    form.feature_id.data = defect.feature_id or 0
    form.story_id.data = defect.story_id or 0
    form.sprint_id.data = defect.sprint_id or 0
    form.assigned_qa_id.data = defect.assigned_qa_id or 0
    form.assigned_developer_id.data = defect.assigned_developer_id or 0
    form.labels.data = [label.id for label in defect.labels]
    form.tags.data = ", ".join(sorted(tag.name for tag in defect.tags))


def _form_payload(form: DefectForm) -> "Dict[str, Any]":
    def txt(value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        return value or None

    return {
        "title": form.title.data.strip(),
        "description": txt(form.description.data),
        "expected_result": txt(form.expected_result.data),
        "actual_result": txt(form.actual_result.data),
        "steps_to_reproduce": txt(form.steps_to_reproduce.data),
        "platform": Platform[form.platform.data],
        "environment": Environment[form.environment.data],
        "app_version": txt(form.app_version.data),
        "build_number": txt(form.build_number.data),
        "os_version": txt(form.os_version.data),
        "device_name": txt(form.device_name.data),
        "severity": Severity[form.severity.data],
        "priority": Priority[form.priority.data],
        "criticality": Criticality[form.criticality.data] if form.criticality.data else None,
        "module_id": form.module_id.data or None,
        "feature_id": form.feature_id.data or None,
        "story_id": form.story_id.data or None,
        "sprint_id": form.sprint_id.data or None,
        "assigned_qa_id": form.assigned_qa_id.data or None,
        "assigned_developer_id": form.assigned_developer_id.data or None,
        "eta": form.eta.data,
        "regression_required": form.regression_required.data,
        "regression_status": (
            RegressionStatus[form.regression_status.data]
            if form.regression_status.data else None
        ),
        "label_ids": form.labels.data or [],
        "tags_csv": form.tags.data or "",
    }


# ---------------------------------------------------------------------------
# list / create / edit
# ---------------------------------------------------------------------------

@defects_bp.get("/")
def list_defects():
    filters = _parse_filters()
    page = request.args.get("page", 1, type=int)
    pagination = DefectService().paginate(
        filters, page=page, per_page=current_app.config["PAGE_SIZE_DEFAULT"]
    )
    ref = _reference_data()
    return render_template(
        "defects/list.html",
        pagination=pagination,
        filters=filters,
        statuses=list(DefectStatus),
        severities=list(Severity),
        priorities=list(Priority),
        platforms=list(Platform),
        modules=ref["modules"],
        sprints=ref["sprints"],
        developers=ref["developers"],
    )


@defects_bp.route("/new", methods=["GET", "POST"])
def create_defect():
    form = DefectForm()
    ref = _reference_data()
    _populate_form_choices(form, ref)
    if form.validate_on_submit():
        try:
            defect = DefectService().create_defect(actor=current_user, data=_form_payload(form))
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"{defect.defect_key} created.", "success")
            return redirect(url_for("defects.detail", defect_key=defect.defect_key))
    return render_template(
        "defects/form.html", form=form, ref=ref, defect=None, heading="Report defect"
    )


@defects_bp.route("/<int:defect_id>/edit", methods=["GET", "POST"])
def edit_defect(defect_id: int):
    service = DefectService()
    defect = service.get(defect_id)
    form = DefectForm(obj=defect)
    ref = _reference_data()
    _populate_form_choices(form, ref)
    if request.method == "GET":
        _prefill_from_defect(form, defect)
    if form.validate_on_submit():
        try:
            service.update_defect(actor=current_user, defect_id=defect.id, data=_form_payload(form))
        except AppError as exc:
            flash(exc.message, "danger")
        else:
            flash(f"{defect.defect_key} updated.", "success")
            return redirect(url_for("defects.detail", defect_key=defect.defect_key))
    return render_template(
        "defects/form.html", form=form, ref=ref, defect=defect,
        heading=f"Edit {defect.defect_key}",
    )


# ---------------------------------------------------------------------------
# detail + workflow
# ---------------------------------------------------------------------------

@defects_bp.get("/<string:defect_key>")
def detail(defect_key: str):
    service = DefectService()
    defect = service.get_detail_by_key(defect_key)

    comment_children: "Dict[int, List]" = {}
    for comment in defect.comments:
        if comment.parent_id:
            comment_children.setdefault(comment.parent_id, []).append(comment)

    return render_template(
        "defects/detail.html",
        defect=defect,
        transitions=service.allowed_transitions(defect),
        resolutions=list(ResolutionType),
        comment_form=CommentForm(),
        upload_form=AttachmentUploadForm(),
        comment_roots=[c for c in defect.comments if c.parent_id is None],
        comment_children=comment_children,
        activities=list(reversed(defect.activities)),
    )


@defects_bp.post("/<int:defect_id>/status")
def change_status(defect_id: int):
    service = DefectService()
    defect = service.get(defect_id)
    target = _enum_by_value(DefectStatus, request.form.get("to_status"))
    if target is None:
        flash("Choose a valid target status.", "danger")
        return redirect(url_for("defects.detail", defect_key=defect.defect_key))
    try:
        service.change_status(
            actor=current_user,
            defect_id=defect_id,
            to_status=target,
            resolution_type=_enum_by_value(ResolutionType, request.form.get("resolution_type")),
            duplicate_of_key=request.form.get("duplicate_of_key"),
            root_cause=request.form.get("root_cause"),
            note=request.form.get("note"),
        )
        flash(f"Status changed to {target.value}.", "success")
    except AppError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("defects.detail", defect_key=defect.defect_key))


@defects_bp.post("/<int:defect_id>/delete")
@admin_required
def delete_defect(defect_id: int):
    try:
        key = DefectService().delete_defect(actor=current_user, defect_id=defect_id)
        flash(f"{key} deleted.", "info")
    except AppError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("defects.list_defects"))


# ---------------------------------------------------------------------------
# comments
# ---------------------------------------------------------------------------

@defects_bp.post("/<int:defect_id>/comments")
def add_comment(defect_id: int):
    defect = DefectService().get(defect_id)
    form = CommentForm()
    if form.validate_on_submit():
        try:
            parent_id = int(form.parent_id.data) if form.parent_id.data else None
        except ValueError:
            parent_id = None
        try:
            DefectService().add_comment(
                actor=current_user, defect_id=defect_id,
                body=form.body.data, parent_id=parent_id,
            )
            flash("Comment added.", "success")
        except AppError as exc:
            flash(exc.message, "danger")
    else:
        flash("Comment text is required.", "danger")
    return redirect(url_for("defects.detail", defect_key=defect.defect_key))


@defects_bp.post("/comments/<int:comment_id>/delete")
def delete_comment(comment_id: int):
    try:
        defect_id = DefectService().delete_comment(actor=current_user, comment_id=comment_id)
    except AppError as exc:
        flash(exc.message, "danger")
        return redirect(url_for("defects.list_defects"))
    flash("Comment deleted.", "info")
    defect = db.session.get(Defect, defect_id)
    return redirect(url_for("defects.detail", defect_key=defect.defect_key))


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

@defects_bp.post("/<int:defect_id>/attachments")
def upload_attachments(defect_id: int):
    defect = DefectService().get(defect_id)
    form = AttachmentUploadForm()
    if form.validate_on_submit():
        try:
            created = DefectService().add_attachments(
                actor=current_user, defect_id=defect_id, uploads=form.files.data
            )
            plural = "s" if len(created) != 1 else ""
            flash(f"{len(created)} file{plural} attached.", "success")
        except AppError as exc:
            flash(exc.message, "danger")
    return redirect(url_for("defects.detail", defect_key=defect.defect_key))


@defects_bp.get("/attachments/<int:attachment_id>/download")
def download_attachment(attachment_id: int):
    attachment = db.session.get(Attachment, attachment_id)
    if attachment is None:
        abort(404)
    inline = request.args.get("inline") == "1"
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        attachment.stored_filename,
        as_attachment=not inline,
        download_name=attachment.original_filename,
    )


@defects_bp.post("/attachments/<int:attachment_id>/delete")
def delete_attachment(attachment_id: int):
    try:
        defect_id = DefectService().delete_attachment(
            actor=current_user, attachment_id=attachment_id
        )
    except AppError as exc:
        flash(exc.message, "danger")
        return redirect(url_for("defects.list_defects"))
    flash("Attachment deleted.", "info")
    defect = db.session.get(Defect, defect_id)
    return redirect(url_for("defects.detail", defect_key=defect.defect_key))
