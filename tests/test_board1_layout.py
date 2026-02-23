"""
Tests for write_board1_layout_sheet() in bridge/board_review.py.
"""

import io
import pandas as pd
import pytest

from openpyxl import Workbook
from unittest.mock import MagicMock

from bridge.board_review import write_board1_layout_sheet, _hand_suit_lines, _ROTATIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PER = "Per Føge Jensen"
HENRIK = "Henrik Friis"


def _make_writer_mock():
    """Return a minimal pd.ExcelWriter-like mock with a real openpyxl workbook."""
    wb = Workbook()
    # openpyxl creates a default sheet; remove it so the sheet list is clean
    wb.remove(wb.active)
    mock = MagicMock()
    mock.book = wb
    return mock, wb


def _make_df(**overrides):
    """Create a minimal single-row DataFrame for board 1."""
    row = {
        'tournament_date': '2026-01-15',
        'board_no': 1,
        'section': 'A',
        'ns1': PER,
        'ns2': HENRIK,
        'ew1': 'Opp East',
        'ew2': 'Opp West',
        'N_hand': 'AKT7.QJ3.984.AK2',
        'S_hand': '652.A75.KQ72.J54',
        'Ø_hand': 'QJ93.T862.AT.876',
        'V_hand': '84.K94.J653.QT93',
    }
    row.update(overrides)
    return pd.DataFrame([row])


# ---------------------------------------------------------------------------
# Unit tests for _hand_suit_lines
# ---------------------------------------------------------------------------

def test_hand_suit_lines_four_lines():
    lines = _hand_suit_lines('AKT7.QJ3.984.AK2')
    assert len(lines) == 4


def test_hand_suit_lines_suit_symbols():
    lines = _hand_suit_lines('AKT7.QJ3.984.AK2')
    assert lines[0] == '♠ AKT7'
    assert lines[1] == '♥ QJ3'
    assert lines[2] == '♦ 984'
    assert lines[3] == '♣ AK2'


def test_hand_suit_lines_none_returns_dashes():
    lines = _hand_suit_lines(None)
    for line in lines:
        assert '-' in line


# ---------------------------------------------------------------------------
# Unit tests for _ROTATIONS
# ---------------------------------------------------------------------------

def test_rotation_per_south_no_change():
    rot = _ROTATIONS['S']
    assert rot['bottom'] == 'S'
    assert rot['top'] == 'N'
    assert rot['left'] == 'V'
    assert rot['right'] == 'Ø'


def test_rotation_per_north_flipped():
    rot = _ROTATIONS['N']
    assert rot['bottom'] == 'N'
    assert rot['top'] == 'S'
    assert rot['left'] == 'Ø'
    assert rot['right'] == 'V'


def test_rotation_per_east():
    rot = _ROTATIONS['Ø']
    assert rot['bottom'] == 'Ø'
    assert rot['top'] == 'V'
    assert rot['left'] == 'S'
    assert rot['right'] == 'N'


def test_rotation_per_west():
    rot = _ROTATIONS['V']
    assert rot['bottom'] == 'V'
    assert rot['top'] == 'Ø'
    assert rot['left'] == 'N'
    assert rot['right'] == 'S'


# ---------------------------------------------------------------------------
# Integration tests for write_board1_layout_sheet
# ---------------------------------------------------------------------------

def test_sheet_created():
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, _make_df(), PER)
    assert 'Board1_LastTournament' in wb.sheetnames


def test_per_at_bottom_when_north():
    """Per is ns1 (North) → should appear at bottom with label 'N: Per Føge Jensen'."""
    df = _make_df()  # ns1 = Per = N
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    # Bottom player cell is row 14, col 2
    bottom_cell = ws.cell(row=14, column=2).value
    assert bottom_cell is not None
    assert PER in bottom_cell
    assert bottom_cell.startswith('N:')


def test_per_at_bottom_when_south():
    """Per is ns2 (South) → should appear at bottom with label 'S: Per Føge Jensen'."""
    df = _make_df(ns1=HENRIK, ns2=PER)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    bottom_cell = ws.cell(row=14, column=2).value
    assert bottom_cell is not None
    assert PER in bottom_cell
    assert bottom_cell.startswith('S:')


def test_per_at_bottom_when_east():
    """Per is ew1 (East/Ø) → should appear at bottom with label 'Ø: Per Føge Jensen'."""
    df = _make_df(ns1='Player A', ns2='Player B', ew1=PER, ew2=HENRIK)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    bottom_cell = ws.cell(row=14, column=2).value
    assert bottom_cell is not None
    assert PER in bottom_cell
    assert bottom_cell.startswith('Ø:')


