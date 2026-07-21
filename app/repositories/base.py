"""Generic repository — the only layer that talks to the database.

Contract:
    * Repositories build and run queries; they **never commit**.
    * Services own transaction boundaries (see ``BaseService.commit``).
    * Lookups that must succeed use the ``*_or_raise`` variants, which raise
      :class:`app.exceptions.NotFoundError` for the global error handlers.
"""
from __future__ import annotations

from typing import Any, Generic, Iterable, TypeVar

import sqlalchemy as sa
from flask_sqlalchemy.pagination import Pagination

from app.exceptions import NotFoundError
from app.extensions import Base, db

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Typed CRUD helpers over a single model.

    Subclass once per aggregate::

        class DefectRepository(BaseRepository[Defect]):
            model = Defect
    """

    model: type[ModelT]

    def __init__(self) -> None:
        if getattr(self, "model", None) is None:
            raise TypeError(f"{type(self).__name__} must define a `model` class attribute")

    # -- session -----------------------------------------------------------
    @property
    def session(self) -> "sa.orm.scoped_session[sa.orm.Session]":
        return db.session

    # -- reads ---------------------------------------------------------------
    def get(self, entity_id: int) -> ModelT | None:
        """Fetch by primary key, or ``None``."""
        return self.session.get(self.model, entity_id)

    def get_or_raise(self, entity_id: int) -> ModelT:
        """Fetch by primary key or raise :class:`NotFoundError`."""
        entity = self.get(entity_id)
        if entity is None:
            raise NotFoundError(f"{self.model.__name__} #{entity_id} does not exist.")
        return entity

    def first(self, *criteria: Any, order_by: Any = None) -> ModelT | None:
        """First row matching ``criteria``, or ``None``."""
        stmt = self._select(*criteria, order_by=order_by).limit(1)
        return self.session.scalars(stmt).first()

    def list(
        self,
        *criteria: Any,
        order_by: Any = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ModelT]:
        """All rows matching ``criteria`` (use sparingly — prefer paginate)."""
        stmt = self._select(*criteria, order_by=order_by)
        if offset:
            stmt = stmt.offset(offset)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def paginate(
        self,
        *criteria: Any,
        page: int = 1,
        per_page: int = 20,
        order_by: Any = None,
    ) -> Pagination:
        """Paginated rows; ``error_out=False`` clamps out-of-range pages."""
        return db.paginate(
            self._select(*criteria, order_by=order_by),
            page=page,
            per_page=per_page,
            error_out=False,
        )

    def count(self, *criteria: Any) -> int:
        stmt = sa.select(sa.func.count()).select_from(self.model)
        if criteria:
            stmt = stmt.where(*criteria)
        return self.session.scalar(stmt) or 0

    def exists(self, *criteria: Any) -> bool:
        if not criteria:
            raise ValueError("exists() requires at least one criterion")
        return bool(self.session.scalar(sa.select(sa.exists().where(*criteria))))

    # -- writes (staged only — the calling service commits) -------------------
    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def add_all(self, entities: Iterable[ModelT]) -> None:
        self.session.add_all(list(entities))

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)

    def flush(self) -> None:
        """Push pending changes so DB-generated values (ids) become available."""
        self.session.flush()

    # -- internals -------------------------------------------------------------
    def _select(self, *criteria: Any, order_by: Any = None) -> "sa.Select[tuple[ModelT]]":
        stmt = sa.select(self.model)
        if criteria:
            stmt = stmt.where(*criteria)
        if order_by is not None:
            if isinstance(order_by, (list, tuple)):
                stmt = stmt.order_by(*order_by)
            else:
                stmt = stmt.order_by(order_by)
        return stmt
