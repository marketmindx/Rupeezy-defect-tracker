"""Dashboard aggregation — shapes repository rollups into the payload the
overview template and its charts consume. Strictly read-only.

Quick-filter and tile links target the Phase 5 defect list; its filter
contract is defined here first: ``status``, ``severity``, ``priority``,
``state=open`` (any non-terminal status), ``regression``, ``assignee``.
The template renders them as live links only once that endpoint exists.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from app.models import DefectStatus, Priority, Severity
from app.repositories.dashboard import DashboardRepository
from app.utils.datetime import local_day_start_utc, to_local_date, utcnow

_SEVERITY_ORDER = [severity.value for severity in Severity]
_PRIORITY_ORDER = [priority.value for priority in Priority]

#: action value → (icon, bootstrap color) for the activity feed.
ACTIVITY_META: "Dict[str, tuple]" = {
    "created": ("bi-plus-circle", "primary"),
    "status_changed": ("bi-arrow-repeat", "info"),
    "assigned": ("bi-person-check", "success"),
    "commented": ("bi-chat-dots", "secondary"),
    "updated": ("bi-pencil", "secondary"),
    "attachment_added": ("bi-paperclip", "secondary"),
    "attachment_removed": ("bi-paperclip", "danger"),
    "deleted": ("bi-trash", "danger"),
}


def _defects_url(**params: str) -> str:
    return "/defects/?" + urlencode(params)


class DashboardService:
    TREND_DAYS = 30
    AGING_BUCKETS = ((3, "0–3d"), (7, "4–7d"), (14, "8–14d"), (30, "15–30d"), (None, "30d+"))

    def __init__(self, repository: Optional[DashboardRepository] = None) -> None:
        self.repository = repository or DashboardRepository()

    def overview(self) -> "Dict[str, Any]":
        repo = self.repository

        status_counts = repo.count_by_status()
        open_total = sum(c for s, c in status_counts.items() if not s.is_terminal)
        done_total = sum(c for s, c in status_counts.items() if s.is_terminal)
        closed_total = status_counts.get(DefectStatus.CLOSED, 0)
        severity_open = repo.count_open_by_severity()
        priority_open = repo.count_open_by_priority()
        today = repo.counts_today(local_day_start_utc())

        return {
            "tiles": self._tiles(open_total, closed_total, severity_open, today),
            "quick_filters": self._quick_filters(),
            "charts": {
                "trend": self._trend(),
                "open_vs_closed": {"open": open_total, "done": done_total},
                "severity": {
                    "labels": _SEVERITY_ORDER,
                    "counts": [severity_open.get(label, 0) for label in _SEVERITY_ORDER],
                },
                "priority": {
                    "labels": _PRIORITY_ORDER,
                    "counts": [priority_open.get(label, 0) for label in _PRIORITY_ORDER],
                },
                "workload": self._workload(),
                "modules": self._modules(),
                "sprints": self._sprints(),
                "aging": self._aging(),
            },
            "sprint": self._sprint_overview(),
            "recent_activity": repo.recent_activity(limit=10),
            "activity_meta": ACTIVITY_META,
            "today": [
                {"label": "Reported", "value": today["reported"], "icon": "bi-bug", "color": "primary"},
                {"label": "Resolved", "value": today["resolved"], "icon": "bi-check2-circle", "color": "success"},
                {"label": "Status changes", "value": today["status_changes"], "icon": "bi-arrow-repeat", "color": "info"},
                {"label": "Comments", "value": today["comments"], "icon": "bi-chat-dots", "color": "secondary"},
            ],
        }

    # -- sections ---------------------------------------------------------------
    @staticmethod
    def _tiles(open_total: int, closed_total: int, severity_open, today) -> "List[dict]":
        return [
            {
                "label": "Open bugs", "value": open_total,
                "icon": "bi-bug", "color": "primary",
                "sub": f"+{today['reported']} today" if today["reported"] else None,
                "href": _defects_url(state="open"),
            },
            {
                "label": "Closed bugs", "value": closed_total,
                "icon": "bi-check2-circle", "color": "success",
                "sub": f"{today['resolved']} resolved today" if today["resolved"] else None,
                "href": _defects_url(status=DefectStatus.CLOSED.value),
            },
            {
                "label": "Critical open", "value": severity_open.get("Critical", 0),
                "icon": "bi-exclamation-octagon", "color": "danger", "sub": None,
                "href": _defects_url(severity="Critical", state="open"),
            },
            {
                "label": "High severity open", "value": severity_open.get("High", 0),
                "icon": "bi-exclamation-triangle", "color": "warning", "sub": None,
                "href": _defects_url(severity="High", state="open"),
            },
        ]

    @staticmethod
    def _quick_filters() -> "List[dict]":
        chips = [
            ("Open", {"status": "Open"}),
            ("In Progress", {"status": "In Progress"}),
            ("Ready for QA", {"status": "Ready for QA"}),
            ("Blocked", {"status": "Blocked"}),
            ("Critical", {"severity": "Critical", "state": "open"}),
            ("P0", {"priority": "P0", "state": "open"}),
            ("Regression pending", {"regression": "Pending"}),
            ("Unassigned", {"assignee": "unassigned", "state": "open"}),
        ]
        return [{"label": label, "href": _defects_url(**params)} for label, params in chips]

    def _trend(self) -> "Dict[str, list]":
        repo = self.repository
        days = [
            date.today() - timedelta(days=offset)
            for offset in range(self.TREND_DAYS - 1, -1, -1)
        ]
        window_start = local_day_start_utc(self.TREND_DAYS - 1)
        created = Counter(to_local_date(dt) for dt in repo.created_since(window_start))
        resolved = Counter(to_local_date(dt) for dt in repo.resolved_since(window_start))
        return {
            "labels": [day.strftime("%d %b") for day in days],
            "created": [created.get(day, 0) for day in days],
            "resolved": [resolved.get(day, 0) for day in days],
        }

    def _workload(self, max_developers: int = 10) -> "Dict[str, Any]":
        totals: "Dict[str, int]" = defaultdict(int)
        per_dev: "Dict[str, Dict[str, int]]" = defaultdict(lambda: defaultdict(int))
        for name, severity, count in self.repository.workload_rows():
            per_dev[name][severity.value] += count
            totals[name] += count
        developers = sorted(totals, key=lambda name: -totals[name])[:max_developers]
        return {
            "developers": developers,
            "series": {
                label: [per_dev[name].get(label, 0) for name in developers]
                for label in _SEVERITY_ORDER
            },
        }

    def _modules(self) -> "Dict[str, list]":
        rows = self.repository.open_by_module()
        return {"labels": [name for name, _ in rows], "counts": [count for _, count in rows]}

    def _sprints(self) -> "Dict[str, list]":
        rows = list(reversed(self.repository.sprint_rollup()))  # chronological
        return {
            "labels": [f"S{number}" for _, number, _, _ in rows],
            "done": [done for _, _, _, done in rows],
            "remaining": [total - done for _, _, total, done in rows],
        }

    def _aging(self) -> "Dict[str, list]":
        now = utcnow()
        counts = [0] * len(self.AGING_BUCKETS)
        for created_at in self.repository.open_created_dates():
            age_days = (now - created_at).days
            for index, (limit, _) in enumerate(self.AGING_BUCKETS):
                if limit is None or age_days <= limit:
                    counts[index] += 1
                    break
        return {"labels": [label for _, label in self.AGING_BUCKETS], "counts": counts}

    def _sprint_overview(self) -> "Optional[Dict[str, Any]]":
        sprint = self.repository.current_sprint()
        if sprint is None:
            return None
        total, done = self.repository.sprint_stats(sprint.id)
        return {
            "id": sprint.id,
            "name": sprint.name,
            "number": sprint.number,
            "goal": sprint.goal,
            "start_date": sprint.start_date,
            "end_date": sprint.end_date,
            "days_left": max((sprint.end_date - date.today()).days, 0),
            "total": total,
            "done": done,
            "completion_pct": round(done * 100 / total) if total else 0,
            "stories": self.repository.sprint_story_count(sprint.id),
        }
