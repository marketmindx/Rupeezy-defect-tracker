#!/usr/bin/env python3
"""Rupeezy Defect Tracker  <-  Strapi board sync (ONE-WAY, read-only).

Pulls the current state of the configured sprints from Strapi and upserts it
into the tracker. Safe to run any number of times — every entity is matched by
a natural key and updated in place, so re-running only brings in what changed.

What it syncs, per sprint in SYNC_SPRINT_IDS:
  • sprint timeline + status
  • Engineering user stories (title, description, points, status, priority,
    labels, and links to the assignee/reporter members)
  • epics and the story -> epic links
  • type=Bug tickets  ->  Defects (title, description, status, priority,
    labels, and a link to the assigned member)

This is CONTENT-ONLY. It never writes back to Strapi, and it never creates,
modifies, deletes, or re-passwords user accounts — members are managed
outside /sync. Defects link only to members that already exist. It also does
not overwrite local QA judgement fields (module, severity, platform,
environment) after a defect's first import, so manual reclassifications stick.

    .venv/bin/python scripts/strapi_sync.py
"""
from __future__ import annotations

import os
import re
import sys
import json
import urllib.parse
import urllib.request
from datetime import datetime, date
from pathlib import Path

# make `app` importable no matter where this is run from
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app import create_app
from app.extensions import db
import sqlalchemy as sa
from app.models import User, Sprint, Story, Defect
from app.models.agile import Epic
from app.models.taxonomy import Module, Feature, Label
from app.models.enums import (
    UserRole, SprintStatus, StoryStatus,
    Platform, Environment, Severity, Priority, DefectStatus, ResolutionType,
)

# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
STRAPI_URL = os.environ.get("STRAPI_URL", "https://blog-admin.rupeezy.dev")
TOKEN = os.environ.get("STRAPI_TOKEN_BOARD")

#: Strapi board-sprint ids to mirror. Add ids here to sync more sprints.
SYNC_SPRINT_IDS = [9, 11]  # Sprint 5, Sprint 6

#: Sourav is both Admin and QA. His Admin login (@asthatrade.com) is kept
#: deliberately clean — defects are reported under his separate QA profile
#: (@rupeezy.in). Never assign or attribute anything to the Admin account.
REPORTER_EMAIL = "sourav.banerjee@rupeezy.in"

#: Route his Admin identity onto his QA identity for any attribution (assignee/
#: reporter), so the Admin profile never accumulates defect work.
ALIAS_EMAIL = {"sourav.banerjee@asthatrade.com": "sourav.banerjee@rupeezy.in"}

#: Members who must never be linked from a defect (wrong team in Strapi).
#: Vidushi Yadav is Design, mislabelled Engineering on the board.
EXCLUDE_MEMBERS = {"vidushi.yadav@asthatrade.com", "vidushi.yadav"}

#: Strapi labels that are pure type-markers — redundant as defect labels.
SKIP_LABELS = {"bug", "defect", "sub-task"}

SPRINT_STATUS = {"Active": SprintStatus.ACTIVE, "Completed": SprintStatus.COMPLETED,
                 "Planned": SprintStatus.PLANNED}
STORY_STATUS = {"To Do": StoryStatus.OPEN, "Backlog": StoryStatus.OPEN,
                "In Progress": StoryStatus.IN_PROGRESS, "In Review": StoryStatus.IN_PROGRESS,
                "Blocked": StoryStatus.IN_PROGRESS, "Done": StoryStatus.DONE,
                "Cancelled": StoryStatus.DONE}
PRIO_TO_PRIORITY = {"Critical": Priority.P0, "High": Priority.P1,
                    "Medium": Priority.P2, "Low": Priority.P3}
PRIO_TO_SEVERITY = {"Critical": Severity.CRITICAL, "High": Severity.HIGH,
                    "Medium": Severity.MEDIUM, "Low": Severity.LOW}
DEFECT_STATUS = {"Done": DefectStatus.CLOSED, "Cancelled": DefectStatus.REJECTED,
                 "To Do": DefectStatus.OPEN, "Backlog": DefectStatus.OPEN,
                 "In Progress": DefectStatus.IN_PROGRESS,
                 "In Review": DefectStatus.READY_FOR_QA, "Blocked": DefectStatus.BLOCKED}

