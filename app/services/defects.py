"""Defect lifecycle: creation, editing with field-level audit, the status
workflow, comments, and attachments.

The WORKFLOW matrix is the single source of truth for legal status moves.
Terminal transitions manage resolution metadata automatically and re-opening
clears it, so a defect's resolution fields always agree with its status.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import sqlalchemy as sa
from flask_sqlalchemy.pagination import Pagination
from werkzeug.datastructures import FileStorage

from app.exceptions import (
    BusinessRuleError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.extensions import db
from app.models import (
    ActivityAction,
    Attachment,
    Comment,
    Defect,
    DefectStatus,
    Feature,
    Label,
    Module,
    RegressionStatus,
    ResolutionType,
    Sprint,
    Story,
    Tag,
    User,
)
from app.repositories.defects import DefectFilters, DefectRepository
from app.services.activity import ActivityService
from app.services.base import BaseService
from app.services.keys import next_key
from app.utils.datetime import utcnow
from app.utils.files import allowed_file, delete_stored, detect_kind, save_upload

#: Legal status moves: {from: {allowed targets}}.
WORKFLOW: "Dict[DefectStatus, set]" = {
    DefectStatus.OPEN: {
        DefectStatus.IN_PROGRESS, DefectStatus.BLOCKED, DefectStatus.DEFERRED,
        DefectStatus.REJECTED, DefectStatus.DUPLICATE, DefectStatus.CANNOT_REPRODUCE,
    },
    DefectStatus.IN_PROGRESS: {
        DefectStatus.READY_FOR_QA, DefectStatus.BLOCKED,
        DefectStatus.DEFERRED, DefectStatus.OPEN,
    },
    DefectStatus.READY_FOR_QA: {
        DefectStatus.RETEST, DefectStatus.VERIFIED, DefectStatus.IN_PROGRESS,
    },
    DefectStatus.RETEST: {DefectStatus.VERIFIED, DefectStatus.IN_PROGRESS},
    DefectStatus.VERIFIED: {DefectStatus.CLOSED, DefectStatus.RETEST},
    DefectStatus.CLOSED: {DefectStatus.RETEST},  # re-open path
    DefectStatus.REJECTED: {DefectStatus.OPEN},
    DefectStatus.DUPLICATE: {DefectStatus.OPEN},
    DefectStatus.DEFERRED: {DefectStatus.OPEN, DefectStatus.IN_PROGRESS},
    DefectStatus.BLOCKED: {
        DefectStatus.IN_PROGRESS, DefectStatus.OPEN, DefectStatus.DEFERRED,
    },
    DefectStatus.CANNOT_REPRODUCE: {DefectStatus.OPEN, DefectStatus.RETEST},
}

#: Resolution auto-applied on entering a terminal status when the caller
#: didn't provide one and the defect doesn't already carry one.
_AUTO_RESOLUTION = {
    DefectStatus.VERIFIED: ResolutionType.FIXED,
    DefectStatus.CLOSED: ResolutionType.FIXED,
    DefectStatus.REJECTED: ResolutionType.NOT_A_BUG,
    DefectStatus.DUPLICATE: ResolutionType.DUPLICATE,
    DefectStatus.DEFERRED: ResolutionType.DEFERRED,
    DefectStatus.CANNOT_REPRODUCE: ResolutionType.CANNOT_REPRODUCE,
}


class DefectService(BaseService):
    def __init__(
        self,
        repository: Optional[DefectRepository] = None,
        activity: Optional[ActivityService] = None,
    ) -> None:
        self.repository = repository or DefectRepository()
        self.activity = activity or ActivityService()

    # -- queries -----------------------------------------------------------
    def get(self, defect_id: int) -> Defect:
        return self.repository.get_or_raise(defect_id)

    def get_detail_by_key(self, defect_key: str) -> Defect:
        defect = self.repository.get_detail(defect_key)
        if defect is None:
            raise NotFoundError(f"No defect with id '{defect_key}'.")
        return defect

    def paginate(self, filters: DefectFilters, *, page: int, per_page: int) -> Pagination:
        return self.repository.paginate_filtered(filters, page=page, per_page=per_page)

    @staticmethod
    def allowed_transitions(defect: Defect) -> "List[DefectStatus]":
        order = list(DefectStatus)
        return sorted(WORKFLOW.get(defect.status, set()), key=order.index)

    # -- creation ------------------------------------------------------------
    def create_defect(self, *, actor: User, data: "Dict[str, Any]") -> Defect:
        self._validate_placement(data)
        defect = Defect(
            defect_key=next_key("defect"),
            title=data["title"],
            description=data.get("description"),
            expected_result=data.get("expected_result"),
            actual_result=data.get("actual_result"),
            steps_to_reproduce=data.get("steps_to_reproduce"),
            platform=data["platform"],
            environment=data["environment"],
            app_version=data.get("app_version"),
            build_number=data.get("build_number"),
            os_version=data.get("os_version"),
            device_name=data.get("device_name"),
            severity=data["severity"],
            priority=data["priority"],
            criticality=data.get("criticality"),
            module_id=data["module_id"],
            feature_id=data.get("feature_id"),
            story_id=data.get("story_id"),
            sprint_id=data.get("sprint_id"),
            assigned_qa_id=data.get("assigned_qa_id"),
            assigned_developer_id=data.get("assigned_developer_id"),
            eta=data.get("eta"),
            regression_required=bool(data.get("regression_required", False)),
            regression_status=data.get("regression_status"),
            reporter=actor,
        )
        # Session membership first: label/tag lookups autoflush, and a
        # constructed-but-unadded defect would trip that flush.
        self.repository.add(defect)
        defect.labels = self._labels_from_ids(data.get("label_ids") or [])
        defect.tags = self._resolve_tags(data.get("tags_csv") or "")
        self.repository.flush()

        self.activity.log(
            entity_type="defect", entity_id=defect.id, defect=defect, actor=actor,
            action=ActivityAction.CREATED, new_value=DefectStatus.OPEN.value,
        )
        if defect.assigned_developer is not None:
            self._log_assignment(defect, actor, "assigned_developer", defect.assigned_developer)
        if defect.assigned_qa is not None:
            self._log_assignment(defect, actor, "assigned_qa", defect.assigned_qa)
        self.commit()
        return defect

    # -- editing ---------------------------------------------------------------
    def update_defect(self, *, actor: User, defect_id: int, data: "Dict[str, Any]") -> Defect:
        defect = self.repository.get_or_raise(defect_id)
        self._validate_placement(data)

        changes: "Dict[str, Tuple[Optional[str], Optional[str]]]" = {}

        def scalar(field: str, new_value, display=lambda value: value) -> None:
            old_value = getattr(defect, field)
            if old_value != new_value:
                changes[field] = (
                    None if old_value is None else str(display(old_value)),
                    None if new_value is None else str(display(new_value)),
                )
                setattr(defect, field, new_value)

        scalar("title", data["title"])
        for field in (
            "description", "expected_result", "actual_result", "steps_to_reproduce",
            "app_version", "build_number", "os_version", "device_name",
        ):
            scalar(field, data.get(field))
        for field in ("platform", "environment", "severity", "priority"):
            scalar(field, data[field], lambda value: value.value)
        scalar("criticality", data.get("criticality"), lambda value: value.value)
        scalar("regression_status", data.get("regression_status"), lambda value: value.value)
        scalar("eta", data.get("eta"), lambda value: value.isoformat())

        new_regression = bool(data.get("regression_required", False))
        if new_regression != defect.regression_required:
            changes["regression_required"] = (
                "Yes" if defect.regression_required else "No",
                "Yes" if new_regression else "No",
            )
            defect.regression_required = new_regression

        self._relation_change(defect, changes, "module_id", data["module_id"], Module, lambda m: m.name)
        self._relation_change(defect, changes, "feature_id", data.get("feature_id"), Feature, lambda f: f.name)
        self._relation_change(defect, changes, "story_id", data.get("story_id"), Story, lambda s: s.key)
        self._relation_change(defect, changes, "sprint_id", data.get("sprint_id"), Sprint, lambda s: s.name)

        assignments: "List[Tuple[str, Optional[User]]]" = []
        for field in ("assigned_developer_id", "assigned_qa_id"):
            new_id = data.get(field)
            if new_id != getattr(defect, field):
                new_user = db.session.get(User, new_id) if new_id else None
                assignments.append((field.replace("_id", ""), new_user))
                setattr(defect, field, new_id)

        new_labels = self._labels_from_ids(data.get("label_ids") or [])
        if {label.id for label in defect.labels} != {label.id for label in new_labels}:
            changes["labels"] = (
                ", ".join(sorted(label.name for label in defect.labels)) or None,
                ", ".join(sorted(label.name for label in new_labels)) or None,
            )
            defect.labels = new_labels

        new_tags = self._resolve_tags(data.get("tags_csv") or "")
        if {tag.name for tag in defect.tags} != {tag.name for tag in new_tags}:
            changes["tags"] = (
                ", ".join(sorted(tag.name for tag in defect.tags)) or None,
                ", ".join(sorted(tag.name for tag in new_tags)) or None,
            )
            defect.tags = new_tags

        if changes:
            self.activity.log_field_changes(
                entity_type="defect", entity_id=defect.id,
                actor=actor, changes=changes, defect=defect,
            )
        for field, user in assignments:
            self._log_assignment(defect, actor, field, user)
        if changes or assignments:
            self.commit()
        return defect

    # -- workflow ----------------------------------------------------------------
    def change_status(
        self,
        *,
        actor: User,
        defect_id: int,
        to_status: DefectStatus,
        resolution_type: Optional[ResolutionType] = None,
        duplicate_of_key: Optional[str] = None,
        root_cause: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Defect:
        defect = self.repository.get_or_raise(defect_id)
        from_status = defect.status
        if to_status is from_status:
            raise BusinessRuleError("The defect is already in that status.")
        if to_status not in WORKFLOW.get(from_status, set()):
            raise BusinessRuleError(
                f"Illegal transition: {from_status.value} → {to_status.value}."
            )
        if (
            to_status is DefectStatus.CLOSED
            and defect.regression_required
            and defect.regression_status is not RegressionStatus.PASSED
        ):
            current = defect.regression_status.value if defect.regression_status else "not started"
            raise BusinessRuleError(
                f"Regression must pass before closing — currently: {current}."
            )
        if to_status is DefectStatus.DUPLICATE:
            original = self.repository.get_by_key(duplicate_of_key or "")
            if original is None:
                raise ValidationError("Enter the id of the original defect (e.g. BUG-012).")
            if original.id == defect.id:
                raise ValidationError("A defect cannot be a duplicate of itself.")
            defect.duplicate_of = original

        if to_status.is_terminal:
            defect.resolution_type = (
                resolution_type or defect.resolution_type or _AUTO_RESOLUTION[to_status]
            )
            if defect.resolved_at is None:
                defect.resolved_at = utcnow()
        else:
            defect.resolution_type = None
            defect.resolved_at = None
            if from_status is DefectStatus.DUPLICATE:
                defect.duplicate_of = None
        if root_cause and root_cause.strip():
            defect.root_cause = root_cause.strip()

        defect.status = to_status
        self.activity.log(
            entity_type="defect", entity_id=defect.id, defect=defect, actor=actor,
            action=ActivityAction.STATUS_CHANGED, field="status",
            old_value=from_status.value, new_value=to_status.value,
            note=(note or "").strip() or None,
        )
        self.commit()
        return defect

    # -- comments -------------------------------------------------------------------
    def add_comment(
        self, *, actor: User, defect_id: int, body: str, parent_id: Optional[int] = None
    ) -> Comment:
        defect = self.repository.get_or_raise(defect_id)
        body = (body or "").strip()
        if not body:
            raise ValidationError("Comment text is required.")
        parent = None
        if parent_id:
            parent = db.session.get(Comment, parent_id)
            if parent is None or parent.defect_id != defect.id:
                raise ValidationError("The comment you are replying to no longer exists.")
        comment = Comment(defect=defect, author=actor, parent=parent, body=body)
        db.session.add(comment)
        db.session.flush()
        self.activity.log(
            entity_type="defect", entity_id=defect.id, defect=defect, actor=actor,
            action=ActivityAction.COMMENTED,
        )
        self.commit()
        return comment

    def delete_comment(self, *, actor: User, comment_id: int) -> int:
        comment = db.session.get(Comment, comment_id)
        if comment is None:
            raise NotFoundError("Comment not found.")
        if comment.author_id != actor.id and not actor.is_admin:
            raise PermissionDeniedError("You can only delete your own comments.")
        defect_id = comment.defect_id
        db.session.delete(comment)
        self.commit()
        return defect_id

    # -- attachments -------------------------------------------------------------------
    def add_attachments(
        self, *, actor: User, defect_id: int, uploads: "List[FileStorage]"
    ) -> "List[Attachment]":
        defect = self.repository.get_or_raise(defect_id)
        uploads = [u for u in (uploads or []) if u and (u.filename or "").strip()]
        if not uploads:
            raise ValidationError("Choose at least one file.")
        for upload in uploads:
            if not allowed_file(upload.filename):
                raise ValidationError(f"File type not allowed: {upload.filename}")

        created: "List[Attachment]" = []
        stored_names: "List[str]" = []
        try:
            for upload in uploads:
                stored_name, size = save_upload(upload)
                stored_names.append(stored_name)
                attachment = Attachment(
                    defect=defect,
                    uploaded_by=actor,
                    kind=detect_kind(upload.filename),
                    original_filename=upload.filename,
                    stored_filename=stored_name,
                    content_type=upload.mimetype,
                    size_bytes=size,
                )
                db.session.add(attachment)
                created.append(attachment)
            db.session.flush()
            for attachment in created:
                self.activity.log(
                    entity_type="defect", entity_id=defect.id, defect=defect, actor=actor,
                    action=ActivityAction.ATTACHMENT_ADDED,
                    note=attachment.original_filename[:255],
                )
            self.commit()
        except Exception:
            db.session.rollback()
            for stored_name in stored_names:
                delete_stored(stored_name)
            raise
        return created

    def delete_attachment(self, *, actor: User, attachment_id: int) -> int:
        attachment = db.session.get(Attachment, attachment_id)
        if attachment is None:
            raise NotFoundError("Attachment not found.")
        if attachment.uploaded_by_id != actor.id and not actor.is_admin:
            raise PermissionDeniedError("You can only delete attachments you uploaded.")
        defect = attachment.defect
        stored_name = attachment.stored_filename
        original_name = attachment.original_filename
        db.session.delete(attachment)
        self.activity.log(
            entity_type="defect", entity_id=defect.id, defect=defect, actor=actor,
            action=ActivityAction.ATTACHMENT_REMOVED, note=original_name[:255],
        )
        self.commit()
        delete_stored(stored_name)
        return defect.id

    # -- deletion ---------------------------------------------------------------------
    def delete_defect(self, *, actor: User, defect_id: int) -> str:
        if not actor.is_admin:
            raise PermissionDeniedError("Only admins can delete defects.")
        defect = self.repository.get_or_raise(defect_id)
        key = defect.defect_key
        stored_names = [a.stored_filename for a in defect.attachments]
        # defect_id stays NULL so this row survives the cascade.
        self.activity.log(
            entity_type="defect", entity_id=defect.id, actor=actor,
            action=ActivityAction.DELETED, note=key,
        )
        self.repository.delete(defect)
        self.commit()
        for stored_name in stored_names:
            delete_stored(stored_name)
        return key

    # -- helpers -----------------------------------------------------------------------
    def _log_assignment(self, defect: Defect, actor: User, field: str, user: "Optional[User]") -> None:
        self.activity.log(
            entity_type="defect", entity_id=defect.id, defect=defect, actor=actor,
            action=ActivityAction.ASSIGNED, field=field,
            new_value=user.full_name if user else "Unassigned",
        )

    @staticmethod
    def _relation_change(defect, changes, field, new_id, model, display) -> None:
        old_id = getattr(defect, field)
        if old_id == new_id:
            return
        old_obj = db.session.get(model, old_id) if old_id else None
        new_obj = db.session.get(model, new_id) if new_id else None
        changes[field] = (
            display(old_obj) if old_obj else None,
            display(new_obj) if new_obj else None,
        )
        setattr(defect, field, new_id)

    @staticmethod
    def _validate_placement(data: "Dict[str, Any]") -> None:
        module = db.session.get(Module, data.get("module_id") or 0)
        if module is None:
            raise ValidationError("Choose a valid module.")
        feature_id = data.get("feature_id")
        if feature_id:
            feature = db.session.get(Feature, feature_id)
            if feature is None or feature.module_id != module.id:
                raise ValidationError(
                    "The selected feature does not belong to the chosen module."
                )

    @staticmethod
    def _labels_from_ids(label_ids: "List[int]") -> "List[Label]":
        if not label_ids:
            return []
        return list(db.session.scalars(sa.select(Label).where(Label.id.in_(label_ids))))

    @staticmethod
    def _resolve_tags(tags_csv: str) -> "List[Tag]":
        names: "List[str]" = []
        for raw in (tags_csv or "").split(","):
            name = raw.strip().lower()[:50]
            if name and name not in names:
                names.append(name)
        if not names:
            return []
        existing = {
            tag.name: tag
            for tag in db.session.scalars(sa.select(Tag).where(Tag.name.in_(names)))
        }
        resolved: "List[Tag]" = []
        for name in names:
            tag = existing.get(name)
            if tag is None:
                tag = Tag(name=name)
                db.session.add(tag)
            resolved.append(tag)
        return resolved
