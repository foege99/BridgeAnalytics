"""Tests for bridge.dd_compute — verify endplay output matches scraped DD data.

Uses a known board from the tournament JSON files as ground truth.
"""
import pytest

# Known board: tournament_1_612.json, section A, board_no 1
# (hands used for all sub-tests; contract/lead varies per test class)
_BOARD = {
    "N_hand": "7.AT86.876.KQ972",
    "\u00d8_hand": "KJ54.K.QJ942.A64",   # \u00d8 = East
    "S_hand": "A962.932.KT5.853",
    "V_hand": "QT83.QJ754.A3.JT",        # V = West
    "strain": "\u2666",                    # \u2666
    "decl": "\u00d8",                      # \u00d8 (East)
    "lead": "\u2665 5",                    # \u2665 5
    "vul": "-",
    "dealer": "N",
}

# Same deal, but with a contract where the lead (\u25034) is in the leader's hand.
# Contract: 4\u2665 by North.  Leader = East (LHO of North).
# East has KJ54.K.QJ942.A64 \u2192 clubs A,6,4 \u2192 \u25034 is valid.
# Optimal defence leads a club (4 declarer tricks); \u25034 costs 1 trick (5 vs 4).
_LEAD_BOARD = {
    **_BOARD,
    "strain": "\u2665",   # \u2665
    "decl": "N",
    "lead": "\u2663 4",   # \u25034
}

# Scraped ground-truth DD values for this board
_EXPECTED_DD = {
    "dd_N_NT": 5, "dd_N_S": 2, "dd_N_H": 4, "dd_N_D": 4,  "dd_N_C": 7,
    "dd_S_NT": 5, "dd_S_S": 3, "dd_S_H": 4, "dd_S_D": 4,  "dd_S_C": 7,
    "dd_\u00d8_NT": 7, "dd_\u00d8_S": 10, "dd_\u00d8_H": 8, "dd_\u00d8_D": 7, "dd_\u00d8_C": 6,
    "dd_V_NT": 7, "dd_V_S": 10, "dd_V_H": 8, "dd_V_D": 7,  "dd_V_C": 6,
}


class TestComputeDDTable:
    def test_matches_scraped_data(self):
        from bridge.dd_compute import compute_dd_table

        result = compute_dd_table(_BOARD)

        assert result["dd_valid"] is True
        for col, expected in _EXPECTED_DD.items():
            assert result[col] == expected, (
                f"{col}: expected {expected}, got {result[col]}"
            )

    def test_all_20_columns_present(self):
        from bridge.dd_compute import compute_dd_table

        result = compute_dd_table(_BOARD)
        for d in ["N", "\u00d8", "S", "V"]:
            for s in ["NT", "S", "H", "D", "C"]:
                assert f"dd_{d}_{s}" in result


class TestComputePar:
    def test_par_score_matches_scraped(self):
        from bridge.dd_compute import compute_par

        result = compute_par(_BOARD)
        assert result["par_score"] == -420
        assert result["par_contract"] == "4\u2660"   # 4♠
        assert result["par_side"] == "\u00d8V"        # ØV


class TestParseLeadCard:
    def test_heart_five(self):
        from bridge.dd_compute import parse_lead_card
        assert parse_lead_card("\u2665 5") == "H5"

    def test_spade_ace_no_space(self):
        from bridge.dd_compute import parse_lead_card
        assert parse_lead_card("\u2660A") == "SA"

    def test_club_ten_with_space(self):
        from bridge.dd_compute import parse_lead_card
        assert parse_lead_card("\u2663 T") == "CT"

    def test_diamond_queen(self):
        from bridge.dd_compute import parse_lead_card
        assert parse_lead_card("\u2666 Q") == "DQ"

    def test_invalid_returns_none(self):
        from bridge.dd_compute import parse_lead_card
        assert parse_lead_card("") is None
        assert parse_lead_card(None) is None
        assert parse_lead_card("Pass") is None


class TestComputeLeadTable:
    def test_best_lead_is_club(self):
        """Best defensive lead against 5♦ by East is a club (limits to 7 tricks).

        Heart/spade/diamond leads give declarer more tricks.
        """
        from bridge.dd_compute import compute_lead_table

        lead_table = compute_lead_table(_BOARD)

        assert lead_table, "lead_table should not be empty"

        # Every value must be between 0 and 13
        for card, tricks in lead_table.items():
            assert 0 <= tricks <= 13, f"{card}: {tricks} out of range"

        # Best defensive lead minimises declarer tricks (should be a club)
        best_card = min(lead_table, key=lead_table.__getitem__)
        best_tricks = lead_table[best_card]
        assert best_card.startswith("C"), (
            f"Expected club as best lead, got {best_card}"
        )
        # Should match the scraped DD value dd_Ø_D = 7
        assert best_tricks == _EXPECTED_DD["dd_\u00d8_D"]


    def test_missing_strain_returns_empty(self):
        from bridge.dd_compute import compute_lead_table

        row = {**_BOARD, "strain": None}
        assert compute_lead_table(row) == {}

    def test_missing_decl_returns_empty(self):
        from bridge.dd_compute import compute_lead_table

        row = {**_BOARD, "decl": None}
        assert compute_lead_table(row) == {}
