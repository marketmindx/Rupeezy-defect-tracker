"""Phase 5 list tests: every filter of the dashboard contract, sorting, paging."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import DefectStatus, Platform, Priority, RegressionStatus, Severity
from app.models.enums import UserRole
from app.utils.datetime import utcnow
from tests.factories import login, make_defect, make_module, make_sprint, make_user


@pytest.fixture()
def world(app, client) -> dict:
    qa = make_user(username="list.qa")
    dev1 = make_user(role=UserRole.DEVELOPER, full_name="Dev Alpha")
    dev2 = make_user(role=UserRole.DEVELOPER, full_name="Dev Beta")
    payments = make_module(name="Payments")
    platform_mod = make_module(name="Platform")
    sprint_now = make_sprint()
    sprint_old = make_sprint(
        start_date=date.today() - timedelta(days=40),
        end_date=date.today() - timedelta(days=26),
    )
    a = make_defect(
        qa, payments, title="UPI mandate timeout", severity=Severity.CRITICAL,
        priority=Priority.P0, platform=Platform.ANDROID, assigned_developer=dev1,
        sprint=sprint_now, regression_required=True,
        regression_status=RegressionStatus.PENDING,
    )
    b = make_defect(
        qa, payments, title="Login OTP fails", severity=Severity.HIGH,
        priority=Priority.P1, platform=Platform.WEB,
        status=DefectStatus.IN_PROGRESS, assigned_developer=dev2, sprint=sprint_now,
    )
    c = make_defect(
        qa, platform_mod, title="Old closed bug", status=DefectStatus.CLOSED,
        resolved_at=utcnow(), created_at=utcnow() - timedelta(days=40),
        sprint=sprint_old,
    )
    d = make_defect(qa, platform_mod, title="Unassigned web bug", platform=Platform.WEB)
    db.session.commit()
    login(client, qa)
    return {
        "qa": qa, "dev1": dev1, "dev2": dev2,
        "payments": payments, "platform_mod": platform_mod,
        "sprint_now": sprint_now, "sprint_old": sprint_old,
        "a": a, "b": b, "c": c, "d": d,
    }


def _page(client, **params):
    return client.get("/defects/", query_string=params).data


class TestFilters:
    def test_q_matches_key_and_title(self, client, world) -> None:
        page = _page(client, q=world["a"].defect_key)
        assert world["a"].defect_key.encode() in page
        assert world["b"].defect_key.encode() not in page

        page = _page(client, q="mandate")
        assert b"UPI mandate timeout" in page
        assert b"Login OTP fails" not in page

    def test_status(self, client, world) -> None:
        page = _page(client, status="In Progress")
        assert world["b"].defect_key.encode() in page
        assert world["a"].defect_key.encode() not in page

    def test_state_open_excludes_terminal(self, client, world) -> None:
        page = _page(client, state="open")
        assert world["a"].defect_key.encode() in page
        assert world["c"].defect_key.encode() not in page

    def test_severity_and_priority(self, client, world) -> None:
        page = _page(client, severity="Critical")
        assert world["a"].defect_key.encode() in page
        assert world["b"].defect_key.encode() not in page

        page = _page(client, priority="P1")
        assert world["b"].defect_key.encode() in page
        assert world["a"].defect_key.encode() not in page

    def test_platform(self, client, world) -> None:
        page = _page(client, platform="Android")
        assert world["a"].defect_key.encode() in page
        assert world["d"].defect_key.encode() not in page

    def test_module_sprint_developer(self, client, world) -> None:
        page = _page(client, module=world["payments"].id)
        assert world["a"].defect_key.encode() in page
        assert world["c"].defect_key.encode() not in page

        page = _page(client, sprint=world["sprint_old"].id)
        assert world["c"].defect_key.encode() in page
        assert world["a"].defect_key.encode() not in page

        page = _page(client, developer=world["dev2"].id)
        assert world["b"].defect_key.encode() in page
        assert world["a"].defect_key.encode() not in page

    def test_assignee_unassigned(self, client, world) -> None:
        page = _page(client, assignee="unassigned", state="open")
        assert world["d"].defect_key.encode() in page
        assert world["a"].defect_key.encode() not in page

    def test_regression(self, client, world) -> None:
        page = _page(client, regression="Pending")
        assert world["a"].defect_key.encode() in page
        assert world["b"].defect_key.encode() not in page

    def test_date_range(self, client, world) -> None:
        recent = (date.today() - timedelta(days=2)).isoformat()
        page = _page(client, created_from=recent)
        assert world["a"].defect_key.encode() in page
        assert world["c"].defect_key.encode() not in page

        old_window = (date.today() - timedelta(days=45)).isoformat()
        page = _page(
            client, created_from=old_window,
            created_to=(date.today() - timedelta(days=30)).isoformat(),
        )
        assert world["c"].defect_key.encode() in page
        assert world["a"].defect_key.encode() not in page


class TestSortingAndPaging:
    def test_sort_by_severity(self, client, world) -> None:
        page = _page(client, sort="severity", dir="asc")
        assert page.index(world["a"].defect_key.encode()) < page.index(
            world["b"].defect_key.encode()
        )
        page = _page(client, sort="severity", dir="desc")
        assert page.index(world["b"].defect_key.encode()) < page.index(
            world["a"].defect_key.encode()
        )

    def test_pagination(self, client, world) -> None:
        for _ in range(20):
            make_defect(world["qa"], world["payments"])
        db.session.commit()
        page2 = client.get("/defects/", query_string={"page": 2})
        assert page2.status_code == 200
        assert b"Showing 21" in page2.data  # 24 defects -> 20 + 4


class TestIntegration:
    def test_requires_login(self, app) -> None:
        anonymous = app.test_client()
        response = anonymous.get("/defects/")
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_dashboard_quick_filters_now_live(self, client, world) -> None:
        page = client.get("/dashboard/").data
        assert b'href="/defects/?state=open"' in page
        assert b'href="/defects/?status=Open"' in page
