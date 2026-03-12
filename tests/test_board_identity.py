import pandas as pd

from bridge.board_identity import make_cross_club_board_identity_check


TARGET_DATE = "2026-03-11"


def _hands(tag: str) -> dict:
    return {
        "N_hand": f"N{tag}.1.1.1",
        "S_hand": f"S{tag}.1.1.1",
        "\u00d8_hand": f"E{tag}.1.1.1",
        "V_hand": f"W{tag}.1.1.1",
    }


def _row(board_no: int, clubno: int, row_code: str, tag: str) -> dict:
    data = {
        "tournament_date": TARGET_DATE,
        "board_no": board_no,
        "row": row_code,
        "clubno": clubno,
    }
    data.update(_hands(tag))
    return data


def test_cross_club_board_identity_statuses_and_summary():
    rows: list[dict] = []

    # Board 1: fully consistent across clubs and rows.
    for club in (1, 2, 3):
        for row_code in ("A", "B", "C"):
            rows.append(_row(1, club, row_code, "b1"))

    # Board 2: missing one required club+row combination.
    for club in (1, 2, 3):
        for row_code in ("A", "B", "C"):
            if club == 3 and row_code == "C":
                continue
            rows.append(_row(2, club, row_code, "b2"))

    # Board 3: one club has row mismatch (rows not equal inside club).
    for club in (1, 2, 3):
        for row_code in ("A", "B", "C"):
            tag = "b3_ok"
            if club == 2 and row_code == "A":
                tag = "b3_diff"
            rows.append(_row(3, club, row_code, tag))

    # Board 4: each club internally consistent, but clubs disagree.
    club_tags = {1: "b4_x", 2: "b4_y", 3: "b4_x"}
    for club in (1, 2, 3):
        for row_code in ("A", "B", "C"):
            rows.append(_row(4, club, row_code, club_tags[club]))

    # Board 5: internal mismatch within one club+row.
    for club in (1, 2, 3):
        for row_code in ("A", "B", "C"):
            rows.append(_row(5, club, row_code, "b5_ok"))
    rows.append(_row(5, 1, "A", "b5_alt"))

    df = pd.DataFrame(rows)

    report, summary = make_cross_club_board_identity_check(
        df,
        clubs=(1, 2, 3),
        rows=("A", "B", "C"),
        board_start=1,
        board_end=5,
        target_date=TARGET_DATE,
    )

    status_by_board = {
        int(board): status
        for board, status in zip(report["board_no"], report["status"])
    }

    assert status_by_board[1] == "OK"
    assert status_by_board[2] == "MISSING_CLUB_ROW"
    assert status_by_board[3] == "ROW_MISMATCH_WITHIN_CLUB"
    assert status_by_board[4] == "CLUB_MISMATCH"
    assert status_by_board[5] == "ROW_INTERNAL_MISMATCH"

    assert summary["boards_ok"] == 1
    assert summary["boards_missing_club_row"] == 1
    assert summary["boards_row_mismatch_within_club"] == 1
    assert summary["boards_club_mismatch"] == 1
    assert summary["boards_row_internal_mismatch"] == 1
    assert summary["ok_boards"] == [1]
    assert summary["target_date"] == TARGET_DATE


def test_missing_requested_club_does_not_zero_out_ok_boards():
    rows: list[dict] = []

    # Only clubs 2 and 3 have data for the date; club 1 is fully missing.
    for club in (2, 3):
        for row_code in ("A", "B", "C"):
            rows.append(_row(1, club, row_code, "same"))

    df = pd.DataFrame(rows)

    report, summary = make_cross_club_board_identity_check(
        df,
        clubs=(1, 2, 3),
        rows=("A", "B", "C"),
        board_start=1,
        board_end=1,
        target_date=TARGET_DATE,
    )

    assert report.loc[0, "status"] == "OK"
    assert summary["boards_ok"] == 1
    assert summary["ok_boards"] == [1]
    assert summary["clubs_checked"] == "2, 3"
    assert summary["clubs_missing_on_date"] == "1"
    assert summary["club_1_boards_all_rows_present"] == 0
    assert summary["club_2_boards_all_rows_present"] == 1
    assert summary["club_3_boards_all_rows_present"] == 1


def test_uses_section_when_row_is_degenerate():
    rows: list[dict] = []

    for section_name in ("A", "B", "C"):
        rows.append(
            {
                "tournament_date": TARGET_DATE,
                "board_no": 1,
                "clubno": 1,
                # Degenerate row values from source: always A.
                "row": "A",
                # Reliable section values.
                "section": section_name,
                "N_hand": "Nsame.1.1.1",
                "S_hand": "Ssame.1.1.1",
                "Ø_hand": "Esame.1.1.1",
                "V_hand": "Wsame.1.1.1",
            }
        )

    df = pd.DataFrame(rows)

    report, summary = make_cross_club_board_identity_check(
        df,
        clubs=(1,),
        rows=("A", "B", "C"),
        board_start=1,
        board_end=1,
        target_date=TARGET_DATE,
    )

    assert summary["row_column"] == "section"
    assert report.loc[0, "status"] == "OK"
    assert summary["boards_ok"] == 1


def test_mixed_row_source_by_club_keeps_valid_boards():
    rows: list[dict] = []

    # Club 1: row is degenerate (always A), section is reliable.
    for section_name in ("A", "B", "C"):
        rows.append(
            {
                "tournament_date": TARGET_DATE,
                "board_no": 1,
                "clubno": 1,
                "row": "A",
                "section": section_name,
                "N_hand": "Nsame.1.1.1",
                "S_hand": "Ssame.1.1.1",
                "Ø_hand": "Esame.1.1.1",
                "V_hand": "Wsame.1.1.1",
            }
        )

    # Club 2: row is reliable A/B/C.
    for row_code in ("A", "B", "C"):
        rows.append(
            {
                "tournament_date": TARGET_DATE,
                "board_no": 1,
                "clubno": 2,
                "row": row_code,
                "section": row_code,
                "N_hand": "Nsame.1.1.1",
                "S_hand": "Ssame.1.1.1",
                "Ø_hand": "Esame.1.1.1",
                "V_hand": "Wsame.1.1.1",
            }
        )

    df = pd.DataFrame(rows)

    report, summary = make_cross_club_board_identity_check(
        df,
        clubs=(1, 2),
        rows=("A", "B", "C"),
        board_start=1,
        board_end=1,
        target_date=TARGET_DATE,
    )

    assert summary["row_column"] == "mixed"
    assert "1:section" in summary.get("row_column_by_club", "")
    assert "2:row" in summary.get("row_column_by_club", "")
    assert report.loc[0, "status"] == "OK"
    assert summary["boards_ok"] == 1
