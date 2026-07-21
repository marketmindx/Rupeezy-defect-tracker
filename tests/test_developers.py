"""Phase 7 tests: developer directory, profiles, metrics, and people links."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import DefectStatus, Severity
from app.models.enums import UserRole
from app.services.developers import DeveloperService
from app.utils.datetime import utcnow
from tests.factories import login, make_defect, make_module, make_user


@pytest.fixture()
def world(app, client) -> dict:
    qa = make_user(username="dir.qa", full_name="Meera QA")
    dev = make_user(role=UserRole.DEVELOPER, full_name="Dev Person")
    module = make_module()
    db.session.commit()
    login(client, qa)
    return {"qa": qa, "dev": dev, "module": module}


class TestDirectory:
    def test_requires_login(self, app) -> None:
        # No `world` fixture here: nothing may sign in during this test
        # (see the conftest note on Flask-Login's per-context user cache).
        response = app.test_client().get("/developers/")
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_cards_with_counts_and_links(self, client, world) -> None:
        qa, dev, module = world["qa"], world["dev"], world["module"]
        make_defect(qa, module, assigned_developer=dev, severity=Severity.CRITICAL)
        make_defect(qa, module, assigned_developer=dev)
        make_defect(
            qa, module, assigned_developer=dev,
            status=DefectStatus.CLOSED, resolved_at=utcnow(),
        )
        db.session.commit()

        page = client.get("/developers/").data
        assert b"Dev Person" in page
        assert f'href="/developers/{dev.id}"'.encode() in page
        assert b"Development team" in page and b"QA team" in page
        assert b"Meera QA" in page  # reporter appears in the QA section


class TestProfile:
    def test_developer_metrics(self, client, world) -> None:
        qa, dev, module = world["qa"], world["dev"], world["module"]
        make_defect(
            qa, module, assigned_developer=dev, severity=Severity.CRITICAL,
            eta=date.today() - timedelta(days=2),
        )
        make_defect(
            qa, module, assigned_developer=dev, status=DefectStatus.CLOSED,
            created_at=utcnow() - timedelta(days=4),
            resolved_at=utcnow() - timedelta(days=1),
        )
        db.session.commit()

        stats = DeveloperService().profile(dev.id)["stats"]
        assert stats["assigned_total"] == 2
        assert stats["open"] == 1
        assert stats["done"] == 1
        assert stats["critical_open"] == 1
        assert stats["overdue"] == 1
        assert stats["avg_resolution_days"] == 3.0

        page = client.get(f"/developers/{dev.id}").data
        assert b"Open assigned" in page
        assert b"3.0" in page
        assert f"/defects/?developer={dev.id}".encode() in page

    def test_qa_profile_shows_queue_and_reported(self, client, world) -> None:
        qa, module = world["qa"], world["module"]
        defect = make_defect(qa, module, assigned_qa=qa)
        db.session.commit()

        page = client.get(f"/developers/{qa.id}").data
        assert b"QA queue" in page
        assert defect.defect_key.encode() in page
        assert f"/defects/?qa={qa.id}".encode() in page
        assert f"/defects/?reporter={qa.id}".encode() in page

    def test_unknown_user_redirects_with_flash(self, client, world) -> None:
        # Web paths translate NotFoundError to flash+redirect (Phase 1 design).
        assert client.get("/developers/99999").status_code == 302


class TestLinksAndReporterFilter:
    def test_defect_detail_links_people(self, client, world) -> None:
        qa, dev, module = world["qa"], world["dev"], world["module"]
        defect = make_defect(qa, module, assigned_developer=dev, assigned_qa=qa)
        db.session.commit()

        page = client.get(f"/defects/{defect.defect_key}").data
        assert f'href="/developers/{dev.id}"'.encode() in page
        assert f'href="/developers/{qa.id}"'.encode() in page

    def test_defect_list_links_developer(self, client, world) -> None:
        qa, dev, module = world["qa"], world["dev"], world["module"]
        make_defect(qa, module, assigned_developer=dev)
        db.session.commit()
        page = client.get("/defects/").data
        assert f'href="/developers/{dev.id}"'.encode() in page

    def test_reporter_filter_on_defect_list(self, client, world) -> None:
        qa, module = world["qa"], world["module"]
        other = make_user(username="other.reporter")
        mine = make_defect(qa, module, title="Mine alone")
        theirs = make_defect(other, module, title="Theirs alone")
        db.session.commit()

        page = client.get(f"/defects/?reporter={qa.id}").data
        assert mine.defect_key.encode() in page
        assert theirs.defect_key.encode() not in page
