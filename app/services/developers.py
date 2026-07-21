"""Developer directory and per-person profile assembly (read-only)."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from app.models import Defect, DefectStatus, Severity, User, UserRole
from app.repositories.developers import DeveloperRepository
from app.services.base import BaseService

# Chart colors keyed by status display value — matches the badge palette.
_STATUS_COLORS = {
    "Open": "#0d6efd",
    "In Progress": "#0dcaf0",
    "Ready for QA": "#ffc107",
    "Retest": "#fd7e14",
    "Verified": "#198754",
    "Closed": "#495057",
    "Rejected": "#6c757d",
    "Duplicate": "#adb5bd",
    "Deferred": "#6c757d",
    "Blocked": "#dc3545",
    "Cannot Reproduce": "#adb5bd",
}


class DeveloperService(BaseService):
    def __init__(self, repository: Optional[DeveloperRepository] = None) -> None:
        self.repository = repository or DeveloperRepository()

    # -- directory -----------------------------------------------------------
    def directory(self) -> "Dict[str, List[Dict[str, Any]]]":
        dev_counts = self.repository.counts_by(Defect.assigned_developer_id)
        qa_counts = self.repository.counts_by(Defect.assigned_qa_id)
        reported = self.repository.reported_counts()

        developers = []
        for user in self.repository.users_with_role(UserRole.DEVELOPER):
            counts = dev_counts.get(user.id, {"total": 0, "done": 0, "critical_open": 0})
            developers.append({
                "user": user,
                "stats": [
                    ("Open", counts["total"] - counts["done"], "primary"),
                    ("Critical", counts["critical_open"], "danger"),
                    ("Resolved", counts["done"], "success"),
                ],
            })

        qa_team = []
        for user in self.repository.users_with_role(UserRole.QA):
            counts = qa_counts.get(user.id, {"total": 0, "done": 0, "critical_open": 0})
            qa_team.append({
                "user": user,
                "stats": [
                    ("QA queue", counts["total"] - counts["done"], "warning"),
                    ("Reported", reported.get(user.id, 0), "primary"),
                    ("Verified+", counts["done"], "success"),
                ],
            })

        return {"developers": developers, "qa_team": qa_team}

    # -- profile -------------------------------------------------------------
    def profile(self, user_id: int) -> "Dict[str, Any]":
        user: User = self.repository.get_or_raise(user_id)
        stats = self.repository.assignment_stats(user_id)
        stats["qa_open"] = self.repository.qa_open_count(user_id)
        stats["reported_total"] = self.repository.reported_count(user_id)
        stats["avg_resolution_days"] = self.repository.avg_resolution_days(user_id)

        status_breakdown = self.repository.status_breakdown(user_id)
        chart = {
            "labels": [status.value for status in DefectStatus],
            "counts": [status_breakdown.get(status, 0) for status in DefectStatus],
            "colors": [_STATUS_COLORS[status.value] for status in DefectStatus],
        }

        show_dev = user.is_developer or stats["assigned_total"] > 0
        show_qa = user.is_qa or stats["qa_open"] > 0
        return {
            "user": user,
            "stats": stats,
            "today": date.today(),
            "severity_open": self.repository.open_severity_breakdown(user_id),
            "severities": list(Severity),
            "chart": chart,
            "show_dev": show_dev,
            "show_qa": show_qa,
            "first_tab": "open" if show_dev else ("qa" if show_qa else "reported"),
            "open_assigned": self.repository.open_assigned(user_id) if show_dev else [],
            "all_assigned": self.repository.all_assigned(user_id) if show_dev else [],
            "qa_queue": self.repository.qa_queue(user_id) if show_qa else [],
            "reported": self.repository.reported(user_id),
        }