def test_per_at_bottom_when_west():
    """Per is ew2 (West/V) → should appear at bottom with label 'V: Per Føge Jensen'."""
    df = _make_df(ns1='Player A', ns2='Player B', ew1=HENRIK, ew2=PER)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    bottom_cell = ws.cell(row=14, column=2).value
    assert bottom_cell is not None
    assert PER in bottom_cell
    assert bottom_cell.startswith('V:')


def test_hand_written_as_four_suit_lines():
    """The bottom hand must be spread over 4 rows (rows 15-18, col 2)."""
    df = _make_df()  # Per = N → N_hand = 'AKT7.QJ3.984.AK2'
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    lines = [ws.cell(row=15 + i, column=2).value for i in range(4)]
    assert str(lines[0]) == '♠ AKT7'
    # ♥ and ♦ may be rich text (red symbol); str() normalises both cases
    assert str(lines[1]) == '♥ QJ3'
    assert str(lines[2]) == '♦ 984'
    assert str(lines[3]) == '♣ AK2'


def test_latest_date_used():
    """When multiple dates exist, only the latest date is used."""
    df_old = _make_df(tournament_date='2025-12-01', ns1='Old Player', ns2='Old 2',
                      ew1='Old 3', ew2='Old 4')
    df_new = _make_df(tournament_date='2026-01-15')
    df = pd.concat([df_old, df_new], ignore_index=True)

    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    # Title cell (row 1 col 2) should reference the latest date
    title = ws.cell(row=1, column=2).value
    assert '2026-01-15' in str(title)
    assert '2025-12-01' not in str(title)


def test_missing_board1_writes_message():
    """When board 1 is absent from the latest tournament, a message is written."""
    df = _make_df(board_no=5)  # no board 1
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    msg = ws.cell(row=1, column=1).value
    assert msg is not None
    assert 'Spil 1' in msg


def test_per_not_found_writes_message():
    """When Per is not in board 1, a descriptive message is written."""
    df = _make_df(ns1='Someone', ns2='Else', ew1='Another', ew2='Player')
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    msg = ws.cell(row=1, column=1).value
    assert msg is not None
    assert PER in msg


def test_empty_dataframe_writes_message():
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, pd.DataFrame(), PER)
    ws = wb['Board1_LastTournament']

    msg = ws.cell(row=1, column=1).value
    assert msg is not None


def test_missing_board_no_column_writes_message():
    df = pd.DataFrame([{'tournament_date': '2026-01-15', 'ns1': PER}])
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    msg = ws.cell(row=1, column=1).value
    assert msg is not None


# ---------------------------------------------------------------------------
# Tests for new features: HCP, header block, right-side info, red suits
# ---------------------------------------------------------------------------

def test_player_label_includes_hcp_computed():
    """Player label must include HCP computed from hand (no HCP column supplied)."""
    df = _make_df()  # Per = N, N_hand = 'AKT7.QJ3.984.AK2' → 17 HCP
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    # Bottom cell (Per) row 14, col 2
    label = ws.cell(row=14, column=2).value
    assert '17 HCP' in label


def test_player_label_includes_hcp_from_column():
    """Player label uses per-hand HCP column when present."""
    df = _make_df(N_HCP=21)  # override with explicit column value
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    label = ws.cell(row=14, column=2).value
    assert '21 HCP' in label


def test_header_block_written_col_e():
    """Header block with Turnering/Board/Dealer/Zone written at column E."""
    df = _make_df(dealer='N', vul='NS')
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert '2026-01-15' in str(ws.cell(row=1, column=5).value)
    assert 'Board: 1' in str(ws.cell(row=2, column=5).value)
    assert 'N' in str(ws.cell(row=3, column=5).value)   # Dealer
    assert 'NS' in str(ws.cell(row=4, column=5).value)  # Zone


def test_header_block_fallback_when_no_dealer_zone():
    """Header block shows '(ukendt)' when dealer/zone columns absent."""
    df = _make_df()  # no dealer or vul column
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert '(ukendt)' in str(ws.cell(row=3, column=5).value)
    assert '(ukendt)' in str(ws.cell(row=4, column=5).value)


