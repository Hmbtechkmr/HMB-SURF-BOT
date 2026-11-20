import asyncio

import pytest

from bot.database import Database, normalize_question
from bot.i18n import STRINGS
from bot.text import chunk, esc


def test_escape():
    assert esc("a<b>&c") == "a&lt;b&gt;&amp;c"


def test_chunk_limits():
    parts = chunk("x" * 9000)
    assert all(len(p) <= 4000 for p in parts)
    assert "".join(parts) == "x" * 9000


def test_normalize():
    assert normalize_question("  Combien ÇA coûte ?! ") == "combien ca coute"


def test_langs_parity():
    assert set(STRINGS["fr"]) == set(STRINGS["en"])


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "t.sqlite3"))


def test_order_code_unique(db):
    ids = set()
    for _ in range(30):
        _order_id, code = db.create_order((1, "u", "N", "op", "c1", "l", 100))
        ids.add(code)
    assert len(ids) == 30


def test_stock_reservation(db):
    db.add_stock("c1", ["A", "B"])
    first = db.reserve_stock("c1", 1)
    second = db.reserve_stock("c1", 2)
    assert {first, second} == {"A", "B"}
    assert db.reserve_stock("c1", 3) is None


def test_dedup(db):
    assert db.mark_update(10) is True
    assert db.mark_update(10) is False


def test_faq(db):
    db.faq_add("Combien ça coûte ?", "Voir catalogue")
    assert db.faq_lookup("combien ca coute") == "Voir catalogue"
