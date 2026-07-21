"""Phase 5 collaboration tests: threaded comments and attachments."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.extensions import db
from app.models import ActivityAction, ActivityLog, Attachment, AttachmentKind, Comment
from app.models.enums import UserRole
from tests.factories import login, make_defect, make_module, make_user


@pytest.fixture()
def world(app, client) -> dict:
    qa = make_user(username="collab.qa")
    module = make_module()
    defect = make_defect(qa, module)
    db.session.commit()
    login(client, qa)
    return {"qa": qa, "module": module, "defect": defect}


def _upload(client, defect_id: int, filename: str, payload: bytes = b"data"):
    return client.post(
        f"/defects/{defect_id}/attachments",
        data={"files": (BytesIO(payload), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


class TestComments:
    def test_add_comment_with_activity(self, client, world) -> None:
        response = client.post(
            f"/defects/{world['defect'].id}/comments",
            data={"body": "Reproduced on staging."},
            follow_redirects=True,
        )
        assert b"Comment added." in response.data
        assert b"Reproduced on staging." in response.data
        actions = db.session.scalars(
            sa.select(ActivityLog.action).where(ActivityLog.defect_id == world["defect"].id)
        ).all()
        assert ActivityAction.COMMENTED in actions

    def test_threaded_reply(self, client, world) -> None:
        client.post(
            f"/defects/{world['defect'].id}/comments", data={"body": "parent"}
        )
        parent = db.session.scalar(sa.select(Comment))
        client.post(
            f"/defects/{world['defect'].id}/comments",
            data={"body": "the reply", "parent_id": str(parent.id)},
        )
        reply = db.session.scalar(sa.select(Comment).where(Comment.parent_id == parent.id))
        assert reply is not None
        assert reply.body == "the reply"

        page = client.get(f"/defects/{world['defect'].defect_key}").data
        assert b"the reply" in page

    def test_delete_permissions(self, client, world) -> None:
        other = make_user(username="other.qa")
        comment = Comment(defect=world["defect"], author=other, body="not yours")
        db.session.add(comment)
        db.session.commit()

        response = client.post(
            f"/defects/comments/{comment.id}/delete", follow_redirects=True
        )
        assert b"only delete your own comments" in response.data
        assert db.session.get(Comment, comment.id) is not None

        client.post("/auth/logout")
        login(client, make_user(role=UserRole.ADMIN))
        client.post(f"/defects/comments/{comment.id}/delete")
        assert db.session.get(Comment, comment.id) is None


class TestAttachments:
    def test_upload_detects_kind_and_stores_file(self, client, world, app) -> None:
        response = _upload(client, world["defect"].id, "shot.png", b"fake-png-bytes")
        assert b"1 file attached." in response.data

        attachment = db.session.scalar(sa.select(Attachment))
        assert attachment.kind is AttachmentKind.SCREENSHOT
        assert attachment.original_filename == "shot.png"
        stored = Path(app.config["UPLOAD_FOLDER"]) / attachment.stored_filename
        assert stored.read_bytes() == b"fake-png-bytes"

        actions = db.session.scalars(sa.select(ActivityLog.action)).all()
        assert ActivityAction.ATTACHMENT_ADDED in actions

    def test_blocked_extension(self, client, world, app) -> None:
        response = _upload(client, world["defect"].id, "malware.exe")
        assert b"File type not allowed" in response.data
        assert db.session.scalar(sa.select(sa.func.count()).select_from(Attachment)) == 0
        upload_dir = Path(app.config["UPLOAD_FOLDER"])
        assert not upload_dir.exists() or not any(upload_dir.iterdir())

    def test_download_and_inline(self, client, world) -> None:
        _upload(client, world["defect"].id, "trace.log", b"log-content")
        attachment = db.session.scalar(sa.select(Attachment))
        assert attachment.kind is AttachmentKind.LOG

        response = client.get(f"/defects/attachments/{attachment.id}/download")
        assert response.status_code == 200
        assert response.data == b"log-content"
        assert "attachment" in response.headers["Content-Disposition"]
        assert "trace.log" in response.headers["Content-Disposition"]

        inline = client.get(f"/defects/attachments/{attachment.id}/download?inline=1")
        assert "inline" in inline.headers["Content-Disposition"]

    def test_download_requires_login(self, client, world, app) -> None:
        _upload(client, world["defect"].id, "shot.png")
        attachment = db.session.scalar(sa.select(Attachment))
        client.post("/auth/logout")
        response = client.get(f"/defects/attachments/{attachment.id}/download")
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_delete_removes_row_and_file(self, client, world, app) -> None:
        _upload(client, world["defect"].id, "shot.png")
        attachment = db.session.scalar(sa.select(Attachment))
        stored = Path(app.config["UPLOAD_FOLDER"]) / attachment.stored_filename
        assert stored.exists()

        response = client.post(
            f"/defects/attachments/{attachment.id}/delete", follow_redirects=True
        )
        assert b"Attachment deleted." in response.data
        assert db.session.scalar(sa.select(sa.func.count()).select_from(Attachment)) == 0
        assert not stored.exists()
        actions = db.session.scalars(sa.select(ActivityLog.action)).all()
        assert ActivityAction.ATTACHMENT_REMOVED in actions