def test_right_info_block_contract_fields():
    """Right-side info block contains contract/decl/lead/tricks."""
    df = _make_df(contract='4S', decl='N', lead='♥A', tricks=10)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert '4S' in str(ws.cell(row=8, column=5).value)
    assert 'N'  in str(ws.cell(row=9, column=5).value)
    assert '♥A' in str(ws.cell(row=10, column=5).value)
    assert '10'  in str(ws.cell(row=11, column=5).value)


def test_right_info_block_hcp_totals_from_columns():
    """NS/ØV HCP totals shown from combined columns when present."""
    df = _make_df(NS_HCP=26, ØV_HCP=14)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert '26' in str(ws.cell(row=12, column=5).value)
    assert '14' in str(ws.cell(row=13, column=5).value)


def test_right_info_block_hcp_totals_computed():
    """NS/ØV HCP totals computed from per-hand HCP when combined columns absent."""
    # N_hand=17 HCP, S_hand → compute from 'S_hand'
    # N_hand='AKT7.QJ3.984.AK2' = 17 HCP, S_hand='652.A75.KQ72.J54' = 10 HCP → NS=27
    df = _make_df()
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    ns_cell = str(ws.cell(row=12, column=5).value)
    assert 'NS HCP' in ns_cell
    assert '27' in ns_cell


def test_red_suit_symbols_rich_text():
    """♥ and ♦ suit lines use rich text; ♠ and ♣ remain plain strings."""
    try:
        from openpyxl.cell.rich_text import CellRichText
    except ImportError:
        pytest.skip("openpyxl rich text not available")

    df = _make_df()  # Per = N, N_hand = 'AKT7.QJ3.984.AK2'
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    # Rows 15-18 are the bottom (Per's) hand
    spade_val   = ws.cell(row=15, column=2).value
    heart_val   = ws.cell(row=16, column=2).value
    diamond_val = ws.cell(row=17, column=2).value
    club_val    = ws.cell(row=18, column=2).value

    assert not isinstance(spade_val, CellRichText), "♠ should be plain string"
    assert not isinstance(club_val,  CellRichText), "♣ should be plain string"
    assert isinstance(heart_val,   CellRichText), "♥ should be CellRichText"
    assert isinstance(diamond_val, CellRichText), "♦ should be CellRichText"


def test_right_info_block_fallback_when_missing():
    """Right-side info shows '(ukendt)' when contract fields absent."""
    df = _make_df()  # no contract/decl/lead/tricks columns
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert '(ukendt)' in str(ws.cell(row=8, column=5).value)
    assert '(ukendt)' in str(ws.cell(row=9, column=5).value)


# ---------------------------------------------------------------------------
# Tests for mini traveller table (G1:Q2)
# ---------------------------------------------------------------------------

def test_mini_traveller_headers_at_g1():
    """Mini traveller header row must be written at G1:Q1."""
    df = _make_df()
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    # Column G = 7; headers span G1..Q1 (11 columns)
    headers = [ws.cell(row=1, column=7 + i).value for i in range(11)]
    assert headers[0] == 'NS-par'
    assert headers[1] == 'ØV-par'
    assert headers[2] == 'Kontrakt'
    assert headers[3] == 'Udspil'
    assert headers[4] == 'Stik'
    assert headers[5] == 'Score NS'
    assert headers[6] == 'Score ØV'
    assert headers[7] == 'MP/IMP NS'
    assert headers[8] == 'MP/IMP ØV'
    assert headers[9] == 'Pct NS'
    assert headers[10] == 'Pct ØV'


def test_mini_traveller_data_row_player_names():
    """Mini traveller data row (row 2) shows combined NS and ØV names."""
    df = _make_df(contract='4S', lead='♥A', tricks=10, pct_NS=58.3)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    ns_cell = ws.cell(row=2, column=7).value   # G2 = NS-par
    ov_cell = ws.cell(row=2, column=8).value   # H2 = ØV-par
    contract_cell = ws.cell(row=2, column=9).value  # I2 = Kontrakt
    lead_cell = ws.cell(row=2, column=10).value     # J2 = Udspil
    tricks_cell = ws.cell(row=2, column=11).value   # K2 = Stik
    pct_ns_cell = ws.cell(row=2, column=16).value   # P2 = Pct NS

    assert PER in str(ns_cell)
    assert HENRIK in str(ns_cell)
    assert 'Opp East' in str(ov_cell)
    assert 'Opp West' in str(ov_cell)
    assert contract_cell == '4S'
    assert lead_cell == '♥A'
    assert tricks_cell == 10
    assert pct_ns_cell == 58.3


