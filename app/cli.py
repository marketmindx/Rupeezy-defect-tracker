"""Application CLI commands.

``flask seed`` — populate an empty database with realistic demo data so
every screen has something to show from Phase 3 onward. Idempotent: it
refuses to run against a database that already has users. To start over,
delete ``instance/defect_tracker.db``, then ``flask db upgrade && flask seed``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import click
import sqlalchemy as sa
from flask import Flask

from app.extensions import db
from app.models import (
    ActivityAction,
    ActivityLog,
    Comment,
    Criticality,
    Defect,
    DefectStatus,
    Environment,
    Epic,
    Feature,
    Label,
    Module,
    Platform,
    Priority,
    RegressionStatus,
    ResolutionType,
    Severity,
    Sprint,
    SprintStatus,
    Story,
    StoryStatus,
    Tag,
    User,
    UserRole,
)
from app.services.keys import next_key
from app.utils.datetime import utcnow

DEMO_PASSWORD = "Password@123"

#: Hours between seeded workflow transitions (spread history realistically).
_STEP_HOURS = 16

#: Final status → path of transitions walked from Open.
_STATUS_PATHS: "dict[DefectStatus, list[DefectStatus]]" = {
    DefectStatus.OPEN: [],
    DefectStatus.IN_PROGRESS: [DefectStatus.IN_PROGRESS],
    DefectStatus.READY_FOR_QA: [DefectStatus.IN_PROGRESS, DefectStatus.READY_FOR_QA],
    DefectStatus.RETEST: [
        DefectStatus.IN_PROGRESS, DefectStatus.READY_FOR_QA, DefectStatus.RETEST,
    ],
    DefectStatus.VERIFIED: [
        DefectStatus.IN_PROGRESS, DefectStatus.READY_FOR_QA, DefectStatus.VERIFIED,
    ],
    DefectStatus.CLOSED: [
        DefectStatus.IN_PROGRESS, DefectStatus.READY_FOR_QA,
        DefectStatus.VERIFIED, DefectStatus.CLOSED,
    ],
    DefectStatus.REJECTED: [DefectStatus.REJECTED],
    DefectStatus.DUPLICATE: [DefectStatus.DUPLICATE],
    DefectStatus.DEFERRED: [DefectStatus.DEFERRED],
    DefectStatus.BLOCKED: [DefectStatus.IN_PROGRESS, DefectStatus.BLOCKED],
    DefectStatus.CANNOT_REPRODUCE: [DefectStatus.CANNOT_REPRODUCE],
}

#: Default resolution per terminal status (spec may override with "resolution").
_DEFAULT_RESOLUTIONS = {
    DefectStatus.VERIFIED: ResolutionType.FIXED,
    DefectStatus.CLOSED: ResolutionType.FIXED,
    DefectStatus.REJECTED: ResolutionType.NOT_A_BUG,
    DefectStatus.DUPLICATE: ResolutionType.DUPLICATE,
    DefectStatus.DEFERRED: ResolutionType.DEFERRED,
    DefectStatus.CANNOT_REPRODUCE: ResolutionType.CANNOT_REPRODUCE,
}


def register_cli(app: Flask) -> None:
    """Attach CLI commands to the application."""

    @app.cli.command("seed")
    def seed() -> None:
        """Populate an empty database with demo data."""
        if db.session.scalar(sa.select(sa.func.count()).select_from(User)):
            click.echo("Database already contains users — seeding skipped.")
            return

        users = _seed_users()
        modules, features = _seed_modules()
        sprints = _seed_sprints()
        stories = _seed_agile(sprints)
        labels, tags = _seed_vocabulary()
        defects = _seed_defects(users, modules, features, sprints, stories, labels, tags)
        comment_count = _seed_comments(users, defects)
        db.session.commit()

        activity_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(ActivityLog)
        )
        click.echo("Seed complete:")
        click.echo(
            f"  {len(users)} users · {len(modules)} modules · {len(features)} features · "
            f"{len(sprints)} sprints · {len(stories)} stories · {len(defects)} defects · "
            f"{comment_count} comments · {activity_count} activity entries"
        )
        click.echo(f"\nAll demo accounts share the password: {DEMO_PASSWORD}")
        for user in users.values():
            click.echo(f"  {user.username:<12} {user.role.value:<10} {user.email}")


# ---------------------------------------------------------------------------
# seed helpers
# ---------------------------------------------------------------------------

def _seed_users() -> "Dict[str, User]":
    spec = {
        "admin": ("admin", "Aditi Rao", UserRole.ADMIN),
        "priya": ("priya.qa", "Priya Nair", UserRole.QA),
        "rahul": ("rahul.qa", "Rahul Verma", UserRole.QA),
        "arjun": ("arjun.dev", "Arjun Mehta", UserRole.DEVELOPER),
        "sneha": ("sneha.dev", "Sneha Kulkarni", UserRole.DEVELOPER),
        "vikram": ("vikram.dev", "Vikram Singh", UserRole.DEVELOPER),
    }
    users: "Dict[str, User]" = {}
    for key, (username, full_name, role) in spec.items():
        user = User(
            username=username,
            email=f"{username}@rupeezy.in",
            full_name=full_name,
            role=role,
        )
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        users[key] = user
    db.session.flush()
    return users


def _seed_modules() -> "Tuple[Dict[str, Module], Dict[str, Feature]]":
    spec = {
        "kyc": ("Onboarding & KYC", ["PAN verification", "Bank account linking", "Selfie & liveness"]),
        "orders": ("Trading & Orders", ["Order placement", "Order book", "GTT orders"]),
        "payments": ("Payments", ["UPI collect", "Netbanking", "Withdrawals"]),
        "mf": ("Mutual Funds", ["SIP setup", "Lumpsum purchase", "Redemption"]),
        "platform": ("Platform", ["Login & OTP", "Push notifications", "App performance"]),
    }
    modules: "Dict[str, Module]" = {}
    features: "Dict[str, Feature]" = {}
    for key, (name, feature_names) in spec.items():
        module = Module(name=name)
        db.session.add(module)
        modules[key] = module
        for feature_name in feature_names:
            feature = Feature(module=module, name=feature_name)
            db.session.add(feature)
            features[f"{key}:{feature_name}"] = feature
    db.session.flush()
    return modules, features


def _seed_sprints() -> "Dict[str, Sprint]":
    today = date.today()
    s13_start = today - timedelta(days=4)
    s13 = Sprint(
        name="Sprint 13 — July II",
        number=13,
        start_date=s13_start,
        end_date=s13_start + timedelta(days=13),
        status=SprintStatus.ACTIVE,
        goal="UPI Autopay rollout + regression hardening",
    )
    s12 = Sprint(
        name="Sprint 12 — July I",
        number=12,
        start_date=s13_start - timedelta(days=14),
        end_date=s13_start - timedelta(days=1),
        status=SprintStatus.COMPLETED,
        goal="Payments stability and app performance",
    )
    db.session.add_all([s12, s13])
    db.session.flush()
    return {"s12": s12, "s13": s13}


def _seed_agile(sprints: "Dict[str, Sprint]") -> "Dict[str, Story]":
    epic = Epic(
        key=next_key("epic"),
        name="UPI Autopay rollout",
        description="Recurring-payment mandates across app and web, per NPCI guidelines.",
    )
    db.session.add(epic)

    def make_story(**kwargs) -> Story:
        # Key first, add immediately: next_key() autoflushes the session,
        # so no constructed-but-unadded Story may exist when it runs.
        story = Story(key=next_key("story"), epic=epic, **kwargs)
        db.session.add(story)
        return story

    stories = {
        "st1": make_story(
            title="UPI Autopay mandate creation",
            sprint=sprints["s13"],
            status=StoryStatus.IN_PROGRESS,
            story_points=8,
        ),
        "st2": make_story(
            title="Mandate management screen",
            sprint=sprints["s13"],
            status=StoryStatus.OPEN,
            story_points=5,
        ),
        "st3": make_story(
            title="Autopay backend APIs",
            sprint=sprints["s12"],
            status=StoryStatus.DONE,
            story_points=8,
        ),
    }
    db.session.flush()
    return stories


def _seed_vocabulary() -> "Tuple[Dict[str, Label], Dict[str, Tag]]":
    labels = {
        name: Label(name=name, color=color)
        for name, color in [
            ("regression", "#d63384"),
            ("ui", "#0d6efd"),
            ("crash", "#dc3545"),
            ("payment-critical", "#fd7e14"),
        ]
    }
    tags = {
        name: Tag(name=name)
        for name in ["upi", "android14", "ios18", "login", "sip", "chart"]
    }
    db.session.add_all(labels.values())
    db.session.add_all(tags.values())
    db.session.flush()
    return labels, tags


# Each entry drives one defect. Optional keys default sensibly in _build_defect.
_DEFECT_SPECS: "List[dict]" = [
    dict(
        title="Mandate creation fails with UPI PIN timeout on slow networks",
        platform=Platform.ANDROID, severity=Severity.CRITICAL, priority=Priority.P0,
        status=DefectStatus.IN_PROGRESS, module="payments", feature="payments:UPI collect",
        story="st1", sprint="s13", dev="arjun", qa="priya", days_ago=3,
        environment=Environment.UAT, device="Pixel 8", os="Android 14",
        app_version="5.12.0", build="5120", criticality=Criticality.HIGH, eta_days=2,
        labels=["payment-critical"], tags=["upi"],
        description="Mandate creation aborts when the UPI PIN screen takes >30s on 3G-class networks.",
        steps="1. Throttle network to 3G\n2. Start Autopay mandate creation\n3. Wait on the PIN screen for 30s\n4. Submit PIN",
        expected="Mandate is created; slow PIN entry does not abort the flow.",
        actual="Flow times out and shows a generic failure toast; mandate stuck in PENDING.",
    ),
    dict(
        title="Autopay mandate list shows duplicate entries after pull-to-refresh",
        platform=Platform.ANDROID, severity=Severity.MEDIUM, priority=Priority.P2,
        status=DefectStatus.OPEN, module="payments", feature="payments:UPI collect",
        story="st1", sprint="s13", reporter="priya", days_ago=2,
        device="Samsung S23", os="Android 14", app_version="5.12.0", build="5120",
        tags=["upi"],
        description="Refreshing the mandate list appends the page instead of replacing it.",
    ),
    dict(
        title="Mandate amount above ₹15,000 not blocked client-side",
        platform=Platform.WEB, severity=Severity.HIGH, priority=Priority.P1,
        status=DefectStatus.READY_FOR_QA, module="payments", feature="payments:UPI collect",
        story="st1", sprint="s13", dev="sneha", qa="rahul", days_ago=4,
        environment=Environment.STAGING, criticality=Criticality.HIGH, eta_days=1,
        tags=["upi"],
        description="NPCI cap for UPI Autopay without PIN is ₹15,000; the web form only validates server-side.",
    ),
    dict(
        title="Autopay confirmation screen crashes on iOS 18 beta",
        platform=Platform.IOS, severity=Severity.CRITICAL, priority=Priority.P0,
        status=DefectStatus.BLOCKED, module="payments", feature="payments:UPI collect",
        story="st1", sprint="s13", dev="vikram", qa="priya", days_ago=5,
        device="iPhone 15 Pro", os="iOS 18.0", app_version="5.11.2", build="4870",
        criticality=Criticality.CRITICAL, labels=["crash"], tags=["upi", "ios18"],
        root_cause="Crash inside the PassKit sheet on iOS 18 beta 3 — blocked on Apple feedback FB1482Z.",
    ),
    dict(
        title="Cancel-mandate CTA overlaps footer on small screens",
        platform=Platform.ANDROID, severity=Severity.LOW, priority=Priority.P3,
        status=DefectStatus.OPEN, module="payments", feature="payments:UPI collect",
        story="st2", sprint="s13", reporter="rahul", days_ago=1,
        device="Redmi Note 12", os="Android 13", app_version="5.12.0", build="5120",
        labels=["ui"],
    ),
    dict(
        title="Search in mandate list returns stale results",
        platform=Platform.WEB, severity=Severity.MEDIUM, priority=Priority.P2,
        status=DefectStatus.OPEN, module="payments", feature="payments:UPI collect",
        story="st2", sprint="s13", reporter="priya", days_ago=1,
    ),
    dict(
        title="Mandate status webhook retries stop after first failure",
        platform=Platform.API, severity=Severity.HIGH, priority=Priority.P1,
        status=DefectStatus.IN_PROGRESS, module="payments", sprint="s13",
        dev="arjun", qa="rahul", days_ago=2, eta_days=3, tags=["upi"],
        description="Webhook consumer acks before processing; a failed handler is never retried.",
    ),
    dict(
        title="Login OTP auto-read fails on Android 14",
        platform=Platform.ANDROID, severity=Severity.HIGH, priority=Priority.P1,
        status=DefectStatus.RETEST, module="platform", feature="platform:Login & OTP",
        sprint="s13", dev="sneha", qa="rahul", days_ago=6,
        device="Pixel 7a", os="Android 14", app_version="5.12.0", build="5118",
        tags=["login", "android14"], regression_required=True,
        regression_status=RegressionStatus.PENDING,
    ),
    dict(
        title="Charts freeze when switching intervals rapidly",
        platform=Platform.WEB, severity=Severity.MEDIUM, priority=Priority.P2,
        status=DefectStatus.OPEN, module="platform", feature="platform:App performance",
        sprint="s13", reporter="rahul", days_ago=1, tags=["chart"],
    ),
    dict(
        title="GTT order confirmation shows wrong trigger-price rounding",
        platform=Platform.WEB, severity=Severity.HIGH, priority=Priority.P1,
        status=DefectStatus.VERIFIED, module="orders", feature="orders:GTT orders",
        sprint="s13", dev="vikram", qa="priya", days_ago=7,
        labels=["regression"], regression_required=True,
        regression_status=RegressionStatus.PASSED,
    ),
    dict(
        title="SIP setup allows selecting a past start date",
        platform=Platform.ANDROID, severity=Severity.MEDIUM, priority=Priority.P2,
        status=DefectStatus.CLOSED, module="mf", feature="mf:SIP setup",
        sprint="s13", dev="sneha", qa="priya", days_ago=8,
        device="OnePlus 12", os="Android 14", app_version="5.11.2", build="4870",
        tags=["sip"],
    ),
    dict(
        title="Redemption accepts amount greater than current holdings",
        platform=Platform.WEB, severity=Severity.CRITICAL, priority=Priority.P0,
        status=DefectStatus.CLOSED, module="mf", feature="mf:Redemption",
        sprint="s13", dev="arjun", qa="rahul", days_ago=10,
        criticality=Criticality.CRITICAL, labels=["regression", "payment-critical"],
        regression_required=True, regression_status=RegressionStatus.PASSED,
        root_cause="Server trusted the client-side holdings snapshot; re-validation added in the redemption service.",
    ),
    dict(
        title="PAN OCR misreads the 5th character on worn cards",
        platform=Platform.ANDROID, severity=Severity.MEDIUM, priority=Priority.P2,
        status=DefectStatus.CANNOT_REPRODUCE, module="kyc", feature="kyc:PAN verification",
        sprint="s13", reporter="rahul", qa="priya", days_ago=9,
        device="Vivo V29", os="Android 13", app_version="5.11.0", build="4790",
    ),
    dict(
        title="Bank penny-drop stuck at processing for co-operative banks",
        platform=Platform.API, severity=Severity.HIGH, priority=Priority.P1,
        status=DefectStatus.DEFERRED, module="kyc", feature="kyc:Bank account linking",
        sprint="s13", dev="vikram", days_ago=11,
        root_cause="Vendor API has no async status callback for co-operative banks — revisit after their Q3 upgrade.",
    ),
    dict(
        title="Dark mode: order-book row text unreadable on hover",
        platform=Platform.WEB, severity=Severity.LOW, priority=Priority.P3,
        status=DefectStatus.OPEN, module="orders", feature="orders:Order book",
        sprint="s13", reporter="priya", days_ago=0, labels=["ui"],
    ),
    dict(
        title="UPI mandate creation times out on PIN entry",
        platform=Platform.ANDROID, severity=Severity.CRITICAL, priority=Priority.P0,
        status=DefectStatus.DUPLICATE, module="payments", feature="payments:UPI collect",
        sprint="s13", reporter="rahul", days_ago=2, tags=["upi"],
        duplicate_of_index=0,
    ),
    dict(
        title="Withdrawal OTP screen allows six rapid resends",
        platform=Platform.ANDROID, severity=Severity.HIGH, priority=Priority.P1,
        status=DefectStatus.REJECTED, module="payments", feature="payments:Withdrawals",
        sprint="s13", reporter="priya", days_ago=6,
        root_cause="Resend limits are enforced server-side by design; the client counter is cosmetic.",
    ),
    dict(
        title="App cold start exceeds 4 seconds on mid-range devices",
        platform=Platform.ANDROID, severity=Severity.MEDIUM, priority=Priority.P2,
        status=DefectStatus.CLOSED, module="platform", feature="platform:App performance",
        sprint="s12", dev="sneha", qa="rahul", days_ago=16,
        environment=Environment.PRODUCTION, device="Redmi Note 11", os="Android 12",
        app_version="5.11.0", build="4790",
    ),
    dict(
        title="Netbanking redirect loses session on bank-side timeout",
        platform=Platform.WEB, severity=Severity.HIGH, priority=Priority.P1,
        status=DefectStatus.CLOSED, module="payments", feature="payments:Netbanking",
        sprint="s12", dev="arjun", qa="priya", days_ago=18,
        environment=Environment.PRODUCTION, labels=["regression"],
        regression_required=True, regression_status=RegressionStatus.PASSED,
    ),
    dict(
        title="Autopay API returns 500 for duplicate mandate reference",
        platform=Platform.API, severity=Severity.CRITICAL, priority=Priority.P0,
        status=DefectStatus.CLOSED, module="payments", feature="payments:UPI collect",
        story="st3", sprint="s12", dev="vikram", qa="rahul", days_ago=17,
        labels=["payment-critical"], tags=["upi"],
        root_cause="Missing idempotency check on mandate reference; now returns 409 with the existing mandate.",
    ),
]


def _seed_defects(
    users: "Dict[str, User]",
    modules: "Dict[str, Module]",
    features: "Dict[str, Feature]",
    sprints: "Dict[str, Sprint]",
    stories: "Dict[str, Story]",
    labels: "Dict[str, Label]",
    tags: "Dict[str, Tag]",
) -> "List[Defect]":
    defects: "List[Defect]" = []
    for spec in _DEFECT_SPECS:
        defects.append(
            _build_defect(spec, users, modules, features, sprints, stories, labels, tags)
        )
    # Wire duplicates once every defect exists.
    for spec, defect in zip(_DEFECT_SPECS, defects):
        if "duplicate_of_index" in spec:
            defect.duplicate_of = defects[spec["duplicate_of_index"]]
    db.session.flush()
    return defects


def _build_defect(
    spec: dict,
    users: "Dict[str, User]",
    modules: "Dict[str, Module]",
    features: "Dict[str, Feature]",
    sprints: "Dict[str, Sprint]",
    stories: "Dict[str, Story]",
    labels: "Dict[str, Label]",
    tags: "Dict[str, Tag]",
) -> Defect:
    created_at = utcnow() - timedelta(days=spec.get("days_ago", 0), hours=5)
    reporter = users[spec.get("reporter", "priya")]
    developer = users[spec["dev"]] if "dev" in spec else None
    qa = users[spec["qa"]] if "qa" in spec else None
    status: DefectStatus = spec["status"]

    defect = Defect(
        defect_key=next_key("defect"),
        title=spec["title"],
        description=spec.get("description"),
        expected_result=spec.get("expected"),
        actual_result=spec.get("actual"),
        steps_to_reproduce=spec.get("steps"),
        platform=spec["platform"],
        environment=spec.get("environment", Environment.QA),
        app_version=spec.get("app_version"),
        build_number=spec.get("build"),
        os_version=spec.get("os"),
        device_name=spec.get("device"),
        severity=spec["severity"],
        priority=spec["priority"],
        criticality=spec.get("criticality"),
        status=status,
        module=modules[spec["module"]],
        feature=features[spec["feature"]] if "feature" in spec else None,
        story=stories[spec["story"]] if "story" in spec else None,
        sprint=sprints[spec["sprint"]] if "sprint" in spec else None,
        reporter=reporter,
        assigned_developer=developer,
        assigned_qa=qa,
        eta=date.today() + timedelta(days=spec["eta_days"]) if "eta_days" in spec else None,
        root_cause=spec.get("root_cause"),
        regression_required=spec.get("regression_required", False),
        regression_status=spec.get("regression_status"),
        created_at=created_at,
        updated_at=created_at,
    )
    db.session.add(defect)
    db.session.flush()

    _write_history(defect, reporter, developer, qa, created_at, status)
    return defect


def _write_history(
    defect: Defect,
    reporter: User,
    developer: "Optional[User]",
    qa: "Optional[User]",
    created_at,
    status: DefectStatus,
) -> None:
    """Backdated audit trail: created → (assigned) → status transitions."""
    def log(action: ActivityAction, when, actor: User, **kwargs) -> None:
        db.session.add(
            ActivityLog(
                entity_type="defect",
                entity_id=defect.id,
                defect=defect,
                actor=actor,
                action=action,
                created_at=when,
                **kwargs,
            )
        )

    log(ActivityAction.CREATED, created_at, reporter, new_value=DefectStatus.OPEN.value)

    if developer is not None:
        log(
            ActivityAction.ASSIGNED,
            created_at + timedelta(hours=2),
            qa or reporter,
            field="assigned_developer",
            new_value=developer.full_name,
        )

    previous = DefectStatus.OPEN
    when = created_at
    for step in _STATUS_PATHS[status]:
        when = when + timedelta(hours=_STEP_HOURS)
        # QA signs off verification/closure; the developer moves the rest.
        actor = qa if step in {DefectStatus.VERIFIED, DefectStatus.CLOSED} and qa else (
            developer or reporter
        )
        log(
            ActivityAction.STATUS_CHANGED,
            when,
            actor,
            field="status",
            old_value=previous.value,
            new_value=step.value,
        )
        previous = step

    if status.is_terminal:
        defect.resolved_at = when
        defect.resolution_type = _DEFAULT_RESOLUTIONS[status]
    if when != created_at:
        defect.updated_at = when


def _seed_comments(users: "Dict[str, User]", defects: "List[Defect]") -> int:
    """Threaded comments on a few defects (+ matching activity rows)."""
    entries = [
        # (defect, author, parent_index_within_batch, body)
        (defects[0], users["priya"], None,
         "Reproduced on Pixel 8 / Android 14 with network throttled to 3G — fails 5/5 times."),
        (defects[0], users["arjun"], 0,
         "Root cause looks like our 30s client timeout racing the NPCI PIN screen. Testing a fix with the timer paused while the PIN sheet is up."),
        (defects[3], users["vikram"], None,
         "Filed Apple feedback FB1482Z; crash is inside the PassKit sheet. Parking as Blocked until beta 4."),
        (defects[11], users["rahul"], None,
         "Verified on staging: over-redemption now returns a clear validation error. Regression suite passed."),
    ]
    created: "List[Comment]" = []
    for defect, author, parent_index, body in entries:
        comment = Comment(
            defect=defect,
            author=author,
            parent=created[parent_index] if parent_index is not None else None,
            body=body,
            created_at=defect.created_at + timedelta(hours=6 + len(created)),
            updated_at=defect.created_at + timedelta(hours=6 + len(created)),
        )
        db.session.add(comment)
        created.append(comment)
        if parent_index is None:
            db.session.add(
                ActivityLog(
                    entity_type="defect",
                    entity_id=defect.id,
                    defect=defect,
                    actor=author,
                    action=ActivityAction.COMMENTED,
                    created_at=comment.created_at,
                )
            )
    db.session.flush()
    return len(created)
