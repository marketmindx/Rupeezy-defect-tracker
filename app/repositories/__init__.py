"""Data-access layer.

One repository per aggregate root (Phase 2+: users, defects, sprints,
stories, comments, attachments, activity log). All inherit
:class:`BaseRepository` and never commit — services own transactions.
"""
from app.repositories.base import BaseRepository

__all__ = ["BaseRepository"]
