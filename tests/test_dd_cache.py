"""Tests for bridge.dd_cache — SQLite CRUD operations.

Uses a temporary database path to avoid touching the real cache.
"""
import pathlib
import pytest


_BOARD = {
    "N_hand": "7.AT86.876.KQ972",
    "\u00d8_hand": "KJ54.K.QJ942.A64",
    "S_hand": "A962.932.KT5.853",
    "V_hand": "QT83.QJ754.A3.JT",
}

_DD_TABLE = {
    f"dd_{d}_{s}": 5
    for d in ["N", "\u00d8", "S", "V"]
    for s in ["NT", "S", "H", "D", "C"]
}


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Redirect cache DB to a temp file for test isolation."""
    import bridge.dd_cache as cache_module

    fake_db = tmp_path / "test_cache.db"
    monkeypatch.setattr(cache_module, "_DB_PATH", fake_db)
    yield


class TestDealHash:
    def test_returns_string(self):
        from bridge.dd_cache import get_deal_hash

        h = get_deal_hash(_BOARD)
        assert isinstance(h, str) and len(h) == 64

    def test_same_board_same_hash(self):
        from bridge.dd_cache import get_deal_hash

        assert get_deal_hash(_BOARD) == get_deal_hash(_BOARD)

    def test_different_boards_different_hash(self):
        from bridge.dd_cache import get_deal_hash

        board2 = {**_BOARD, "N_hand": "AKQ.AKQ.AKQ.AKQ2"}
        assert get_deal_hash(_BOARD) != get_deal_hash(board2)

    def test_missing_hand_returns_none(self):
        from bridge.dd_cache import get_deal_hash

        assert get_deal_hash({"N_hand": "7.AT86.876.KQ972"}) is None


class TestDDTableCRUD:
    def test_miss_returns_none(self):
        from bridge.dd_cache import get_dd_table

        assert get_dd_table("nonexistent_hash") is None

    def test_save_and_retrieve(self):
        from bridge.dd_cache import get_deal_hash, get_dd_table, save_dd_table

        h = get_deal_hash(_BOARD)
        save_dd_table(h, _DD_TABLE)
        result = get_dd_table(h)
        assert result is not None
        for col, val in _DD_TABLE.items():
            assert result[col] == val

    def test_overwrite_with_replace(self):
        from bridge.dd_cache import get_deal_hash, get_dd_table, save_dd_table

        h = get_deal_hash(_BOARD)
        save_dd_table(h, _DD_TABLE)
        updated = {**_DD_TABLE, "dd_N_NT": 9}
        save_dd_table(h, updated)
        result = get_dd_table(h)
        assert result["dd_N_NT"] == 9


class TestParCRUD:
    _PAR_DATA = {"par_score": -420, "par_contract": "4\u2660", "par_side": "\u00d8V"}

    def test_miss_returns_none(self):
        from bridge.dd_cache import get_par

        assert get_par("nohash", "-") is None

    def test_save_and_retrieve(self):
        from bridge.dd_cache import get_deal_hash, get_par, save_par

        h = get_deal_hash(_BOARD)
        save_par(h, "-", self._PAR_DATA)
        result = get_par(h, "-")
        assert result["par_score"] == -420
        assert result["par_contract"] == "4\u2660"

    def test_different_vul_separate_entries(self):
        from bridge.dd_cache import get_deal_hash, get_par, save_par

        h = get_deal_hash(_BOARD)
        save_par(h, "-", self._PAR_DATA)
        save_par(h, "NS", {"par_score": 620, "par_contract": "4\u2665", "par_side": "NS"})
        assert get_par(h, "-")["par_score"] == -420
        assert get_par(h, "NS")["par_score"] == 620


class TestLeadTableCRUD:
    _LEAD_DATA = {"H5": 9, "C3": 7, "CA": 7, "SA": 8}

    def test_miss_returns_none(self):
        from bridge.dd_cache import get_lead_table

        assert get_lead_table("nohash", "D", "\u00d8") is None

    def test_save_and_retrieve(self):
        from bridge.dd_cache import get_deal_hash, get_lead_table, save_lead_table

        h = get_deal_hash(_BOARD)
        save_lead_table(h, "D", "\u00d8", self._LEAD_DATA)
        result = get_lead_table(h, "D", "\u00d8")
        assert result is not None
        assert result["H5"] == 9
        assert result["C3"] == 7

    def test_different_strain_different_entry(self):
        from bridge.dd_cache import get_deal_hash, get_lead_table, save_lead_table

        h = get_deal_hash(_BOARD)
        save_lead_table(h, "D", "\u00d8", self._LEAD_DATA)
        # NT by same declarer should be empty
        assert get_lead_table(h, "NT", "\u00d8") is None
