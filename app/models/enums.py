"""Domain vocabulary — every enum member stores its human-readable ``value``.

Columns use plain VARCHAR (``native_enum=False``) so adding a vocabulary
entry is a code change rather than a schema migration, and the data reads
naturally in raw SQL on both SQLite and PostgreSQL. Validity is enforced at
the ORM boundary (``validate_strings=True``).
"""
from __future__ import annotations

import enum

import sqlalchemy as sa


def enum_column(enum_cls: "type[enum.Enum]") -> sa.Enum:
    """Build the standard portable enum column type for ``enum_cls``."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


class UserRole(enum.Enum):
    ADMIN = "Admin"
    QA = "QA"
    DEVELOPER = "Developer"


class Platform(enum.Enum):
    ANDROID = "Android"
    IOS = "iOS"
    WEB = "Web"
    API = "API"


class Environment(enum.Enum):
    DEVELOPMENT = "Development"
    QA = "QA"
    STAGING = "Staging"
    UAT = "UAT"
    PRODUCTION = "Production"


class Severity(enum.Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Priority(enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Criticality(enum.Enum):
    """Business impact — tracked separately from technical severity."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class DefectStatus(enum.Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    READY_FOR_QA = "Ready for QA"
    RETEST = "Retest"
    VERIFIED = "Verified"
    CLOSED = "Closed"
    REJECTED = "Rejected"
    DUPLICATE = "Duplicate"
    DEFERRED = "Deferred"
    BLOCKED = "Blocked"
    CANNOT_REPRODUCE = "Cannot Reproduce"

    @property
    def is_terminal(self) -> bool:
        """True once a defect needs no further action.

        Deferred and Blocked count as *open* — both re-enter the workflow.
        """
        return self in {
            DefectStatus.VERIFIED,
            DefectStatus.CLOSED,
            DefectStatus.REJECTED,
            DefectStatus.DUPLICATE,
            DefectStatus.CANNOT_REPRODUCE,
        }

    @classmethod
    def open_statuses(cls) -> "list[DefectStatus]":
        return [status for status in cls if not status.is_terminal]


class ResolutionType(enum.Enum):
    FIXED = "Fixed"
    WONT_FIX = "Won't Fix"
    DUPLICATE = "Duplicate"
    NOT_A_BUG = "Not a Bug"
    CANNOT_REPRODUCE = "Cannot Reproduce"
    DEFERRED = "Deferred"


class RegressionStatus(enum.Enum):
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    PASSED = "Passed"
    FAILED = "Failed"


class SprintStatus(enum.Enum):
    PLANNED = "Planned"
    ACTIVE = "Active"
    COMPLETED = "Completed"


class StoryStatus(enum.Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    DONE = "Done"


class AttachmentKind(enum.Enum):
    SCREENSHOT = "Screenshot"
    VIDEO = "Video"
    LOG = "Log"
    OTHER = "Other"


class ActivityAction(enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    COMMENTED = "commented"
    ATTACHMENT_ADDED = "attachment_added"
    ATTACHMENT_REMOVED = "attachment_removed"
    DELETED = "deleted"
