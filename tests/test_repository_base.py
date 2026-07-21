"""Exercises BaseRepository against a throwaway model.

Real models arrive in Phase 2; this keeps the generic data-access layer
honest in the meantime (and pins its contract for those models).
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.exceptions import NotFoundError
from app.extensions import db
from app.repositories import BaseRepository


class _Widget(db.Model):
    __tablename__ = "_test_widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(50))


class _WidgetRepository(BaseRepository[_Widget]):
    model = _Widget


@pytest.fixture()
def repo(app) -> _WidgetRepository:
    return _WidgetRepository()


def _seed(repo: _WidgetRepository, *names: str) -> list[_Widget]:
    widgets = [repo.add(_Widget(name=name)) for name in names]
    repo.flush()
    return widgets


def test_add_and_get_roundtrip(repo: _WidgetRepository) -> None:
    widget = _seed(repo, "alpha")[0]
    assert widget.id is not None
    fetched = repo.get(widget.id)
    assert fetched is not None
    assert fetched.name == "alpha"


def test_get_or_raise_raises_domain_error(repo: _WidgetRepository) -> None:
    with pytest.raises(NotFoundError, match="_Widget #999"):
        repo.get_or_raise(999)


def test_list_count_exists_with_criteria(repo: _WidgetRepository) -> None:
    _seed(repo, "alpha", "beta", "beta")

    assert repo.count() == 3
    assert repo.count(_Widget.name == "beta") == 2
    assert [w.name for w in repo.list(_Widget.name == "beta")] == ["beta", "beta"]
    assert repo.exists(_Widget.name == "alpha") is True
    assert repo.exists(_Widget.name == "gamma") is False


def test_exists_requires_criteria(repo: _WidgetRepository) -> None:
    with pytest.raises(ValueError):
        repo.exists()


def test_first_with_ordering(repo: _WidgetRepository) -> None:
    _seed(repo, "charlie", "alpha", "beta")
    first = repo.first(order_by=_Widget.name)
    assert first is not None
    assert first.name == "alpha"


def test_paginate_clamps_and_counts(repo: _WidgetRepository) -> None:
    _seed(repo, *[f"w{i:02d}" for i in range(25)])

    page = repo.paginate(page=2, per_page=10, order_by=_Widget.id)
    assert page.total == 25
    assert page.pages == 3
    assert [w.name for w in page.items] == [f"w{i:02d}" for i in range(10, 20)]


def test_delete_stages_removal(repo: _WidgetRepository) -> None:
    widget = _seed(repo, "alpha")[0]
    repo.delete(widget)
    repo.flush()
    assert repo.get(widget.id) is None
    assert repo.count() == 0


def test_repository_without_model_is_rejected() -> None:
    class _Broken(BaseRepository):  # type: ignore[type-arg]
        pass

    with pytest.raises(TypeError, match="must define a `model`"):
        _Broken()
