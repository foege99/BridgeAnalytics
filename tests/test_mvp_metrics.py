"""
tests/test_mvp_metrics.py

Unit tests for bridge/mvp_metrics.py – the MVP analysis framework.

Run:
    python -m pytest tests/test_mvp_metrics.py -v
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from bridge.mvp_metrics import (
    add_mvp_metrics,
    _expected_level_hcp,
    _extract_lead_suit,
    _extract_lead_card,
    _dd_tricks_for_decl,
)


# ---------------------------------------------------------------------------
# Helper to build a minimal row dict / DataFrame
# ---------------------------------------------------------------------------

def _base_row(**kwargs) -> dict:
    """Return a base row with sensible defaults; override via kwargs."""
    row = {
        # Contract
        "contract": "4♥",
        "level": 4,
        "strain": "H",
        "decl": "N",
        # Results
        "tricks": 10,
        "pct_NS": 55.0,
        "expected_pct": 50.0,
        # Hand features
        "NS_HCP": 26.0,
        "ØV_HCP": 14.0,
        "NS_LTC_adj": 5.0,
        "ØV_LTC_adj": 7.0,
        "Declarer_Side": "NS",
        # Double dummy
        "dd_valid": True,
        "dd_N_NT": 9,
        "dd_N_S": 10,
        "dd_N_H": 10,
        "dd_N_D": 8,
        "dd_N_C": 7,
        "dd_S_NT": 9,
        "dd_S_S": 10,
        "dd_S_H": 10,
        "dd_S_D": 8,
        "dd_S_C": 7,
        "dd_Ø_NT": 3,
        "dd_Ø_S": 2,
        "dd_Ø_H": 3,
        "dd_Ø_D": 5,
        "dd_Ø_C": 6,
        "dd_V_NT": 3,
        "dd_V_S": 2,
        "dd_V_H": 3,
        "dd_V_D": 5,
        "dd_V_C": 6,
        # Lead
        "lead": "♥7",
    }
    row.update(kwargs)
    return row


def _make_df(*rows: dict) -> pd.DataFrame:
    if not rows:
        rows = (_base_row(),)
    return pd.DataFrame(list(rows))


# ===========================================================================
# A1: expected_level_hcp  (unit tests on the pure helper)
# ===========================================================================

class TestExpectedLevelHcp:
    def test_20_hcp_gives_level_1(self):
        assert _expected_level_hcp(20) == 1

    def test_23_hcp_gives_level_2(self):
        # floor((23-20)/3)+1 = floor(1)+1 = 2
        assert _expected_level_hcp(23) == 2

    def test_26_hcp_gives_level_3(self):
        # floor((26-20)/3)+1 = floor(2)+1 = 3
        assert _expected_level_hcp(26) == 3

    def test_33_hcp_gives_level_5(self):
        # floor((33-20)/3)+1 = floor(4.33)+1 = 5
        assert _expected_level_hcp(33) == 5

    def test_clamped_to_7_high(self):
        assert _expected_level_hcp(40) == 7

    def test_clamped_to_1_low(self):
        assert _expected_level_hcp(5) == 1

    def test_none_returns_none(self):
        assert _expected_level_hcp(None) is None


# ===========================================================================
# A1: level_gap_hcp and contract_aggression_hcp (via add_mvp_metrics)
# ===========================================================================

class TestLevelGapAndAggression:
    def test_ok_when_gap_zero(self):
        # NS_HCP=13 + ØV_HCP=13 = combined=26 -> expected=floor((26-20)/3)+1=3; level=3 -> gap=0
        row = _base_row(NS_HCP=13.0, ØV_HCP=13.0, level=3)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "level_gap_hcp"] == pytest.approx(0)
        assert df.loc[0, "contract_aggression_hcp"] == "ok"

    def test_underbid_when_gap_negative(self):
        # combined=34 -> expected=floor(14/3)+1=floor(4.67)+1=5; level=4 -> gap=-1
        row = _base_row(NS_HCP=20.0, ØV_HCP=14.0, level=4)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "expected_level_hcp"] == 5
        assert df.loc[0, "level_gap_hcp"] == pytest.approx(-1.0)
        assert df.loc[0, "contract_aggression_hcp"] == "underbid"

    def test_overbid_label(self):
        # combined=26 -> expected=floor(6/3)+1=3; level=5 -> gap=2
        row = _base_row(NS_HCP=13.0, ØV_HCP=13.0, level=5)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "contract_aggression_hcp"] == "overbid"

    def test_nan_hcp_produces_nan_gap_and_none_aggression(self):
        row = _base_row(NS_HCP=np.nan, ØV_HCP=np.nan, level=4)
        df = add_mvp_metrics(_make_df(row))
        assert pd.isna(df.loc[0, "level_gap_hcp"])
        assert df.loc[0, "contract_aggression_hcp"] is None


# ===========================================================================
# A2: LTC computations (only for suit strains)
# ===========================================================================

class TestLtcMetrics:
    def test_ltc_combined_uses_ns_when_declarer_side_ns(self):
        row = _base_row(NS_LTC_adj=5.0, ØV_LTC_adj=7.0, Declarer_Side="NS", strain="H")
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "LTC_combined"] == pytest.approx(5.0)

    def test_ltc_combined_uses_ov_when_declarer_side_ov(self):
        row = _base_row(
            NS_LTC_adj=5.0, ØV_LTC_adj=7.0,
            Declarer_Side="ØV", decl="Ø", strain="S",
        )
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "LTC_combined"] == pytest.approx(7.0)

    def test_expected_tricks_ltc_suit(self):
        # LTC_combined=5 -> expected_tricks=24-5=19; required=6+4=10 -> gap=9
        row = _base_row(NS_LTC_adj=5.0, Declarer_Side="NS", strain="H", level=4)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "expected_tricks_ltc"] == pytest.approx(19.0)
        assert df.loc[0, "ltc_trick_gap"] == pytest.approx(9.0)
        assert df.loc[0, "ltc_soundness_flag"] == "sound"

    def test_ltc_not_computed_for_nt(self):
        row = _base_row(strain="NT", level=3)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "expected_tricks_ltc"] is None
        assert df.loc[0, "ltc_trick_gap"] is None
        assert df.loc[0, "ltc_soundness_flag"] is None

    def test_ltc_soundness_stretch(self):
        # LTC_combined=10 -> expected_tricks=14; required=6+6=12 -> gap=2 sound
        # LTC_combined=12 -> expected_tricks=12; required=6+7=13 -> gap=-1 stretch
        row = _base_row(NS_LTC_adj=12.0, Declarer_Side="NS", strain="S", level=7)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "ltc_soundness_flag"] == "stretch"

    def test_ltc_nan_produces_none_for_dependent_cols(self):
        row = _base_row(NS_LTC_adj=np.nan, ØV_LTC_adj=np.nan, strain="H")
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "expected_tricks_ltc"] is None
        assert df.loc[0, "ltc_trick_gap"] is None


# ===========================================================================
# A3: Slam flags
# ===========================================================================

class TestSlamFlags:
    def test_slam_attempted_false_for_level_5(self):
        row = _base_row(level=5)
        df = add_mvp_metrics(_make_df(row))
        assert not df.loc[0, "slam_attempted"]

    def test_slam_attempted_true_for_level_6(self):
        row = _base_row(level=6)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "slam_attempted"]

    def test_slam_hcp_ok_true_at_33(self):
        row = _base_row(NS_HCP=19.0, ØV_HCP=14.0)  # combined=33
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "slam_hcp_ok"] == True

    def test_slam_hcp_ok_false_below_33(self):
        row = _base_row(NS_HCP=15.0, ØV_HCP=17.0)  # combined=32
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "slam_hcp_ok"] == False

    def test_slam_hcp_ok_none_when_missing(self):
        row = _base_row(NS_HCP=np.nan, ØV_HCP=np.nan)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "slam_hcp_ok"] is None

    def test_slam_ltc_ok_true_at_12(self):
        row = _base_row(NS_LTC_adj=5.0, ØV_LTC_adj=7.0, Declarer_Side="NS")
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "slam_ltc_ok"] == True  # LTC_combined=5 <= 12

    def test_slam_ltc_ok_false_above_12(self):
        row = _base_row(NS_LTC_adj=7.0, ØV_LTC_adj=8.0, Declarer_Side="NS")
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "slam_ltc_ok"] == True  # LTC_combined=7 <= 12 -> True
        # Let's use a value >12
        row2 = _base_row(NS_LTC_adj=13.0, ØV_LTC_adj=5.0, Declarer_Side="NS")
        df2 = add_mvp_metrics(_make_df(row2))
        assert df2.loc[0, "slam_ltc_ok"] == False


# ===========================================================================
# B1: DD trick selection based on decl+strain
# ===========================================================================

class TestDdTrickSelection:
    def test_dd_tricks_for_north_hearts(self):
        row = _base_row(decl="N", strain="H", dd_valid=True)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "dd_tricks_declarer"] == 10  # dd_N_H

    def test_dd_tricks_for_south_spades(self):
        row = _base_row(decl="S", strain="S", dd_valid=True)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "dd_tricks_declarer"] == 10  # dd_S_S

    def test_dd_tricks_for_east_nt(self):
        row = _base_row(decl="Ø", strain="NT", dd_valid=True)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "dd_tricks_declarer"] == 3  # dd_Ø_NT

    def test_dd_tricks_none_when_dd_not_valid(self):
        row = _base_row(dd_valid=False)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "dd_tricks_declarer"] is None

    def test_dd_tricks_none_when_dd_valid_missing(self):
        row = _base_row()
        del row["dd_valid"]
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "dd_tricks_declarer"] is None

    def test_dd_tricks_none_for_unknown_decl(self):
        row = _base_row(decl="X", dd_valid=True)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "dd_tricks_declarer"] is None


# ===========================================================================
# B1+B2: play_precision_dd and contract_hardness_dd
# ===========================================================================

class TestPlayPrecision:
    def test_play_precision_positive_overtrick(self):
        # dd_N_H=10, tricks=11 -> precision=+1
        row = _base_row(decl="N", strain="H", tricks=11)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "play_precision_dd"] == 1

    def test_play_precision_zero(self):
        row = _base_row(decl="N", strain="H", tricks=10)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "play_precision_dd"] == 0

    def test_play_precision_negative_undertrick(self):
        row = _base_row(decl="N", strain="H", tricks=8)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "play_precision_dd"] == -2

    def test_play_precision_none_when_dd_invalid(self):
        row = _base_row(dd_valid=False)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "play_precision_dd"] is None

    def test_contract_hardness_dd(self):
        # dd_N_H=10, contract_required=6+4=10 -> hardness=0
        row = _base_row(decl="N", strain="H", level=4)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "contract_hardness_dd"] == 0

    def test_contract_hardness_dd_negative_beyond_dd(self):
        # dd_N_H=10, level=7 -> required=13 -> hardness=10-13=-3
        row = _base_row(decl="N", strain="H", level=7)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "contract_hardness_dd"] == -3

    def test_hardness_none_when_dd_invalid(self):
        row = _base_row(dd_valid=False)
        df = add_mvp_metrics(_make_df(row))
        assert df.loc[0, "contract_hardness_dd"] is None


# ===========================================================================
# C: lead_suit extraction
# ===========================================================================

class TestLeadSuitExtraction:
    @pytest.mark.parametrize("lead,expected_suit", [
        ("♠A", "S"),
        ("♥7", "H"),
        ("♦2", "D"),
        ("♣K", "C"),
        ("♠", "S"),       # suit symbol without rank
    ])
    def test_suit_symbols(self, lead, expected_suit):
        assert _extract_lead_suit(lead) == expected_suit

    @pytest.mark.parametrize("lead,expected_suit", [
        ("SA", "S"),
        ("h7", "H"),   # lower-case
        ("DK", "D"),
        ("CQ", "C"),
    ])
    def test_ascii_letters(self, lead, expected_suit):
        assert _extract_lead_suit(lead) == expected_suit

    @pytest.mark.parametrize("lead", [None, "", "   ", np.nan])
    def test_missing_lead_gives_ukendt(self, lead):
        assert _extract_lead_suit(lead) == "ukendt"

    def test_unknown_format_gives_ukendt(self):
        assert _extract_lead_suit("7x") == "ukendt"

    def test_via_dataframe(self):
        rows = [
            _base_row(lead="♥7"),
            _base_row(lead=None),
            _base_row(lead="♠A"),
        ]
        df = add_mvp_metrics(_make_df(*rows))
        assert list(df["lead_suit"]) == ["H", "ukendt", "S"]

    def test_lead_card_extraction(self):
        assert _extract_lead_card("♥7") == "7"
        assert _extract_lead_card("♠AK") == "AK"
        assert _extract_lead_card(None) is None


# ===========================================================================
# Edge cases / robustness
# ===========================================================================

class TestRobustness:
    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["contract", "level", "strain", "decl", "tricks"])
        result = add_mvp_metrics(df)
        assert result.empty

    def test_missing_hand_columns_gives_nan(self):
        """If NS_HCP etc are absent the metrics should be NaN/None, not raise."""
        df = pd.DataFrame([{"level": 4, "strain": "H", "decl": "N", "tricks": 10}])
        result = add_mvp_metrics(df)
        assert pd.isna(result.loc[0, "Combined_HCP"])
        assert pd.isna(result.loc[0, "level_gap_hcp"])

    def test_multiple_rows_all_sections(self):
        """Verify computation works across multiple rows (A/B/C)."""
        rows = [
            _base_row(level=4, NS_HCP=26.0, ØV_HCP=14.0),
            _base_row(level=6, NS_HCP=33.0, ØV_HCP=7.0),
            _base_row(level=3, NS_HCP=22.0, ØV_HCP=18.0),
        ]
        df = add_mvp_metrics(_make_df(*rows))
        assert len(df) == 3
        # Spot-check no NaN in Combined_HCP
        assert df["Combined_HCP"].notna().all()

    def test_pct_vs_expected_added_when_missing(self):
        """add_mvp_metrics should compute pct_vs_expected if absent."""
        row = _base_row(pct_NS=60.0, expected_pct=50.0)
        df_in = _make_df(row)
        # Ensure column is absent
        if "pct_vs_expected" in df_in.columns:
            df_in = df_in.drop(columns=["pct_vs_expected"])
        result = add_mvp_metrics(df_in)
        assert "pct_vs_expected" in result.columns
        assert result.loc[0, "pct_vs_expected"] == pytest.approx(10.0)

    def test_no_duplicate_columns(self):
        df = add_mvp_metrics(_make_df())
        assert df.columns.duplicated().sum() == 0
