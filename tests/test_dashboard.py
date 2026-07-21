"""Phase 4 dashboard tests: page rendering, chart payload, service aggregates."""
from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import ActivityAction, ActivityLog, DefectStatus, Severity
from app.models.enums import UserRole
from app.services.dashboard import DashboardService
from app.utils.datetime import utcnow
from tests.factories import login, make_defect, make_module, make_sprint, make_user


@pytest.fixture()
def scenario(app) -> dict:
    """A small, fully-known world: 4 defects in one current sprint."""
    qa = make_user(username="dash.qa")
    dev = make_user(role=UserRole.DEVELOPER, full_name="Dev One")
    module = make_module(name="Payments")
    sprint = make_sprint()  # spans today by default
    d1 = make_defect(qa, module, severity=Severity.CRITICAL, assigned_developer=dev, sprint=sprint)
    d2 = make_defect(
        qa, module,
        severity=Severity.HIGH,
        status=DefectStatus.IN_PROGRESS,
        assigned_developer=dev,
        sprint=sprint,
    )
    d3 = make_defect(qa, module, status=DefectStatus.CLOSED, resolved_at=utcnow(), sprint=sprint)
    d4 = make_defect(qa, module, status=DefectStatus.VERIFIED, sprint=sprint)
    db.session.add(
        ActivityLog(
            entity_type="defect", entity_id=d1.id, defect=d1, actor=qa,
            action=ActivityAction.CREATED,
        )
    )
    db.session.commit()
    return {"qa": qa, "dev": dev, "module": module, "sprint": sprint,
            "defects": [d1, d2, d3, d4]}


def _page_payload(response) -> dict:
    match = re.search(
        rb'<script id="dashboard-data"[^>]*>(.*?)</script>', response.data, re.S
    )
    assert match, "dashboard-data JSON blob missing from page"
    return json.loads(match.group(1))


class TestDashboardPage:
    def test_requires_login(self, client) -> None:
        response = client.get("/dashboard/")
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_renders_with_payload(self, client, scenario) -> None:
        login(client, scenario["qa"])
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert b"Dashboard" in response.data
        assert b"chart-trend" in response.data

        payload = _page_payload(response)
        assert payload["severity"]["labels"] == ["Critical", "High", "Medium", "Low"]
        assert payload["severity"]["counts"] == [1, 1, 0, 0]  # open bugs only
        assert payload["open_vs_closed"] == {"open": 2, "done": 2}
        assert payload["workload"]["developers"] == ["Dev One"]
        assert payload["workload"]["series"]["Critical"] == [1]
        assert payload["workload"]["series"]["High"] == [1]
        assert payload["modules"]["labels"] == ["Payments"]
        assert payload["modules"]["counts"] == [2]
        assert sum(payload["aging"]["counts"]) == 2
        assert len(payload["trend"]["labels"]) == DashboardService.TREND_DAYS
        assert sum(payload["trend"]["created"]) == 4
        assert sum(payload["trend"]["resolved"]) == 1

    def test_sprint_progress_rendered(self, client, scenario) -> None:
        login(client, scenario["qa"])
        response = client.get("/dashboard/")
        assert scenario["sprint"].name.encode() in response.data
        assert b"2 of 4 defects completed" in response.data
        assert b"50%" in response.data

    def test_renders_on_empty_database(self, client) -> None:
        login(client, make_user())
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert b"No sprint covers" in response.data
        payload = _page_payload(response)
        assert payload["open_vs_closed"] == {"open": 0, "done": 0}
        assert sum(payload["trend"]["created"]) == 0

    def test_home_redirects_to_dashboard(self, client, scenario) -> None:
        login(client, scenario["qa"])
        response = client.get("/")
        assert response.status_code == 302
        assert "/dashboard/" in response.headers["Location"]


class TestDashboardService:
    def test_tiles(self, scenario) -> None:
        data = DashboardService().overview()
        by_label = {tile["label"]: tile["value"] for tile in data["tiles"]}
        assert by_label["Open bugs"] == 2
        assert by_label["Closed bugs"] == 1
        assert by_label["Critical open"] == 1
        assert by_label["High severity open"] == 1

    def test_sprint_overview(self, scenario) -> None:
        sprint = DashboardService().overview()["sprint"]
        assert sprint is not None
        assert sprint["total"] == 4
        assert sprint["done"] == 2
        assert sprint["completion_pct"] == 50
        assert sprint["days_left"] >= 0

    def test_aging_buckets_cover_old_bugs(self, scenario) -> None:
        old = make_defect(
            scenario["qa"], scenario["module"],
            created_at=utcnow() - timedelta(days=45),
        )
        db.session.commit()
        aging = DashboardService().overview()["charts"]["aging"]
        assert aging["labels"][-1] == "30d+"
        assert aging["counts"][-1] == 1
        assert sum(aging["counts"]) == 3
        assert old.status is DefectStatus.OPEN

    def test_recent_activity_limited_to_ten(self, scenario) -> None:
        for _ in range(15):
            db.session.add(
                ActivityLog(
                    entity_type="defect",
                    entity_id=scenario["defects"][0].id,
                    defect=scenario["defects"][0],
                    actor=scenario["qa"],
                    action=ActivityAction.UPDATED,
                )
            )
        db.session.commit()
        assert len(DashboardService().overview()["recent_activity"]) == 10

    def test_sprints_chart_shape(self, scenario) -> None:
        sprints = DashboardService().overview()["charts"]["sprints"]
        assert sprints["labels"] == [f"S{scenario['sprint'].number}"]
        assert sprints["done"] == [2]
        assert sprints["remaining"] == [2]