# curated module -> features taxonomy (create-if-missing only)
TAXONOMY = {
    "Onboarding & KYC": ["PAN verification", "Aadhaar & e-Sign", "Bank linking (penny-drop)",
                          "Nominee", "Minor account", "Admin reject", "KYC Web", "Re-KYC"],
    "Trading & Orders": ["Order placement", "Order window (NSE/BSE)", "GTT orders", "Stock SIP",
                         "Basket orders", "MTF & T+5", "Executed / Pending / Rejected orders",
                         "Order charges & margins"],
    "Portfolio & Holdings": ["Holdings", "Positions", "Pledge", "Exit P&L", "Portfolio reports"],
    "Mutual Funds": ["SIP setup", "SWP", "Mandates", "MF Lab", "TER / BER", "ETF Baskets",
                     "Redemption", "MF web pages"],
    "Partner & MFD Platform": ["MFD Home screen", "MFD Portfolio Analysis", "AP consolidated reports",
                               "Commission calculator", "ARN validity", "Creator partner program"],
    "Payments & Autopay": ["UPI Autopay", "Add funds (UPI / G-Pay)", "Netbanking", "Withdrawals",
                           "Payment notifications"],
    "Charts & Market Data": ["TV terminal charts", "OI indicators", "Candle & volume data",
                             "Index data", "Scalper Pro"],
    "Goals": ["Goal creation", "Goal completion", "Edit / Delete goal", "Goal-based investment",
              "Goals redesign"],
    "Watchlist & Scrip Detail": ["Watchlist", "Scrip detail", "BSE / NSE toggle", "Corporate actions"],
    "Web App": ["Web home & landing", "Web accessibility", "Alerts & Basket (web)", "Marketing website"],
    "Platform & App": ["Login & OTP", "Theme & Dark mode", "App performance & crashes",
                       "Flutter / Impeller upgrade", "Deeplinks", "Event badges", "Shimmer / UI states"],
    "Notifications & Analytics": ["Push notifications", "Communication (Mail / PN)",
                                  "MoEngage journeys", "Analytics taxonomy events"],
}
MODULE_RULES = [
    (r"goal", "Goals"),
    (r"kyc|nominee|digilock|\bkra\b|\bmpin\b|admin reject|\bucc\b", "Onboarding & KYC"),
    (r"mandate|\bswp\b|\bsip\b|mf lab|redemption|\bter\b|\bber\b", "Mutual Funds"),
    (r"watchlist", "Watchlist & Scrip Detail"),
    (r"candle|volume|chart|\bindex\b|\bltp\b|\boi\b", "Charts & Market Data"),
    (r"buyback|buy price|tradeengine|trade|nse-bse|switch|commodit|order|\bgtt\b|\bmtf\b", "Trading & Orders"),
    (r"portfolio|p&l|pnl|position|holding|pledge|widget", "Portfolio & Holdings"),
    (r"\bweb\b", "Web App"),
    (r"crash|ios|launch|session|search|persistent|otp|password|login|theme", "Platform & App"),
]
FALLBACK_MODULE = "Platform & App"


# ---------------------------------------------------------------------------
# strapi helpers
# ---------------------------------------------------------------------------
def api(path: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{STRAPI_URL}{path}?{q}",
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def all_tickets(params: dict) -> list:
    out, page = [], 1
    while True:
        params = {**params, "pagination[page]": page, "pagination[pageSize]": 100}
        d = api("/api/board-tickets", params)
        out += d["data"]
        if page >= d["meta"]["pagination"]["pageCount"]:
            return out
        page += 1


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None) if s else None


# ---------------------------------------------------------------------------
# sync steps
# ---------------------------------------------------------------------------
class Counter:
    def __init__(self): self.created = self.updated = 0
    def bump(self, made): self.created += made; self.updated += (not made)
    def __str__(self): return f"{self.created} new, {self.updated} updated"


def ensure_modules():
    made = 0
    for mod_name, features in TAXONOMY.items():
        module = db.session.scalar(sa.select(Module).where(Module.name == mod_name))
        if not module:
            module = Module(name=mod_name); db.session.add(module); db.session.flush(); made += 1
        for f in features:
            if not db.session.scalar(sa.select(Feature.id).where(
                    Feature.module_id == module.id, Feature.name == f)):
                db.session.add(Feature(module=module, name=f))
    db.session.flush()
    return made


def find_existing_user(name, email, cache):
    """Look up an EXISTING tracker user to link a defect to. This sync never
    creates, modifies, or re-passwords user accounts — members are managed
    outside /sync. Returns the matched User, or None if there's no account."""
    if not email and not name:
        return None
    if (email or "").lower() in EXCLUDE_MEMBERS or (name or "").lower() in EXCLUDE_MEMBERS:
        return None
    if email:
        email = ALIAS_EMAIL.get(email.lower(), email)  # keep Admin profile clean
    key = (email or "").lower() or (name or "").lower()
    if key in cache:
        return cache[key]
    # email is the strong key — match on it first so a shared display name can
    # never pull the wrong account (e.g. the Admin "Sourav Banerjee").
    user = None
    if email:
        user = db.session.scalars(sa.select(User).where(
            sa.func.lower(User.email) == email.lower())).first()
    if user is None and name:
        user = db.session.scalars(sa.select(User).where(
            sa.func.lower(User.full_name) == name.lower())).first()
    cache[key] = user
    return user


