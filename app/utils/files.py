"""Attachment file handling: extension policy, kind detection, storage.

Files are stored under random names inside UPLOAD_FOLDER; the client-supplied
filename is display-only (``Attachment.original_filename``) and never touches
the filesystem, so no sanitisation gymnastics are needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.models.enums import AttachmentKind

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_VIDEO_EXTS = {"mp4", "mov", "webm", "mkv"}
_LOG_EXTS = {"txt", "log", "json", "har", "csv", "zip"}


def file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def allowed_file(filename: str) -> bool:
    return file_extension(filename) in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]


def detect_kind(filename: str) -> AttachmentKind:
    ext = file_extension(filename)
    if ext in _IMAGE_EXTS:
        return AttachmentKind.SCREENSHOT
    if ext in _VIDEO_EXTS:
        return AttachmentKind.VIDEO
    if ext in _LOG_EXTS:
        return AttachmentKind.LOG
    return AttachmentKind.OTHER


def save_upload(upload: FileStorage) -> "Tuple[str, int]":
    """Persist an upload; returns (stored_filename, size_bytes)."""
    folder = Path(current_app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    ext = file_extension(upload.filename or "")
    stored_name = f"{uuid4().hex}.{ext}" if ext else uuid4().hex
    path = folder / stored_name
    upload.save(path)
    return stored_name, path.stat().st_size


def delete_stored(stored_filename: str) -> None:
    (Path(current_app.config["UPLOAD_FOLDER"]) / stored_filename).unlink(missing_ok=True)
