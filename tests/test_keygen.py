"""Key generation (BUG-001 style) — sequence, padding, entity isolation."""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.extensions import db
from app.models import KeyCounter
from app.services.keys import next_key


def test_sequential_and_zero_padded(app) -> None:
    assert next_key("defect") == "BUG-001"
    assert next_key("defect") == "BUG-002"


def test_entities_have_independent_counters(app) -> None:
    assert next_key("defect") == "BUG-001"
    assert next_key("story") == "STORY-001"
    assert next_key("epic") == "EPIC-001"
    assert next_key("defect") == "BUG-002"


def test_unknown_entity_rejected(app) -> None:
    with pytest.raises(ValueError, match="Unknown key entity"):
        next_key("wormhole")


def test_padding_is_a_floor_not_a_cap(app) -> None:
    next_key("defect")  # creates the counter row
    db.session.execute(sa.update(KeyCounter).values(value=999))
    assert next_key("defect") == "BUG-1000"


def test_counter_survives_commit(app) -> None:
    next_key("defect")
    db.session.commit()
    assert next_key("defect") == "BUG-002"
