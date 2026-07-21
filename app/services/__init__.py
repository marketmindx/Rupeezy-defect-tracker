"""Business-logic layer.

Services validate input, enforce workflow rules (raising exceptions from
:mod:`app.exceptions`), write the audit trail, and commit transactions.
Phase 3+ adds: AuthService, DefectService, SprintService, ReportService…
"""
from app.services.base import BaseService

__all__ = ["BaseService"]
