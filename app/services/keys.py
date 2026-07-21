"""Human-readable entity keys: BUG-001, STORY-125, EPIC-007.

Keys come from :class:`app.models.counters.KeyCounter`, not from primary
keys, so they never reuse numbers after deletion and stay stable if the
data is ever migrated.
"""
from __future__ import annotations

import sqlalchemy as sa

from app.extensions import db
from app.models.counters import KeyCounter

#: entity → (prefix, zero-pad width). Width is a floor, not a cap:
#: BUG-999 is followed by BUG-1000.
_REGISTRY: "dict[str, tuple[str, int]]" = {
    "defect": ("BUG", 3),
    "story": ("STORY", 3),
    "epic": ("EPIC", 3),
}


def next_key(entity: str) -> str:
    """Reserve and return the next key for ``entity``.

    Runs inside the caller's transaction. The counter row is locked with
    ``SELECT … FOR UPDATE`` where supported (PostgreSQL); SQLite serialises
    writers anyway. Only the very first concurrent use of a brand-new entity
    can race on the initial insert — the loser hits the primary key and the
    caller's normal rollback/retry handles it.
    """
    try:
        prefix, width = _REGISTRY[entity]
    except KeyError:
        raise ValueError(
            f"Unknown key entity {entity!r} — expected one of {sorted(_REGISTRY)}"
        ) from None

    counter = db.session.execute(
        sa.select(KeyCounter).where(KeyCounter.entity == entity).with_for_update()
    ).scalar_one_or_none()
    if counter is None:
        counter = KeyCounter(entity=entity, value=0)
        db.session.add(counter)
        db.session.flush()

    counter.value += 1
    db.session.flush()
    return f"{prefix}-{counter.value:0{width}d}"
