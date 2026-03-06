"""Tests for latest-tournament row extraction and A/B/C board consistency checks."""

import pandas as pd

from bridge.board_review import (
    get_latest_tournament_other_rows_results,
    make_latest_tournament_board_consistency_check,
)


def _board_hands(board_no: int) -> tuple[str, str, str, str]:
    return (
        f"N{board_no}.A.K.Q",
        f"S{board_no}.J.T.9",
        f"Ø{board_no}.8.7.6",
        f"V{board_no}.5.4.3",
    )


def _make_evening_df(
    *,
    tournament_date: str = "2026-03-03",
    rows: tuple[str, ...] = ("A", "B", "C"),
    boards=range(1, 25),
) -> pd.DataFrame:
    out = []
    for row_code in rows:
        for board_no in boards:
            n_hand, s_hand, o_hand, v_hand = _board_hands(int(board_no))
            out.append(
                {
                    "tournament_date": tournament_date,
                    "board_no": int(board_no),
                    "row": row_code,
                    "section": row_code,
                    "ns1": f"{row_code}-NS1-{board_no}",
                    "ns2": f"{row_code}-NS2-{board_no}",
                    "ew1": f"{row_code}-EW1-{board_no}",
                    "ew2": f"{row_code}-EW2-{board_no}",
                    "contract": "3NT",
                    "lead": "♠A",
                    "tricks": 9,
                    "N_hand": n_hand,
                    "S_hand": s_hand,
                    "Ø_hand": o_hand,
                    "V_hand": v_hand,
                }
            )
    return pd.DataFrame(out)


def test_identifies_other_rows_for_latest_tournament():
    df_latest = _make_evening_df(tournament_date="2026-03-03")
    df_old_b = _make_evening_df(
        tournament_date="2026-02-24",
        rows=("B",),
        boards=(1, 2),
    )
    df = pd.concat([df_latest, df_old_b], ignore_index=True)

    out = get_latest_tournament_other_rows_results(df, base_row="A", other_rows=("B", "C"))

    assert len(out) == 48
    assert set(out["row_code"].unique()) == {"B", "C"}
    assert set(out["tournament_date"].astype(str).unique()) == {"2026-03-03"}


def test_board_consistency_ok_when_hands_identical():
    df = _make_evening_df()

    report, summary = make_latest_tournament_board_consistency_check(
        df,
        rows=("A", "B", "C"),
        board_start=1,
        board_end=24,
    )

    assert len(report) == 24
    assert int(summary["boards_ok"]) == 24
    assert int(summary["boards_mismatch"]) == 0
    assert int(summary["boards_missing_row"]) == 0
    assert bool(summary["is_consistent"]) is True


def test_board_consistency_detects_mismatch_between_rows():
    df = _make_evening_df()
    df.loc[(df["row"] == "B") & (df["board_no"] == 7), "N_hand"] = "DIFF.A.B.C"

    report, summary = make_latest_tournament_board_consistency_check(df)

    board7 = report[report["board_no"] == 7].iloc[0]
    assert board7["status"] == "MISMATCH"
    assert int(summary["boards_mismatch"]) == 1
    assert bool(summary["is_consistent"]) is False


def test_board_consistency_detects_missing_row_board():
    df = _make_evening_df()
    df = df[~((df["row"] == "C") & (df["board_no"] == 5))].copy()

    report, summary = make_latest_tournament_board_consistency_check(df)

    board5 = report[report["board_no"] == 5].iloc[0]
    assert board5["status"] == "MISSING_ROW"
    assert int(summary["boards_missing_row"]) == 1
    assert bool(summary["is_consistent"]) is False


def test_board_consistency_detects_internal_row_inconsistency():
    df = _make_evening_df()

    extra = df[(df["row"] == "A") & (df["board_no"] == 10)].iloc[0].copy()
    extra["N_hand"] = "ALT.A.B.C"
    df = pd.concat([df, pd.DataFrame([extra])], ignore_index=True)

    report, summary = make_latest_tournament_board_consistency_check(df)

    board10 = report[report["board_no"] == 10].iloc[0]
    assert board10["status"] == "ROW_INTERNAL_MISMATCH"
    assert int(summary["boards_row_internal_mismatch"]) == 1
    assert bool(summary["is_consistent"]) is False