def classify_module(title, labels, modules):
    hay = (title + " " + " ".join(labels or [])).lower()
    for pat, mod in MODULE_RULES:
        if re.search(pat, hay):
            return modules[mod]
    return modules[FALLBACK_MODULE]


def get_label(name, cache):
    key = name.lower()
    if key not in cache:
        lbl = db.session.scalar(sa.select(Label).where(sa.func.lower(Label.name) == key))
        if lbl is None:
            lbl = Label(name=name[:50])
            db.session.add(lbl)
            db.session.flush()
        cache[key] = lbl
    return cache[key]


def run():
    if not TOKEN:
        sys.exit("ERROR: STRAPI_TOKEN_BOARD not set (add it to defect-tracker/.env).")

    app = create_app()
    with app.app_context():
        modules_made = ensure_modules()
        modules = {m.name: m for m in db.session.scalars(sa.select(Module))}
        user_cache = {}
        label_cache = {}
        linked_members = set()
        sp_ct, st_ct, ep_ct, d_ct = Counter(), Counter(), Counter(), Counter()
        story_epic = {}   # story key -> (epic key, name)
        reporter = db.session.scalar(sa.select(User).where(User.email == REPORTER_EMAIL))
        if reporter is None:  # sync does not create users — the QA account must exist
            sys.exit(f"ERROR: reporter account {REPORTER_EMAIL} not found. "
                     "Add it in the tracker before syncing (sync never creates users).")

        for sid in SYNC_SPRINT_IDS:
            # -- sprint meta --
            meta = api(f"/api/board-sprints/{sid}", {})["data"]["attributes"]
            num_m = re.search(r"(\d+)", meta["name"])
            number = int(num_m.group(1)) if num_m else sid
            sp = db.session.scalar(sa.select(Sprint).where(Sprint.number == number))
            made = sp is None
            if made:
                sp = Sprint(number=number); db.session.add(sp)
            sp.name = f"Sprint {number}"
            sp.start_date = date.fromisoformat(meta["start_date"])
            sp.end_date = date.fromisoformat(meta["end_date"])
            sp.status = SPRINT_STATUS.get(meta.get("status"), SprintStatus.PLANNED)
            sp.strapi_sprint_id = sid  # lets "push to Strapi" target the right sprint
            db.session.flush()
            sp_ct.bump(made)

            # -- engineering stories + owners --
            stories = all_tickets({
                "filters[sprint][id][$eq]": sid, "filters[type][$eq]": "Story",
                "populate[assignee][fields][0]": "name", "populate[assignee][fields][1]": "email",
                "populate[assignee][fields][2]": "team", "populate[assignee][fields][3]": "role",
                "populate[assignee][fields][4]": "active",
                "populate[reporter][fields][0]": "name", "populate[reporter][fields][1]": "email",
                "populate[epic][fields][0]": "epic_id", "populate[epic][fields][1]": "name",
                "fields[0]": "ticket_id", "fields[1]": "title", "fields[2]": "status",
                "fields[3]": "points", "fields[4]": "description", "fields[5]": "priority",
                "fields[6]": "labels"})
            for t in stories:
                a = t["attributes"]
                asg = ((a.get("assignee") or {}).get("data") or {}).get("attributes")
                if not asg or asg.get("team") != "Engineering":
                    continue
                rep = ((a.get("reporter") or {}).get("data") or {}).get("attributes") or {}
                ep = ((a.get("epic") or {}).get("data") or {}).get("attributes")
                if ep:
                    story_epic[a["ticket_id"]] = (ep["epic_id"], ep["name"])
                st = db.session.scalar(sa.select(Story).where(Story.key == a["ticket_id"]))
                made = st is None
                if made:
                    st = Story(key=a["ticket_id"]); db.session.add(st)
                st.title = (a["title"] or "(untitled)")[:300]
                st.status = STORY_STATUS.get(a["status"], StoryStatus.OPEN)
                st.story_points = a["points"] if isinstance(a["points"], int) else None
                st.description = (a.get("description") or "").strip() or None
                st.priority = PRIO_TO_PRIORITY.get(a.get("priority"))
                st.assignee = find_existing_user(asg.get("name"), asg.get("email"), user_cache)
                # Unlike a defect's reporter (a fixed local QA identity), a
                # story's reporter has no source but Strapi — mirror it
                # exactly, including blank when the ticket has none set.
                st.reporter = find_existing_user(rep.get("name"), rep.get("email"), user_cache)
                story_labels_list = a.get("labels") or []
                st.labels = [get_label(l, label_cache) for l in story_labels_list
                             if l and l.lower() not in SKIP_LABELS]
                st.sprint = sp
                st_ct.bump(made)

            # -- bugs -> defects --
            bugs = all_tickets({
                "filters[sprint][id][$eq]": sid, "filters[type][$eq]": "Bug",
                "populate[assignee][fields][0]": "name", "populate[assignee][fields][1]": "email",
                "populate[parent][fields][0]": "ticket_id",
                "fields[0]": "ticket_id", "fields[1]": "title", "fields[2]": "status",
                "fields[3]": "priority", "fields[4]": "labels",
                "fields[5]": "createdAt", "fields[6]": "updatedAt", "fields[7]": "description"})
            for t in bugs:
                a = t["attributes"]; key = a["ticket_id"]
                asg = ((a.get("assignee") or {}).get("data") or {}).get("attributes") or {}
                dev = None
                if asg.get("email") or asg.get("name"):
                    dev = find_existing_user(asg.get("name"), asg.get("email"), user_cache)
                    if dev is not None:
                        linked_members.add(dev.id)
                parent_key = ((a.get("parent") or {}).get("data") or {}).get("attributes", {}).get("ticket_id")
                story = db.session.scalar(sa.select(Story).where(Story.key == parent_key)) if parent_key else None
                labels = a.get("labels") or []
                labels_txt = ", ".join(labels) or "—"
                status = DEFECT_STATUS.get(a["status"], DefectStatus.OPEN)
                terminal = status in (DefectStatus.CLOSED, DefectStatus.REJECTED)
                hay = (a["title"] + " " + labels_txt).lower()
                platform = (Platform.WEB if re.search(r"\bweb\b", hay)
                            else Platform.IOS if "ios" in a["title"].lower()
                            else Platform.API if re.search(r"tradeengine|lambda|backend|\bapi\b", labels_txt.lower())
                            else Platform.ANDROID)
                d = db.session.scalar(sa.select(Defect).where(Defect.defect_key == key))
                made = d is None
                if made:
                    d = Defect(defect_key=key); db.session.add(d)
                    # QA judgement fields — set once, then never overwritten by
                    # sync so manual reclassification (module/severity/…) sticks.
                    d.platform = platform
                    d.environment = Environment.QA
                    d.severity = PRIO_TO_SEVERITY.get(a.get("priority"), Severity.MEDIUM)
                    d.module = classify_module(a["title"], labels, modules)
                    d.created_at = parse_dt(a.get("createdAt"))
                # Strapi-authoritative content — always kept in sync:
                d.title = a["title"][:300]
                d.description = (a.get("description") or "").strip() or None
                d.priority = PRIO_TO_PRIORITY.get(a.get("priority"), Priority.P2)
                d.status = status
                d.story = story
                d.sprint = sp
                d.reporter = reporter
                if dev is not None:            # link to member if one exists; never unassign
                    d.assigned_developer = dev
                d.resolution_type = (ResolutionType.FIXED if status == DefectStatus.CLOSED
                                     else ResolutionType.WONT_FIX if status == DefectStatus.REJECTED else None)
                d.resolved_at = parse_dt(a.get("updatedAt")) if terminal else None
                d.updated_at = parse_dt(a.get("updatedAt"))
                # Strapi labels -> defect labels (for filtering); drop type-markers
                d.labels = [get_label(l, label_cache) for l in labels
                            if l and l.lower() not in SKIP_LABELS]
                d_ct.bump(made)

        # -- epics + story links --
        epic_cache = {}
        for skey, (ekey, ename) in story_epic.items():
            if ekey not in epic_cache:
                e = db.session.scalar(sa.select(Epic).where(Epic.key == ekey))
                made = e is None
                if made:
                    e = Epic(key=ekey); db.session.add(e)
                e.name = ename[:200]
                epic_cache[ekey] = e; ep_ct.bump(made)
            st = db.session.scalar(sa.select(Story).where(Story.key == skey))
            if st:
                st.epic = epic_cache[ekey]

        db.session.commit()

        print("=== Strapi -> Defect Tracker sync complete ===")
        print(f"  Sprints  : {sp_ct}")
        print(f"  Stories  : {st_ct}")
        print(f"  Epics    : {ep_ct}")
        print(f"  Defects  : {d_ct}")
        print(f"  Members  : {len(linked_members)} linked (accounts never modified by sync)")
        if modules_made:
            print(f"  Modules  : {modules_made} created (taxonomy was missing)")
        totals = dict(
            defects=db.session.scalar(sa.select(sa.func.count()).select_from(Defect)),
            open=db.session.scalar(sa.select(sa.func.count()).select_from(Defect).where(
                Defect.status.in_(DefectStatus.open_statuses()))),
            stories=db.session.scalar(sa.select(sa.func.count()).select_from(Story)),
        )
        print(f"  Now holding: {totals['defects']} defects "
              f"({totals['open']} open), {totals['stories']} stories.")


if __name__ == "__main__":
    run()
