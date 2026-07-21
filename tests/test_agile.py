"""Phase 6 tests: sprint CRUD + rollups, stories/epics, and the tree view."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from app.extensions import db
from app.models import ActivityAction, ActivityLog, DefectStatus, Epic, Story
from app.models.enums import UserRole
from app.utils.datetime import utcnow
from tests.factories import (
    login,
    make_defect,
    make_epic,
    make_module,
    make_sprint,
    make_story,
    make_user,
)


@pytest.fixture()
def world(app, client) -> dict:
    qa = make_user(username="agile.qa")
    module = make_module()
    db.session.commit()
    login(client, qa)
    return {"qa": qa, "module": module}


def _activity(entity_type: str, entity_id: int):
    return list(
        db.session.scalars(
            sa.select(ActivityLog).where(
                ActivityLog.entity_type == entity_type,
                ActivityLog.entity_id == entity_id,
            )
        )
    )


class TestSprints:
    def test_create_via_form(self, client, world) -> None:
        start = date.today().isoformat()
        end = (date.today() + timedelta(days=13)).isoformat()
        response = client.post(
            "/sprints/new",
            data={"name": "Sprint 101 — Hardening", "number": "101", "goal": "Ship it",
                  "start_date": start, "end_date": end, "status": "ACTIVE"},
            follow_redirects=True,
        )
        assert b"created" in response.data
        assert b"Sprint 101" in response.data

        from app.models import Sprint
        sprint = db.session.scalar(sa.select(Sprint).where(Sprint.number == 101))
        assert sprint is not None
        assert any(r.action is ActivityAction.CREATED for r in _activity("sprint", sprint.id))

    def test_number_must_be_unique(self, client, world) -> None:
        existing = make_sprint()
        db.session.commit()
        response = client.post(
            "/sprints/new",
            data={"name": "Clash", "number": str(existing.number),
                  "start_date": date.today().isoformat(),
                  "end_date": date.today().isoformat(), "status": "PLANNED"},
        )
        assert b"already exists" in response.data

    def test_end_before_start_rejected_by_form(self, client, world) -> None:
        response = client.post(
            "/sprints/new",
            data={"name": "Backwards", "number": "999",
                  "start_date": date.today().isoformat(),
                  "end_date": (date.today() - timedelta(days=3)).isoformat(),
                  "status": "PLANNED"},
        )
        assert b"End date must be on or after the start date." in response.data

    def test_edit_with_field_audit(self, client, world) -> None:
        sprint = make_sprint(name="Before rename")
        db.session.commit()
        response = client.post(
            f"/sprints/{sprint.id}/edit",
            data={"name": "After rename", "number": str(sprint.number), "goal": "",
                  "start_date": sprint.start_date.isoformat(),
                  "end_date": sprint.end_date.isoformat(), "status": "COMPLETED"},
            follow_redirects=True,
        )
        assert b"Sprint updated." in response.data
        fields = {r.field for r in _activity("sprint", sprint.id)}
        assert {"name", "status"} <= fields

    def test_list_rollup_and_detail_metrics(self, client, world) -> None:
        sprint = make_sprint()
        make_defect(world["qa"], world["module"], sprint=sprint,
                    status=DefectStatus.CLOSED, resolved_at=utcnow())
        make_defect(world["qa"], world["module"], sprint=sprint)
        story = make_story(sprint=sprint)
        make_defect(world["qa"], world["module"], sprint=sprint, story=story)
        db.session.commit()

        listing = client.get("/sprints/").data
        assert b"1/3" in listing  # done/total rollup

        detail = client.get(f"/sprints/{sprint.id}").data
        assert b"33%" in detail
        assert story.key.encode() in detail
        assert f"/defects/?sprint={sprint.id}".encode() in detail

    def test_manage_requires_admin_or_qa(self, client, world) -> None:
        # Same client, re-logged as a developer (see the conftest note on
        # why a second test client must not be mixed into one test).
        dev = make_user(role=UserRole.DEVELOPER)
        db.session.commit()
        client.post("/auth/logout")
        login(client, dev)
        assert client.get("/sprints/").status_code == 200
        assert client.get("/sprints/new").status_code == 403


class TestStoriesAndEpics:
    def test_create_story_via_form(self, client, world) -> None:
        response = client.post(
            "/sprints/stories/new",
            data={"title": "Mandate management screen", "description": "",
                  "epic_id": "0", "sprint_id": "0", "status": "OPEN", "story_points": "5"},
            follow_redirects=True,
        )
        assert b"STORY-001 created." in response.data
        story = db.session.scalar(sa.select(Story))
        assert story.key == "STORY-001"
        assert story.story_points == 5
        assert any(r.action is ActivityAction.CREATED for r in _activity("story", story.id))

    def test_edit_story_moves_epic_and_sprint_with_audit(self, client, world) -> None:
        story = make_story()
        epic = make_epic(name="Autopay rollout")
        sprint = make_sprint()
        db.session.commit()
        response = client.post(
            f"/sprints/stories/{story.id}/edit",
            data={"title": story.title, "description": "", "epic_id": str(epic.id),
                  "sprint_id": str(sprint.id), "status": "IN_PROGRESS", "story_points": ""},
            follow_redirects=True,
        )
        assert b"updated" in response.data
        assert story.epic_id == epic.id
        assert story.sprint_id == sprint.id
        fields = {r.field for r in _activity("story", story.id)}
        assert {"epic", "sprint", "status"} <= fields

    def test_create_epic_via_form(self, client, world) -> None:
        response = client.post(
            "/sprints/epics/new",
            data={"name": "UPI Autopay rollout", "description": "NPCI mandates"},
            follow_redirects=True,
        )
        assert b"EPIC-001 created." in response.data
        epic = db.session.scalar(sa.select(Epic))
        assert epic.key == "EPIC-001"


class TestTree:
    def test_tree_structure(self, client, world) -> None:
        epic = make_epic(name="Payments epic")
        story = make_story(epic=epic, title="Mandate creation")
        defect = make_defect(world["qa"], world["module"], story=story)
        orphan = make_story(title="Orphan story")
        db.session.commit()

        page = client.get("/sprints/stories/").data
        assert epic.key.encode() in page
        assert f'id="story-{story.id}"'.encode() in page
        assert defect.defect_key.encode() in page
        assert b"No epic" in page
        assert orphan.key.encode() in page

    def test_highlight_expands_story(self, client, world) -> None:
        story = make_story()
        db.session.commit()
        page = client.get(f"/sprints/stories/?story={story.id}").data
        assert f'class="collapse show" id="story-{story.id}"'.encode() in page

    def test_defect_detail_links_to_sprint_and_story(self, client, world) -> None:
        sprint = make_sprint()
        story = make_story(sprint=sprint)
        defect = make_defect(world["qa"], world["module"], sprint=sprint, story=story)
        db.session.commit()
        page = client.get(f"/defects/{defect.defect_key}").data
        assert f"/sprints/{sprint.id}".encode() in page
        assert f"/sprints/stories/?story={story.id}".encode() in page
