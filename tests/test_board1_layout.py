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
    assert lines[0] == '♠ AKT7'
    assert lines[1] == '♥ QJ3'
    assert lines[2] == '♦ 984'
    assert lines[3] == '♣ AK2'


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
