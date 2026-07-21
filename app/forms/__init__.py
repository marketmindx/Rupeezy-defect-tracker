"""WTForms form classes, one module per feature area.

Forms own *shape* validation (required, length, format); services re-check
*business* rules (uniqueness, invariants) so the future automation API gets
the same guarantees without going through a form.
"""
from app.forms.agile import EpicForm, SprintForm, StoryForm
from app.forms.auth import LoginForm
from app.forms.defects import AttachmentUploadForm, CommentForm, DefectForm
from app.forms.users import PasswordResetForm, UserCreateForm, UserEditForm

__all__ = [
    "AttachmentUploadForm",
    "CommentForm",
    "DefectForm",
    "EpicForm",
    "LoginForm",
    "PasswordResetForm",
    "SprintForm",
    "StoryForm",
    "UserCreateForm",
    "UserEditForm",
]
