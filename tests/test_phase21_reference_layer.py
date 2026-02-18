
"""Phase 2.1 – Reference-lag testprotokol (pandas asserts)

Updated: 2026-02-16

Run:
    python -m pytest -q

Place this file at:
    BridgeAnalytics/tests/test_phase21_reference_layer.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bridge.analysis import add_phase21_fields


def make_rows(
    *,
    tournament_date: str,
    board_no: int,
    section: str,
    contracts: list[str],
    pcts: list[float],
    status: str = "PLAYED",
    role: str = "Declarer",
) -> pd.DataFrame:
    assert len(contracts) == len(pcts)
    return pd.DataFrame(
        {
            "tournament_date": [tournament_date] * len(contracts),
            "board_no": [board_no] * len(contracts),
            "section": [section] * len(contracts),
            "result_status_code": [status] * len(contracts),
            "pct": pcts,
            "contract": contracts,
            "role": [role] * len(contracts),
        }
    )


def assert_close(a, b, tol=1e-9):
    assert (pd.isna(a) and pd.isna(b)) or abs(float(a) - float(b)) <= tol


@pytest.fixture
def df_case_section_ge_12() -> pd.DataFrame:
    return pd.concat(
        [
            make_rows(
                tournament_date="2026-01-27",
                board_no=1,
                section="A",
                contracts=["4♥"] * 9 + ["3NT"] * 3,
                pcts=[60, 58, 62, 55, 57, 59, 61, 63, 56, 48, 50, 52],
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=1,
                section="B",
                contracts=["4♥"] * 6 + ["3NT"] * 6,
                pcts=[40, 42, 38, 44, 41, 39, 55, 56, 54, 52, 53, 51],
            ),
        ],
        ignore_index=True,
    )


@pytest.fixture
def df_case_club_fallback_split() -> pd.DataFrame:
    return pd.concat(
        [
            make_rows(
                tournament_date="2026-01-27",
                board_no=2,
                section="A",
                contracts=["3NT"] * 4 + ["4♥"] * 2,
                pcts=[55, 57, 53, 56, 49, 50],
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=2,
                section="B",
                contracts=["3NT"] * 4 + ["4♥"] * 2,
                pcts=[60, 58, 61, 59, 52, 51],
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=2,
                section="C",
                contracts=["3NT"] * 4 + ["4♥"] * 2,
                pcts=[45, 44, 46, 43, 48, 47],
            ),
        ],
        ignore_index=True,
    )


@pytest.fixture
def df_case_low_sample() -> pd.DataFrame:
    return pd.concat(
        [
            make_rows(
                tournament_date="2026-01-27",
                board_no=3,
                section="A",
                contracts=["4♠"] * 5,
                pcts=[55, 56, 54, 57, 53],
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=3,
                section="B",
                contracts=["3NT"] * 3,
                pcts=[45, 44, 46],
            ),
        ],
        ignore_index=True,
    )


@pytest.fixture
def df_case_mode_lt_3_expected_pct_fallback() -> pd.DataFrame:
    contracts = ["4♥", "4♥"] + ["3NT", "4♠", "5♦", "2♠", "2♥", "3♣", "3♦", "5♣", "6♥", "1NT"]
    pcts = [60, 50, 55, 45, 52, 48, 47, 49, 51, 53, 54, 46]
    return pd.concat(
        [
            make_rows(
                tournament_date="2026-01-27",
                board_no=4,
                section="A",
                contracts=contracts[:6],
                pcts=pcts[:6],
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=4,
                section="B",
                contracts=contracts[6:],
                pcts=pcts[6:],
            ),
        ],
        ignore_index=True,
    )


def test_section_reference_selected_when_ge_12(df_case_section_ge_12):
    df_out = add_phase21_fields(df_case_section_ge_12.copy())
    a_row = df_out[(df_out["section"] == "A") & (df_out["board_no"] == 1)].iloc[0]
    assert a_row["reference_scope"] == "SECTION"
    assert int(a_row["N_section_played"]) == 12
    assert int(a_row["reference_n_played"]) == 12
    assert a_row["field_mode_contract"] == "4♥"
    assert_close(a_row["field_mode_freq"], 9 / 12)
    assert a_row["Board_Type"] == "Dominant"
    assert bool(a_row["competitive_flag"]) is False


def test_club_fallback_when_section_small_split(df_case_club_fallback_split):
    df_out = add_phase21_fields(df_case_club_fallback_split.copy())
    a_row = df_out[(df_out["section"] == "A") & (df_out["board_no"] == 2)].iloc[0]
    assert int(a_row["N_section_played"]) == 6
    assert int(a_row["N_club_played"]) == 18
    assert a_row["reference_scope"] == "CLUB"
    assert int(a_row["reference_n_played"]) == 18
    assert a_row["field_mode_contract"] == "3NT"
    assert_close(a_row["field_mode_freq"], 12 / 18)
    assert a_row["Board_Type"] == "Split"
    assert bool(a_row["competitive_flag"]) is True


def test_low_sample_when_both_below_12(df_case_low_sample):
    df_out = add_phase21_fields(df_case_low_sample.copy())
    a_row = df_out[(df_out["section"] == "A") & (df_out["board_no"] == 3)].iloc[0]
    assert int(a_row["N_section_played"]) == 5
    assert int(a_row["N_club_played"]) == 8
    assert a_row["reference_scope"] == "LOW_SAMPLE"
    assert a_row["Board_Type"] == "LOW_SAMPLE"
    assert bool(a_row["competitive_flag"]) is False


def test_expected_pct_fallback_when_mode_occurs_lt_3(df_case_mode_lt_3_expected_pct_fallback):
    df_out = add_phase21_fields(df_case_mode_lt_3_expected_pct_fallback.copy())
    row = df_out[df_out["board_no"] == 4].iloc[0]
    board_mean = df_out[df_out["board_no"] == 4]["pct"].mean()
    assert_close(row["expected_pct"], board_mean)


def test_excludes_sitout_not_played_and_nan_pct_from_reference():
    df = pd.concat(
        [
            make_rows(
                tournament_date="2026-01-27",
                board_no=5,
                section="A",
                contracts=["4♥"] * 10,
                pcts=[50, 51, 49, 52, 48, 53, 47, 54, 46, 55],
                status="PLAYED",
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=5,
                section="A",
                contracts=["4♥"],
                pcts=[np.nan],
                status="PLAYED",
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=5,
                section="A",
                contracts=["4♥"],
                pcts=[50],
                status="SITOUT",
            ),
            make_rows(
                tournament_date="2026-01-27",
                board_no=5,
                section="A",
                contracts=["4♥"],
                pcts=[50],
                status="NOT_PLAYED_AVERAGE",
            ),
        ],
        ignore_index=True,
    )
    df_out = add_phase21_fields(df)
    row = df_out.iloc[0]
    assert int(row["N_section_played"]) == 10


def test_contract_normalization_strips_doubles_and_keeps_double_state():
    df = make_rows(
        tournament_date="2026-01-27",
        board_no=6,
        section="A",
        contracts=["4♥X", "4♥XX", "4♥", "4♥X", "4♥"],
        pcts=[50, 55, 60, 45, 52],
    )
    df_out = add_phase21_fields(df)
    assert set(df_out["contract_norm"].unique()) == {"4♥"}
    assert set(df_out["double_state"].unique()) == {"", "X", "XX"}


@pytest.mark.integration
def test_real_data_slice_template():
    pytest.skip("Provide a real data slice fixture and assertions for invariants.")
