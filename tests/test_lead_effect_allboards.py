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
    lead: str = '♠K',
    pct_def: float = 50.0,
    pct_decl: float = 50.0,
    decl: str = 'N',
    level: int = 4,
    strain: str = '♥',
    contract: str | None = None,
    excluded: bool = False,
) -> dict:
    if contract is None:
        contract = f"{level}{strain}" if strain != 'NT' else f"{level}NT"

    return {
        'tournament_date': date,
        'board_no': board_no,
        'row': row_code,
        'section': row_code,
        'decl': decl,
        'contract': contract,
        'lead': lead,
        'lead_valid': not excluded,
        'exclude_from_lead_stats': excluded,
        'lead_strategic_class': lead_type,
        'lead_rank_class': 'unclear',
        'pct_NS': pct_decl,
        'pct_ØV': pct_def,
        'level': level,
        'strain': strain,
        'tricks': 10,
        'contract_required_tricks': (level + 6),
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


def test_contract_pool_top5_and_slams_are_separate():
    df = pd.DataFrame([
        # 1-5♥ pooled
        _row(board_no=1, row_code='A', lead_type='heart_type_1', level=1, strain='♥', contract='1♥', decl='N'),
        _row(board_no=14, row_code='A', lead_type='heart_type_1', level=2, strain='♥', contract='2♥', decl='N', lead='♥Q'),
        _row(board_no=2, row_code='A', lead_type='heart_type_2', level=3, strain='♥', contract='3♥', decl='S'),
        _row(board_no=3, row_code='A', lead_type='heart_type_3', level=5, strain='♥', contract='5♥', decl='N'),

        # 1-5NT pooled
        _row(board_no=4, row_code='B', lead_type='nt_type_1', level=1, strain='NT', contract='1NT', decl='N'),
        _row(board_no=5, row_code='B', lead_type='nt_type_2', level=3, strain='NT', contract='3NT', decl='S'),
        _row(board_no=6, row_code='B', lead_type='nt_type_3', level=5, strain='NT', contract='5NT', decl='Ø'),

        # Slams must stay separate
        _row(board_no=7, row_code='C', lead_type='slam6_type', level=6, strain='♥', contract='6♥', decl='Ø'),
        _row(board_no=8, row_code='C', lead_type='slam6_type', level=6, strain='♥', contract='6♥', decl='V'),
        _row(board_no=9, row_code='C', lead_type='slam7_type', level=7, strain='NT', contract='7NT', decl='N'),
        _row(board_no=10, row_code='C', lead_type='slam7_type', level=7, strain='NT', contract='7NT', decl='S'),

        # Fifth pool in top-5
        _row(board_no=11, row_code='A', lead_type='spade_type', level=2, strain='♠', contract='2♠', decl='N'),
        _row(board_no=12, row_code='A', lead_type='spade_type', level=4, strain='♠', contract='4♠', decl='S'),

        # Lower-frequency pool outside top-5
        _row(board_no=13, row_code='A', lead_type='diamond_type', level=3, strain='♦', contract='3♦', decl='N'),
    ])

    out = make_latest_tournament_lead_effect_allboards(
        df,
        rows=('A', 'B', 'C'),
        board_start=1,
        board_end=24,
        contract_top_n=5,
        include_decl_hand=True,
    )

    pools = set(out['contract_pool'].astype(str).tolist())
    assert pools == {'1-5♥', '1-5NT', '6♥', '7NT', '1-5♠'}
    assert '1-5♦' not in pools
    assert 'contract_color' in out.columns
    assert set(out['contract_color'].astype(str).tolist()).issubset({'♥', 'NT', '♠'})
    assert 'lead_values' in out.columns
    heart_row = out[(out['contract_pool'] == '1-5♥') & (out['decl_hand'] == 'N') & (out['lead_type'] == 'heart_type_1')]
    assert not heart_row.empty
    heart_leads = str(heart_row.iloc[0]['lead_values'])
    assert '♠K' in heart_leads
    assert '♥Q' in heart_leads
    assert ',' in heart_leads
    assert 'decl_hand' in out.columns
    assert set(out['decl_hand'].astype(str).unique()).issubset({'N', 'S', 'Ø', 'V', 'ukendt'})
    assert 'lead_hand' in out.columns
    assert set(out['lead_hand'].astype(str).unique()).issubset({'N', 'S', 'Ø', 'V', 'ukendt'})
    assert 'avg_play_precision_dd' not in out.columns
