"""Tests for pooled lead effect summary across all boards."""

from __future__ import annotations

import pandas as pd

from bridge.board_review import make_latest_tournament_lead_effect_allboards


def _row(
    *,
    date: str = '2026-03-03',
    board_no: int = 1,
    row_code: str = 'A',
    lead_type: str = 'sequence_lead',
    pct_def: float = 50.0,
    pct_decl: float = 50.0,
    decl: str = 'N',
    excluded: bool = False,
) -> dict:
    return {
        'tournament_date': date,
        'board_no': board_no,
        'row': row_code,
        'section': row_code,
        'decl': decl,
        'lead': '♠K',
        'lead_valid': not excluded,
        'exclude_from_lead_stats': excluded,
        'lead_strategic_class': lead_type,
        'lead_rank_class': 'unclear',
        'pct_NS': pct_decl,
        'pct_ØV': pct_def,
        'level': 4,
        'tricks': 10,
        'contract_required_tricks': 10,
    }


def test_sorted_best_to_worst_by_avg_pct_not_by_count():
    rows = [
        _row(board_no=1, row_code='A', lead_type='best_type', pct_def=70.0, pct_decl=30.0),
        _row(board_no=2, row_code='B', lead_type='mid_type', pct_def=55.0, pct_decl=45.0),
        _row(board_no=3, row_code='C', lead_type='worst_type', pct_def=40.0, pct_decl=60.0),
        _row(board_no=4, row_code='A', lead_type='worst_type', pct_def=45.0, pct_decl=55.0),
    ]
    df = pd.DataFrame(rows)

    out = make_latest_tournament_lead_effect_allboards(df, rows=('A', 'B', 'C'), board_start=1, board_end=24)

    assert len(out) == 3
    assert list(out['lead_type']) == ['best_type', 'mid_type', 'worst_type']
    assert list(out['rank_best_to_worst']) == [1, 2, 3]
    assert float(out.loc[0, 'avg_pct_defense']) == 70.0
    assert float(out.loc[0, 'avg_pct_decl']) == 30.0


def test_excluded_leads_removed_and_totals_preserved():
    df = pd.DataFrame([
        _row(board_no=1, row_code='A', lead_type='kept_type', pct_def=52.0, excluded=False),
        _row(board_no=2, row_code='B', lead_type='excluded_type', pct_def=95.0, excluded=True),
    ])

    out = make_latest_tournament_lead_effect_allboards(df)

    assert len(out) == 1
    assert out.loc[0, 'lead_type'] == 'kept_type'
    assert int(out.loc[0, 'valid_leads']) == 1
    assert int(out.loc[0, 'total_leads']) == 2


def test_uses_latest_tournament_and_board_range():
    df = pd.DataFrame([
        _row(date='2026-02-24', board_no=1, row_code='A', lead_type='old_type', pct_def=90.0),
        _row(date='2026-03-03', board_no=1, row_code='A', lead_type='in_range', pct_def=60.0),
        _row(date='2026-03-03', board_no=28, row_code='B', lead_type='out_of_range', pct_def=99.0),
    ])

    out = make_latest_tournament_lead_effect_allboards(df, board_start=1, board_end=24)

    assert len(out) == 1
    assert out.loc[0, 'lead_type'] == 'in_range'
    assert str(out.loc[0, 'tournament_date']) == '2026-03-03'
