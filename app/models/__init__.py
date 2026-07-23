"""SQLAlchemy ORM models.

Everything is imported (and re-exported) here so that:
* Alembic autogenerate sees the complete metadata,
* the Flask-Login ``user_loader`` in :mod:`app.models.user` registers,
* callers can simply ``from app.models import Defect, DefectStatus``.
"""
from app.models.activity import ActivityLog
from app.models.agile import Epic, Sprint, Story, story_labels
from app.models.collaboration import Attachment, Comment
from app.models.counters import KeyCounter
from app.models.defect import Defect, defect_labels, defect_tags
from app.models.enums import (
    ActivityAction,
    AttachmentKind,
    Criticality,
    DefectStatus,
    Environment,
    Platform,
    Priority,
    RegressionStatus,
    ResolutionType,
    Severity,
    SprintStatus,
    StoryStatus,
    UserRole,
)
from app.models.taxonomy import Feature, Label, Module, Tag
from app.models.user import User

__all__ = [
    "ActivityAction",
    "ActivityLog",
    "Attachment",
    "AttachmentKind",
    "Comment",
    "Criticality",
    "Defect",
    "DefectStatus",
    "Environment",
    "Epic",
    "Feature",
    "KeyCounter",
    "Label",
    "Module",
    "Platform",
    "Priority",
    "RegressionStatus",
    "ResolutionType",
    "Severity",
    "Sprint",
    "SprintStatus",
    "Story",
    "StoryStatus",
    "Tag",
    "User",
    "UserRole",
    "defect_labels",
    "defect_tags",
    "story_labels",
]
