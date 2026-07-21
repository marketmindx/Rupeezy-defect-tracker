"""Phase 5 workflow tests: creation, editing audit, and the status matrix."""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.exceptions import BusinessRuleError, ValidationError
from app.extensions import db
from app.models import (
    ActivityAction,
    ActivityLog,
    Defect,
    DefectStatus,
    RegressionStatus,
    ResolutionType,
    Severity,
    Tag,
)
from app.models.enums import UserRole
from app.services.defects import DefectService
from tests.factories import login, make_defect, make_module, make_user


@pytest.fixture()
def world(app, client) -> dict:
    qa = make_user(username="wf.qa")
    dev = make_user(role=UserRole.DEVELOPER, full_name="Workflow Dev")
    module = make_module(name="Payments")
    db.session.commit()
    login(client, qa)
    return {"qa": qa, "dev": dev, "module": module}


def _rows(defect_id: int):
    return list(
        db.session.scalars(
            sa.select(ActivityLog).where(
                ActivityLog.entity_type == "defect", ActivityLog.entity_id == defect_id
            )
        )
    )


def _walk(service: DefectService, actor, defect, *path: DefectStatus) -> None:
    for target in path:
        service.change_status(actor=actor, defect_id=defect.id, to_status=target)


class TestCreate:
    def test_create_via_form(self, client, world) -> None:
        response = client.post(
            "/defects/new",
            data={
                "title": "Mandate stuck at PENDING after PIN timeout",
                "description": "Times out on slow networks.",
                "platform": "ANDROID",
                "environment": "UAT",
                "severity": "CRITICAL",
                "priority": "P0",
                "module_id": str(world["module"].id),
                "feature_id": "0",
                "story_id": "0",
                "sprint_id": "0",
                "assigned_qa_id": "0",
                "assigned_developer_id": str(world["dev"].id),
                "tags": "UPI, Android14",
            },
            follow_redirects=True,
        )
        assert b"created" in response.data

        defect = db.session.scalar(sa.select(Defect).order_by(Defect.id.desc()).limit(1))
        assert defect.defect_key == "BUG-001"
        assert defect.status is DefectStatus.OPEN
        assert defect.reporter_id == world["qa"].id
        assert defect.assigned_developer_id == world["dev"].id
        assert sorted(tag.name for tag in defect.tags) == ["android14", "upi"]

        actions = {row.action for row in _rows(defect.id)}
        assert ActivityAction.CREATED in actions
        assert ActivityAction.ASSIGNED in actions

    def test_create_requires_title_and_module(self, client, world) -> None:
        response = client.post(
            "/defects/new",
            data={"title": "", "platform": "WEB", "environment": "QA",
                  "severity": "LOW", "priority": "P3", "module_id": "0"},
        )
        assert b"This field is required." in response.data
        assert b"Choose a module." in response.data
        assert db.session.scalar(sa.select(sa.func.count()).select_from(Defect)) == 0

    def test_feature_must_belong_to_module(self, world) -> None:
        from app.models import Feature, Module

        other = Module(name="Other module")
        feature = Feature(module=other, name="Foreign feature")
        db.session.add_all([other, feature])
        db.session.flush()
        with pytest.raises(ValidationError, match="does not belong"):
            DefectService().create_defect(
                actor=world["qa"],
                data={
                    "title": "Bad placement", "platform": None, "environment": None,
                    "severity": None, "priority": None,
                    "module_id": world["module"].id, "feature_id": feature.id,
                },
            )


class TestEditAudit:
    def test_field_and_assignment_audit(self, world) -> None:
        service = DefectService()
        defect = make_defect(world["qa"], world["module"], severity=Severity.CRITICAL)
        db.session.commit()

        data = {
            "title": defect.title, "description": None, "expected_result": None,
            "actual_result": None, "steps_to_reproduce": None,
            "platform": defect.platform, "environment": defect.environment,
            "app_version": None, "build_number": None, "os_version": None,
            "device_name": None, "severity": Severity.HIGH,
            "priority": defect.priority, "criticality": None,
            "module_id": world["module"].id, "feature_id": None, "story_id": None,
            "sprint_id": None, "assigned_qa_id": None,
            "assigned_developer_id": world["dev"].id, "eta": None,
            "regression_required": False, "regression_status": None,
            "label_ids": [], "tags_csv": "smoke",
        }
        service.update_defect(actor=world["qa"], defect_id=defect.id, data=data)

        assert defect.severity is Severity.HIGH
        assert defect.assigned_developer_id == world["dev"].id
        rows = _rows(defect.id)
        severity_row = next(r for r in rows if r.field == "severity")
        assert (severity_row.old_value, severity_row.new_value) == ("Critical", "High")
        assert any(
            r.action is ActivityAction.ASSIGNED and r.new_value == "Workflow Dev"
            for r in rows
        )
        assert any(r.field == "tags" and r.new_value == "smoke" for r in rows)