def test_mini_traveller_pct_ov_column():
    """Pct ØV is read from pct_ØV column and placed at Q2 (column 17)."""
    df = _make_df(pct_ØV=41.7)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert ws.cell(row=2, column=17).value == 41.7


def test_mini_traveller_missing_pct_is_none():
    """When pct columns are absent, the data cells are None."""
    df = _make_df()  # no pct columns
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert ws.cell(row=2, column=16).value is None   # Pct NS
    assert ws.cell(row=2, column=17).value is None   # Pct ØV


# ---------------------------------------------------------------------------
# Tests for Double Dummy table (G6:M10)
# ---------------------------------------------------------------------------

def _make_df_with_dd(**extra):
    """Create a DataFrame row with dd_valid=True and representative DD values."""
    dd_data = {
        'dd_valid': True,
        'dd_N_NT': 9, 'dd_N_S': 10, 'dd_N_H': 8, 'dd_N_D': 7, 'dd_N_C': 6, 'dd_N_HCP': 17,
        'dd_S_NT': 8, 'dd_S_S': 9,  'dd_S_H': 7, 'dd_S_D': 6, 'dd_S_C': 5, 'dd_S_HCP': 10,
        'dd_Ø_NT': 4, 'dd_Ø_S': 3,  'dd_Ø_H': 5, 'dd_Ø_D': 6, 'dd_Ø_C': 7, 'dd_Ø_HCP': 6,
        'dd_V_NT': 5, 'dd_V_S': 4,  'dd_V_H': 6, 'dd_V_D': 7, 'dd_V_C': 8, 'dd_V_HCP': 7,
    }
    dd_data.update(extra)
    return _make_df(**dd_data)


def test_dd_table_title_when_valid():
    """Title cell G6 must read 'Double Dummy' when dd_valid is True."""
    df = _make_df_with_dd()
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert ws.cell(row=6, column=7).value == 'Double Dummy'


def test_dd_table_strain_headers():
    """Strain headers in H6:M6 must be NT, ♠, ♥, ♦, ♣, HP."""
    df = _make_df_with_dd()
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    headers = [ws.cell(row=6, column=8 + i).value for i in range(6)]
    assert headers == ['NT', '♠', '♥', '♦', '♣', 'HP']


def test_dd_table_row_labels():
    """Row labels in G7:G10 must be N, S, Ø, V."""
    df = _make_df_with_dd()
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    labels = [ws.cell(row=7 + i, column=7).value for i in range(4)]
    assert labels == ['N', 'S', 'Ø', 'V']


def test_dd_table_values_populated():
    """DD values must be written correctly in H7:L10."""
    df = _make_df_with_dd()
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    # Row 7 = N:  NT=9, ♠=10, ♥=8, ♦=7, ♣=6
    assert ws.cell(row=7, column=8).value == 9    # dd_N_NT
    assert ws.cell(row=7, column=9).value == 10   # dd_N_S (♠)
    assert ws.cell(row=7, column=10).value == 8   # dd_N_H (♥)
    assert ws.cell(row=7, column=11).value == 7   # dd_N_D (♦)
    assert ws.cell(row=7, column=12).value == 6   # dd_N_C (♣)

    # Row 9 = Ø:  NT=4
    assert ws.cell(row=9, column=8).value == 4    # dd_Ø_NT


def test_dd_table_hcp_column():
    """HP column (M = column 13) must contain HCP per direction."""
    df = _make_df_with_dd()
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    assert ws.cell(row=7, column=13).value == 17   # dd_N_HCP
    assert ws.cell(row=8, column=13).value == 10   # dd_S_HCP
    assert ws.cell(row=9, column=13).value == 6    # dd_Ø_HCP
    assert ws.cell(row=10, column=13).value == 7   # dd_V_HCP


def test_dd_table_not_available_when_dd_valid_false():
    """When dd_valid is False, G6 shows 'ikke tilgængelig' message."""
    df = _make_df(dd_valid=False)
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    msg = str(ws.cell(row=6, column=7).value)
    assert 'ikke tilgængelig' in msg


def test_dd_table_not_available_when_dd_valid_missing():
    """When dd_valid column is absent, G6 shows 'ikke tilgængelig' message."""
    df = _make_df()  # no dd_valid column
    writer, wb = _make_writer_mock()
    write_board1_layout_sheet(writer, df, PER)
    ws = wb['Board1_LastTournament']

    msg = str(ws.cell(row=6, column=7).value)
    assert 'ikke tilgængelig' in msg

