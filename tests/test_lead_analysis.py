"""Tests for bridge.lead_analysis and integration with bridge.features."""

from __future__ import annotations

import pandas as pd

from bridge.features import add_hand_features
from bridge.lead_analysis import add_lead_analysis_features


def _base_row(**overrides) -> dict:
    row = {
        "tournament_date": "2026-03-03",
        "board_no": 1,
        "decl": "N",
        "strain": "NT",
        "contract": "3NT",
        "level": 3,
        "lead": "♠K",
        "N_hand": "T987.5432.76.543",
        "S_hand": "A654.KQT.AT9.AT9",
        "Ø_hand": "KQJ2.A76.KQ5.J87",
        "V_hand": "983.J98.J843.KQ6",
    }
    row.update(overrides)
    return row


def test_valid_lead_detects_top_of_sequence():
    df = pd.DataFrame([_base_row()])
    out = add_lead_analysis_features(df)

    assert bool(out.loc[0, "lead_valid"]) is True
    assert out.loc[0, "lead_rank_class"] == "top_of_sequence"
    assert bool(out.loc[0, "exclude_from_lead_stats"]) is False


def test_invalid_lead_excluded_from_stats():
    df = pd.DataFrame([_base_row(lead="♠A")])
    out = add_lead_analysis_features(df)

    assert bool(out.loc[0, "lead_valid"]) is False
    assert bool(out.loc[0, "exclude_from_lead_stats"]) is True
    assert out.loc[0, "lead_rank_class"] == "unclear"


def test_partner_suit_candidate_detected():
    df = pd.DataFrame([
        _base_row(
            lead="♣7",
            Ø_hand="AQT9.876.KQJ.72",
            V_hand="KJ5.AK4.987.AQJT9",
        )
    ])
    out = add_lead_analysis_features(df)

    assert bool(out.loc[0, "lead_valid"]) is True
    assert bool(out.loc[0, "partner_suit_candidate"]) is True
    assert out.loc[0, "lead_strategic_class"] == "partner_suit_candidate"


def test_trump_lead_detected():
    df = pd.DataFrame([
        _base_row(
            strain="♥",
            contract="4♥",
            level=4,
            lead="♥8",
            Ø_hand="KQJ2.98.AQ5.J87",
        )
    ])
    out = add_lead_analysis_features(df)

    assert bool(out.loc[0, "lead_valid"]) is True
    assert bool(out.loc[0, "trump_lead"]) is True
    assert out.loc[0, "lead_strategic_class"] == "trump_lead"


def test_notrump_profile_match_for_fourth_highest_with_honor():
    df = pd.DataFrame([
        _base_row(
            lead="♠7",
            strain="NT",
            contract="3NT",
            Ø_hand="AKQ7.986.KQ5.J87",
        )
    ])
    out = add_lead_analysis_features(df)

    assert out.loc[0, "lead_rank_class"] == "4th_highest"
    assert bool(out.loc[0, "lead_profile_match"]) is True


def test_suit_contract_side_suit_third_highest_from_three_cards():
    """In suit contracts, 3rd-highest lead from a 3-card side suit is classified as 3rd_5th."""
    df = pd.DataFrame([
        _base_row(
            decl="Ø",          # leader = S
            strain="♠",
            contract="4♠",
            level=4,
            lead="♥2",
            S_hand="75.K82.T763.QT73",  # hearts = K82, so ♥2 is 3rd-highest
        )
    ])
    out = add_lead_analysis_features(df)

    assert bool(out.loc[0, "lead_valid"]) is True
    assert out.loc[0, "lead_rank_class"] == "3rd_5th"
    assert out.loc[0, "lead_strategic_class"] != "unclear"


def test_add_hand_features_integration_adds_lead_fields():
    df = pd.DataFrame([_base_row()])
    out = add_hand_features(df)

    expected = {
        "lead_valid",
        "lead_rank_class",
        "lead_strategic_class",
        "partner_suit_candidate",
        "trump_lead",
        "lead_profile_match",
        "exclude_from_lead_stats",
    }
    assert expected.issubset(set(out.columns))
    assert bool(out.loc[0, "lead_valid"]) is True