class TestWorkflow:
    def test_legal_transition_logs_activity(self, world) -> None:
        service = DefectService()
        defect = make_defect(world["qa"], world["module"])
        db.session.commit()
        service.change_status(
            actor=world["dev"], defect_id=defect.id,
            to_status=DefectStatus.IN_PROGRESS, note="Picking this up",
        )
        assert defect.status is DefectStatus.IN_PROGRESS
        row = next(r for r in _rows(defect.id) if r.action is ActivityAction.STATUS_CHANGED)
        assert (row.old_value, row.new_value) == ("Open", "In Progress")
        assert row.note == "Picking this up"

    def test_illegal_transition_rejected(self, client, world) -> None:
        defect = make_defect(world["qa"], world["module"])
        db.session.commit()
        with pytest.raises(BusinessRuleError, match="Illegal transition"):
            DefectService().change_status(
                actor=world["qa"], defect_id=defect.id, to_status=DefectStatus.VERIFIED
            )
        response = client.post(
            f"/defects/{defect.id}/status",
            data={"to_status": "Verified"},
            follow_redirects=True,
        )
        assert b"Illegal transition" in response.data
        assert defect.status is DefectStatus.OPEN

    def test_duplicate_flow(self, world) -> None:
        service = DefectService()
        original = make_defect(world["qa"], world["module"])
        dup = make_defect(world["qa"], world["module"])
        db.session.commit()

        with pytest.raises(ValidationError, match="original defect"):
            service.change_status(
                actor=world["qa"], defect_id=dup.id, to_status=DefectStatus.DUPLICATE
            )
        service.change_status(
            actor=world["qa"], defect_id=dup.id, to_status=DefectStatus.DUPLICATE,
            duplicate_of_key=original.defect_key.lower(),
        )
        assert dup.duplicate_of_id == original.id
        assert dup.resolution_type is ResolutionType.DUPLICATE
        assert dup.resolved_at is not None

    def test_regression_gate_on_close(self, world) -> None:
        service = DefectService()
        defect = make_defect(
            world["qa"], world["module"],
            regression_required=True, regression_status=RegressionStatus.PENDING,
        )
        db.session.commit()
        _walk(service, world["dev"], defect,
              DefectStatus.IN_PROGRESS, DefectStatus.READY_FOR_QA, DefectStatus.VERIFIED)

        with pytest.raises(BusinessRuleError, match="Regression must pass"):
            service.change_status(
                actor=world["qa"], defect_id=defect.id, to_status=DefectStatus.CLOSED
            )
        defect.regression_status = RegressionStatus.PASSED
        service.change_status(
            actor=world["qa"], defect_id=defect.id, to_status=DefectStatus.CLOSED
        )
        assert defect.status is DefectStatus.CLOSED

    def test_verified_defaults_to_fixed_and_reopen_clears(self, world) -> None:
        service = DefectService()
        defect = make_defect(world["qa"], world["module"])
        db.session.commit()
        _walk(service, world["dev"], defect,
              DefectStatus.IN_PROGRESS, DefectStatus.READY_FOR_QA, DefectStatus.VERIFIED)
        assert defect.resolution_type is ResolutionType.FIXED
        assert defect.resolved_at is not None

        _walk(service, world["qa"], defect, DefectStatus.CLOSED, DefectStatus.RETEST)
        assert defect.status is DefectStatus.RETEST
        assert defect.resolution_type is None
        assert defect.resolved_at is None

    def test_detail_shows_only_allowed_targets(self, client, world) -> None:
        defect = make_defect(world["qa"], world["module"])  # Open
        db.session.commit()
        page = client.get(f"/defects/{defect.defect_key}").data
        assert b'<option value="In Progress"' in page
        assert b'<option value="Verified"' not in page


class TestDelete:
    def test_admin_only(self, client, world) -> None:
        defect = make_defect(world["qa"], world["module"])
        db.session.commit()
        response = client.post(f"/defects/{defect.id}/delete")  # qa session
        assert response.status_code == 403

    def test_admin_delete_keeps_tombstone(self, client, world) -> None:
        admin = make_user(role=UserRole.ADMIN)
        defect = make_defect(world["qa"], world["module"])
        defect_id, key = defect.id, defect.defect_key
        db.session.commit()

        client.post("/auth/logout")
        login(client, admin)
        response = client.post(f"/defects/{defect_id}/delete", follow_redirects=True)
        assert f"{key} deleted.".encode() in response.data
        assert db.session.get(Defect, defect_id) is None

        tombstone = next(r for r in _rows(defect_id) if r.action is ActivityAction.DELETED)
        assert tombstone.defect_id is None
        assert tombstone.note == key
