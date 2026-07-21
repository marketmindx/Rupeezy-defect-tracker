"""Tiny data factories — minimal valid rows with unique values where required."""
from __future__ import annotations

import itertools
from datetime import date, timedelta

from app.extensions import db
from app.models import Defect, Epic, Module, Sprint, Story, User
from app.models.enums import Platform, Priority, Severity, UserRole
from app.services.keys import next_key

_seq = itertools.count(1)


def make_user(role: UserRole = UserRole.QA, **overrides) -> User:
    n = next(_seq)
    user = User(
        username=f"user{n}",
        email=f"user{n}@example.com",
        full_name=f"User {n}",
        role=role,
    )
    user.set_password("Secret@123")
    for key, value in overrides.items():
        setattr(user, key, value)
    db.session.add(user)
    db.session.flush()
    return user


def make_module(**overrides) -> Module:
    module = Module(name=f"Module {next(_seq)}")
    for key, value in overrides.items():
        setattr(module, key, value)
    db.session.add(module)
    db.session.flush()
    return module


def make_sprint(**overrides) -> Sprint:
    n = next(_seq)
    sprint = Sprint(
        name=f"Sprint {n}",
        number=n,
        start_date=date.today() - timedelta(days=7),
        end_date=date.today() + timedelta(days=7),
    )
    for key, value in overrides.items():
        setattr(sprint, key, value)
    db.session.add(sprint)
    db.session.flush()
    return sprint


def make_epic(**overrides) -> Epic:
    epic = Epic(key=next_key("epic"), name=f"Epic {next(_seq)}")
    for key, value in overrides.items():
        setattr(epic, key, value)
    db.session.add(epic)
    db.session.flush()
    return epic


def make_story(**overrides) -> Story:
    story = Story(key=next_key("story"), title=f"Story {next(_seq)}")
    for key, value in overrides.items():
        setattr(story, key, value)
    db.session.add(story)
    db.session.flush()
    return story


def make_defect(reporter: User, module: Module, **overrides) -> Defect:
    defect = Defect(
        defect_key=next_key("defect"),
        title=f"Defect {next(_seq)}",
        platform=Platform.WEB,
        severity=Severity.MEDIUM,
        priority=Priority.P2,
        module=module,
        reporter=reporter,
    )
    for key, value in overrides.items():
        setattr(defect, key, value)
    db.session.add(defect)
    db.session.flush()
    return defect


def login(client, user: User, password: str = "Secret@123"):
    """Sign the test client in as ``user`` (factories' default password)."""
    return client.post(
        "/auth/login",
        data={"identifier": user.username, "password": password},
        follow_redirects=True,
    )
