"""Strapi board client — the ONLY place in the app that writes to Strapi.

Used exclusively by the "Create as Bug in Strapi" feature (checkbox on the
defect form / list, see app/routes/defects.py). Every write is an explicit,
user-initiated action from the UI — this module makes no calls on its own.

Ticket numbering follows the org convention (sequential ADVA-N, see the
global CLAUDE.md `strapi-board-rule.md`): project is always Advancement (1),
and the id is the next free ADVA-N at write time.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Valid actor_source values on Strapi board-events (enum-validated server
#: side). The tracker's automated writes are "script".
ACTOR_SOURCE = "script"

STRAPI_PROJECT_ID = 1  # Advancement — org-wide invariant, never asked


class StrapiError(Exception):
    """Raised for any Strapi request failure (network, auth, 4xx/5xx)."""


def _base_url() -> str:
    return os.environ.get("STRAPI_URL", "https://blog-admin.rupeezy.dev")


def _token() -> str:
    token = os.environ.get("STRAPI_TOKEN_BOARD")
    if not token:
        raise StrapiError(
            "STRAPI_TOKEN_BOARD is not configured (check defect-tracker/.env)."
        )
    return token


def _request(method: str, path: str, *, params: Optional[dict] = None,
             body: Optional[dict] = None) -> Any:
    url = f"{_base_url()}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise StrapiError(f"Strapi {method} {path} failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise StrapiError(f"Could not reach Strapi ({exc.reason}).") from exc


# ---------------------------------------------------------------------------
# reads (used to populate the dialog and validate input)
# ---------------------------------------------------------------------------
def find_ticket(ticket_id: str) -> Optional[dict]:
    """Look up any ticket (Story, Bug, ...) by its ADVA-N key."""
    d = _request("GET", "/api/board-tickets", params={
        "filters[ticket_id][$eq]": ticket_id,
        "fields[0]": "ticket_id", "fields[1]": "title", "fields[2]": "type",
        "fields[3]": "status",
        "pagination[limit]": 1,
    })
    rows = d.get("data") or []
    if not rows:
        return None
    a = rows[0]["attributes"]
    return {
        "id": rows[0]["id"], "ticket_id": a["ticket_id"], "title": a["title"],
        "type": a["type"], "status": a["status"],
    }


def list_assignable_members() -> list[dict]:
    """Engineering + PM members, for the assignee dropdown."""
    d = _request("GET", "/api/board-members", params={
        "filters[$or][0][team][$eq]": "Engineering",
        "filters[$or][1][team][$eq]": "PM",
        "filters[active][$eq]": "true",
        "fields[0]": "name", "fields[1]": "email", "fields[2]": "team",
        "sort": "name:asc", "pagination[pageSize]": 200,
    })
    out = []
    for m in d.get("data") or []:
        a = m["attributes"]
        if a.get("email"):
            out.append({"id": m["id"], "name": a["name"], "email": a["email"], "team": a.get("team")})
    return out


def find_member_by_email(email: str) -> Optional[dict]:
    d = _request("GET", "/api/board-members", params={
        "filters[email][$eq]": email, "pagination[limit]": 1,
    })
    rows = d.get("data") or []
    if not rows:
        return None
    return {"id": rows[0]["id"], "name": rows[0]["attributes"].get("name")}


def next_ticket_id() -> str:
    """Next sequential ADVA-N, per the org's ticket-numbering convention.

    ``sort: ticket_id:desc`` is a STRING sort — "ADVA-999" sorts after
    "ADVA-1005" (since '9' > '1' lexicographically), so it does not give the
    numerically highest ticket. That bug once produced "ADVA-1000" as "next"
    while ADVA-1000 already existed, and the create failed on a uniqueness
    error. So: page through every ADVA-N ticket_id and take the true max.
    """
    highest = 0
    page = 1
    while True:
        d = _request("GET", "/api/board-tickets", params={
            "filters[ticket_id][$startsWith]": "ADVA-",
            "fields[0]": "ticket_id",
            "pagination[page]": page,
            "pagination[pageSize]": 500,
        })
        rows = d.get("data") or []
        for row in rows:
            raw = row["attributes"]["ticket_id"].split("-", 1)[1]
            if raw.isdigit():
                highest = max(highest, int(raw))
        pagination = d["meta"]["pagination"]
        if page >= pagination["pageCount"]:
            break
        page += 1
    return f"ADVA-{highest + 1}"


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
def create_bug(*, title: str, description: str, priority: str, sprint_id: Optional[int],
               parent_id: Optional[int], points: Optional[int], labels: list[str],
               assignee_member_id: Optional[int], reporter_member_id: Optional[int]) -> dict:
    """Create a type=Bug ticket, return the created ticket's {ticket_id, id}.
    ``parent_id=None`` creates it with no parent story; ``sprint_id=None``
    leaves it unsprinted — both are how a ticket lands in the assignee's
    Backlog on the board."""
    def build(ticket_id: str) -> dict:
        return {"data": {
            "ticket_id": ticket_id,
            "type": "Bug",
            "title": title,
            "description": description or None,
            "status": "To Do",
            "priority": priority,
            "points": points,
            "labels": labels or [],
            "project": STRAPI_PROJECT_ID,
            "sprint": sprint_id,
            "parent": parent_id,
            "assignee": assignee_member_id,
            "reporter": reporter_member_id,
        }}

    ticket_id = next_ticket_id()
    try:
        d = _request("POST", "/api/board-tickets", body=build(ticket_id))
    except StrapiError as exc:
        # One retry on a ticket_id collision (e.g. another create landed
        # between our lookup and this write) — anything else re-raises.
        if "must be unique" not in str(exc):
            raise
        ticket_id = next_ticket_id()
        d = _request("POST", "/api/board-tickets", body=build(ticket_id))

    numeric_id = d["data"]["id"]
    # The ticket is created — the audit event is a nice-to-have. NEVER let an
    # event-log failure raise, or it would orphan the just-created ticket
    # (the caller would roll back its link without deleting the Strapi ticket).
    try:
        log_event(numeric_id, note=f"Created via Rupeezy Defect Tracker (as {ticket_id}).")
    except StrapiError as exc:
        logger.warning("board-events log failed for %s (ticket still created): %s", ticket_id, exc)
    return {"ticket_id": ticket_id, "id": numeric_id}


def log_event(numeric_id: int, *, note: str) -> None:
    _request("POST", "/api/board-events", body={"data": {
        "ticket": numeric_id,
        "event_type": "created",
        "to_value": "To Do",
        "actor_source": ACTOR_SOURCE,  # "defect-tracker" is NOT a valid enum value
        "note": note,
    }})


def update_ticket_status(numeric_id: int, *, from_status: str, to_status: str, note: str) -> None:
    """Used by the "auto-close" sync (see app.services.strapi_push) when a
    defect linked to this ticket is closed in the tracker. The caller has
    already checked ``from_status`` is safe to overwrite."""
    _request("PUT", f"/api/board-tickets/{numeric_id}", body={"data": {"status": to_status}})
    # Same non-fatal rule as log_event above: the status write already
    # succeeded, so an audit-log hiccup must not surface as a failure.
    try:
        _request("POST", "/api/board-events", body={"data": {
            "ticket": numeric_id,
            "event_type": "status_changed",
            "from_value": from_status,
            "to_value": to_status,
            "actor_source": ACTOR_SOURCE,
            "note": note,
        }})
    except StrapiError as exc:
        logger.warning("board-events log failed for ticket %s (status still updated): %s",
                       numeric_id, exc)
