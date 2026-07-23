""""Create as Bug in Strapi" — a one-way, explicit push of a single defect
into the Strapi board, triggered by a user clicking "Create in Strapi" in
the UI. Also holds the auto-close sync: when a defect closes in the
tracker (see DefectService.change_status), the linked Strapi ticket is
moved to Done alongside it — likewise one-way, and best-effort so a Strapi
hiccup never blocks the local close.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import sqlalchemy as sa

from app.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.extensions import db
from app.integrations.strapi import (
    StrapiError,
    create_bug,
    find_member_by_email,
    find_ticket,
    update_ticket_status,
)
from app.models import ActivityAction, Defect, Sprint, User
from app.services.activity import ActivityService
from app.services.base import BaseService
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)

#: Strapi statuses safe to auto-advance to Done — anything else (In Review,
#: Blocked, Cancelled, already Done, ...) means someone is actively working
#: the board directly, so the auto-close sync leaves it alone.
_AUTO_CLOSABLE_STRAPI_STATUSES = {"To Do", "In Progress"}

#: Defect.severity values already match Strapi's `priority` vocabulary
#: (Critical/High/Medium/Low) — copied as-is, never asked.
_SEVERITY_IS_STRAPI_PRIORITY = True

#: Sentinel the dialog sends for "ad-hoc — no sprint". Strapi has no sprint
#: named "Backlog"; a ticket with no sprint relation is what lands in the
#: assignee's backlog on the Gauntlet board (verified against the live API).
BACKLOG_SENTINEL = "backlog"


def _compose_description(defect: Defect) -> str:
    """Carry forward everything already authored in the tracker, as-is."""
    parts = [defect.description or ""]
    if defect.expected_result:
        parts.append(f"Expected: {defect.expected_result}")
    if defect.actual_result:
        parts.append(f"Actual: {defect.actual_result}")
    if defect.steps_to_reproduce:
        parts.append(f"Steps to reproduce:\n{defect.steps_to_reproduce}")
    return "\n\n".join(p for p in parts if p.strip())


class StrapiPushService(BaseService):
    def get(self, defect_id: int) -> Defect:
        defect = db.session.get(Defect, defect_id)
        if defect is None:
            raise NotFoundError(f"Defect {defect_id} not found.")
        return defect

    def push(self, *, actor: User, defect_id: int, story_key: Optional[str],
              sprint_id: "int | str | None", points: Optional[int], labels: list[str],
              assignee_member_id: Optional[int]) -> Dict[str, Any]:
        """Every field is optional — the user decides what to fill in.

        Rule: no user story number -> no parent, and it goes straight to the
        assignee's Backlog (sprint left unset), regardless of what sprint
        was picked. A sprint is otherwise honored as given; leaving it blank
        also means Backlog. Points, labels, and assignee simply pass through
        (or are omitted) as entered — nothing here invents a value.
        """
        defect = self.get(defect_id)
        if defect.strapi_ticket_id:
            raise BusinessRuleError(
                f"{defect.defect_key} was already pushed to Strapi as {defect.strapi_ticket_id}."
            )

        story_key = (story_key or "").strip().upper()

        strapi_sprint_id: Optional[int] = None
        if story_key and sprint_id and sprint_id != BACKLOG_SENTINEL:
            sprint = db.session.get(Sprint, sprint_id)
            if sprint is None or not sprint.strapi_sprint_id:
                raise ValidationError("That sprint isn't linked to Strapi — pick another, or leave it blank for Backlog.")
            strapi_sprint_id = sprint.strapi_sprint_id

        try:
            parent_id = None
            if story_key:
                parent = find_ticket(story_key)
                if parent is None:
                    raise ValidationError(f"No Strapi ticket found for '{story_key}'.")
                parent_id = parent["id"]

            reporter = find_member_by_email(actor.email)

            result = create_bug(
                title=defect.title,
                description=_compose_description(defect),
                priority=defect.severity.value,
                sprint_id=strapi_sprint_id,  # None -> unsprinted -> Strapi Backlog
                parent_id=parent_id,
                points=points,
                labels=labels,
                assignee_member_id=assignee_member_id,
                reporter_member_id=reporter["id"] if reporter else None,
            )
        except StrapiError as exc:
            raise BusinessRuleError(str(exc)) from exc

        defect.strapi_ticket_id = result["ticket_id"]
        defect.strapi_synced_at = utcnow()
        destination = f"under {story_key}" if story_key else "in the assignee's Backlog"
        ActivityService().log(
            entity_type="defect", entity_id=defect.id, actor=actor,
            action=ActivityAction.UPDATED, defect=defect, field="strapi_ticket_id",
            new_value=result["ticket_id"],
            note=f"Created as {result['ticket_id']} in Strapi, {destination}.",
        )
        self.commit()
        return {"ticket_id": result["ticket_id"], "story_key": story_key or None}


def _linked_ticket_id(defect: Defect) -> Optional[str]:
    """The Strapi ticket a defect maps to, however it got there: pushed
    from the tracker (``strapi_ticket_id``), or the defect itself was
    imported FROM a Strapi Bug ticket by scripts/strapi_sync.py — in which
    case ``defect_key`` already IS the Strapi ticket_id (e.g. "ADVA-1160")."""
    if defect.strapi_ticket_id:
        return defect.strapi_ticket_id
    if defect.defect_key.startswith("ADVA-"):
        return defect.defect_key
    return None


def sync_close_to_strapi(defect: Defect) -> Optional[str]:
    """Best-effort: a defect just closed in the tracker, so move its linked
    Strapi ticket to Done — but only if Strapi still shows it as To Do or
    In Progress, never overwriting a status set by someone working the
    board directly. Returns the new Strapi status if it changed something,
    else None. Never raises — a Strapi failure must not block the local
    close that already happened.
    """
    ticket_id = _linked_ticket_id(defect)
    if not ticket_id:
        return None
    try:
        ticket = find_ticket(ticket_id)
        if ticket is None or ticket["status"] not in _AUTO_CLOSABLE_STRAPI_STATUSES:
            return None
        update_ticket_status(
            ticket["id"], from_status=ticket["status"], to_status="Done",
            note=f"Auto-closed via Rupeezy Defect Tracker ({defect.defect_key} closed).",
        )
        return "Done"
    except StrapiError as exc:
        logger.warning("Strapi auto-close sync failed for %s (%s): %s",
                       defect.defect_key, ticket_id, exc)
        return None
