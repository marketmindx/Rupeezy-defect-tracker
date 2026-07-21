"""Phase 2 schema tests: defaults, relationships, FK rules, seed command."""
from __future__ import annotations

import re
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    ActivityAction,
    ActivityLog,
    Attachment,
    AttachmentKind,
    Comment,
    DefectStatus,
    Label,
    User,
)
from app.models.enums import UserRole
from tests.factories import make_defect, make_module, make_sprint, make_story, make_user


class TestUserModel:
    def test_password_is_hashed_and_verifiable(self, app) -> None:
        user = make_user()
        assert user.password_hash != "Secret@123"
        assert user.check_password("Secret@123") is True
        assert user.check_password("wrong") is False

    def test_username_must_be_unique(self, app) -> None:
        make_user(username="dup")
        with pytest.raises(IntegrityError):
            make_user(username="dup")
        db.session.rollback()

    def test_role_helpers(self, app) -> None:
        assert make_user(role=UserRole.ADMIN).is_admin
        assert make_user(role=UserRole.DEVELOPER).is_developer


class TestDefectBasics:
    def test_defaults_and_key_format(self, app) -> None:
        defect = make_defect(make_user(), make_module())
        assert defect.status is DefectStatus.OPEN
        assert defect.regression_required is False
        assert defect.created_at is not None
        assert re.fullmatch(r"BUG-\d{3,}", defect.defect_key)

    def test_enum_persisted_as_display_value(self, app) -> None:
        defect = make_defect(make_user(), make_module(), status=DefectStatus.IN_PROGRESS)
        db.session.commit()
        raw = db.session.execute(
            sa.text("SELECT status FROM defects WHERE id = :id"), {"id": defect.id}
        ).scalar()
        assert raw == "In Progress"

    def test_relationship_wiring(self, app) -> None:
        reporter = make_user()
        module = make_module()
        sprint = make_sprint()
        story = make_story(sprint=sprint)
        defect = make_defect(reporter, module, story=story, sprint=sprint)

        assert defect in reporter.reported_defects
        assert defect in module.defects
        assert defect in story.defects
        assert defect in sprint.defects

    def test_duplicate_self_reference(self, app) -> None:
        reporter, module = make_user(), make_module()
        original = make_defect(reporter, module)
        dup = make_defect(reporter, module, duplicate_of=original,
                          status=DefectStatus.DUPLICATE)
        assert dup.duplicate_of is original
        assert dup in original.duplicates


class TestForeignKeyRules:
    def _defect_with_children(self):
        user = make_user()
        module = make_module()
        defect = make_defect(user, module)
        label = Label(name=f"label-{uuid4().hex[:8]}")
        defect.labels.append(label)
        parent = Comment(defect=defect, author=user, body="parent")
        db.session.add(parent)
        db.session.add(Comment(defect=defect, author=user, body="reply", parent=parent))
        db.session.add(
            Attachment(
                defect=defect,
                uploaded_by=user,
                kind=AttachmentKind.SCREENSHOT,
                original_filename="s.png",
                stored_filename=f"{uuid4().hex}.png",
                size_bytes=1234,
            )
        )
        db.session.add(
            ActivityLog(
                entity_type="defect",
                entity_id=defect.id,
                defect=defect,
                actor=user,
                action=ActivityAction.CREATED,
            )
        )
        db.session.commit()
        return defect

    def _count(self, table: str) -> int:
        return db.session.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar()

    def test_defect_delete_cascades_children(self, app) -> None:
        defect = self._defect_with_children()
        assert self._count("comments") == 2
        db.session.delete(defect)
        db.session.commit()
        for table in ("comments", "attachments", "activity_log", "defect_labels"):
            assert self._count(table) == 0, table
        assert self._count("labels") == 1  # the label itself survives

    def test_story_delete_nullifies_defect_link(self, app) -> None:
        story = make_story()
        defect = make_defect(make_user(), make_module(), story=story)
        db.session.commit()
        db.session.delete(story)
        db.session.commit()
        assert defect.story_id is None

    def test_sprint_delete_nullifies_defect_link(self, app) -> None:
        sprint = make_sprint()
        defect = make_defect(make_user(), make_module(), sprint=sprint)
        db.session.commit()
        db.session.delete(sprint)
        db.session.commit()
        assert defect.sprint_id is None

    def test_module_delete_blocked_while_defects_exist(self, app) -> None:
        module = make_module()
        make_defect(make_user(), module)
        db.session.commit()
        db.session.delete(module)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_reporter_delete_blocked(self, app) -> None:
        reporter = make_user()
        make_defect(reporter, make_module())
        db.session.commit()
        db.session.delete(reporter)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_assigned_developer_delete_nullifies_assignment(self, app) -> None:
        developer = make_user(role=UserRole.DEVELOPER)
        defect = make_defect(make_user(), make_module(), assigned_developer=developer)
        db.session.commit()
        db.session.delete(developer)
        db.session.commit()
        assert defect.assigned_developer_id is None


class TestCommentsThreading:
    def test_parent_and_replies(self, app) -> None:
        user = make_user()
        defect = make_defect(user, make_module())
        parent = Comment(defect=defect, author=user, body="parent")
        reply = Comment(defect=defect, author=user, body="reply", parent=parent)
        db.session.add_all([parent, reply])
        db.session.commit()
        assert reply.parent is parent
        assert parent.replies == [reply]

    def test_deleting_parent_removes_replies(self, app) -> None:
        user = make_user()
        defect = make_defect(user, make_module())
        parent = Comment(defect=defect, author=user, body="parent")
        db.session.add(parent)
        db.session.add(Comment(defect=defect, author=user, body="reply", parent=parent))
        db.session.commit()
        db.session.delete(parent)
        db.session.commit()
        count = db.session.execute(sa.text("SELECT COUNT(*) FROM comments")).scalar()
        assert count == 0


class TestSprintRules:
    def test_end_before_start_rejected(self, app) -> None:
        from datetime import date, timedelta

        with pytest.raises(IntegrityError):
            make_sprint(end_date=date.today() - timedelta(days=30))
        db.session.rollback()

    def test_completion_pct(self, app) -> None:
        sprint = make_sprint()
        user, module = make_user(), make_module()
        make_defect(user, module, sprint=sprint, status=DefectStatus.CLOSED)
        make_defect(user, module, sprint=sprint, status=DefectStatus.VERIFIED)
        make_defect(user, module, sprint=sprint, status=DefectStatus.OPEN)
        make_defect(user, module, sprint=sprint, status=DefectStatus.BLOCKED)
        assert sprint.completion_pct == 50


class TestSeedCommand:
    def test_seed_populates_and_is_idempotent(self, app) -> None:
        runner = app.test_cli_runner()

        first = runner.invoke(args=["seed"])
        assert first.exit_code == 0, first.output
        assert "Seed complete" in first.output

        users = db.session.scalar(sa.select(sa.func.count()).select_from(User))
        defects = db.session.execute(sa.text("SELECT COUNT(*) FROM defects")).scalar()
        statuses = db.session.execute(sa.text("SELECT COUNT(DISTINCT status) FROM defects")).scalar()
        activity = db.session.execute(sa.text("SELECT COUNT(*) FROM activity_log")).scalar()
        assert users == 6
        assert defects == 20
        assert statuses == 11  # every workflow status is represented
        assert activity > 40

        second = runner.invoke(args=["seed"])
        assert second.exit_code == 0
        assert "skipped" in second.output
