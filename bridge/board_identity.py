import pandas as pd


def _normalize_row_code(value) -> str | None:
    """Normalize row/section code to uppercase string, else None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    txt = str(value).strip().upper()
    return txt if txt else None


def _normalize_clubno(value) -> int | None:
    """Normalize club number to int, else None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mode_or_first(series: pd.Series):
    """Return deterministic representative value from a series."""
    if series.empty:
        return None
    mode_vals = series.mode(dropna=False)
    if not mode_vals.empty:
        return mode_vals.iloc[0]
    return series.iloc[0]


def make_cross_club_board_identity_check(
    df: pd.DataFrame,
    clubs: tuple[int, ...] = (1, 2, 3),
    rows: tuple[str, ...] = ("A", "B", "C"),
    board_start: int = 1,
    board_end: int = 24,
    target_date=None,
) -> tuple[pd.DataFrame, dict]:
    """
    Validate that boards are identical across clubs and rows for one target date.

    Uses hand-record signature:
        N_hand | S_hand | Ø_hand | V_hand

    Status values:
    - OK
    - MISSING_CLUB_ROW
    - ROW_INTERNAL_MISMATCH
    - ROW_MISMATCH_WITHIN_CLUB
    - CLUB_MISMATCH
    """
    start = int(board_start)
    end = int(board_end)
    if start > end:
        start, end = end, start

    target_rows: list[str] = []
    for row in rows:
        norm = _normalize_row_code(row)
        if norm and norm not in target_rows:
            target_rows.append(norm)
    if not target_rows:
        target_rows = ["A", "B", "C"]

    target_clubs: list[int] = []
    for club in clubs:
        norm = _normalize_clubno(club)
        if norm is not None and norm not in target_clubs:
            target_clubs.append(norm)
    target_clubs = sorted(target_clubs)
    requested_clubs = list(target_clubs)

    summary = {
        "target_date": None,
        "row_column": None,
        "club_column": None,
        "rows_checked": ", ".join(target_rows),
        "clubs_requested": ", ".join(str(c) for c in requested_clubs),
        "clubs_checked": "",
        "clubs_missing_on_date": "",
        "board_start": start,
        "board_end": end,
        "boards_checked": max(end - start + 1, 0),
        "boards_ok": 0,
        "boards_missing_club_row": 0,
        "boards_row_internal_mismatch": 0,
        "boards_row_mismatch_within_club": 0,
        "boards_club_mismatch": 0,
        "is_consistent": False,
        "ok_boards": [],
        "error": "",
    }

    report = pd.DataFrame({"board_no": list(range(start, end + 1))})

    if df is None or df.empty:
        summary["error"] = "Ingen data tilgængelig."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    if "tournament_date" not in df.columns:
        summary["error"] = "Kolonnen 'tournament_date' mangler."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    if "board_no" not in df.columns:
        summary["error"] = "Kolonnen 'board_no' mangler."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    if "row" not in df.columns and "section" not in df.columns:
        summary["error"] = "Kolonne 'row' eller 'section' mangler."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    if "clubno" not in df.columns:
        summary["error"] = "Kolonnen 'clubno' mangler."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary
    summary["club_column"] = "clubno"

    hand_cols = ["N_hand", "S_hand", "Ø_hand", "V_hand"]
    missing_hand_cols = [c for c in hand_cols if c not in df.columns]
    if missing_hand_cols:
        summary["error"] = f"Manglende hånd-kolonner: {', '.join(missing_hand_cols)}"
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    work = df.copy()
    work["_tdate"] = pd.to_datetime(work["tournament_date"], errors="coerce").dt.date

    if target_date is None:
        max_ts = pd.to_datetime(work["tournament_date"], errors="coerce").max()
        if pd.isna(max_ts):
            summary["error"] = "Kunne ikke bestemme target dato."
            report["status"] = "MISSING_CLUB_ROW"
            return report, summary
        target_date = max_ts.date()
    else:
        target_ts = pd.to_datetime(target_date, errors="coerce")
        if pd.isna(target_ts):
            summary["error"] = "Ugyldig target dato."
            report["status"] = "MISSING_CLUB_ROW"
            return report, summary
        target_date = target_ts.date()

    summary["target_date"] = str(target_date)

    work = work[work["_tdate"] == target_date].copy()
    if work.empty:
        summary["error"] = f"Ingen data fundet for target dato {target_date}."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    work["clubno_int"] = work["clubno"].apply(_normalize_clubno)
    work["board_no_int"] = pd.to_numeric(work["board_no"], errors="coerce")

    if not target_clubs:
        target_clubs = sorted(c for c in work["clubno_int"].dropna().unique().tolist())
        requested_clubs = list(target_clubs)
        summary["clubs_requested"] = ", ".join(str(c) for c in requested_clubs)

    def _row_coverage_score(values: pd.Series) -> tuple[int, int]:
        vals = values.apply(_normalize_row_code)
        mask = vals.isin(target_rows)
        distinct = int(vals[mask].nunique())
        coverage = int(mask.sum())
        return distinct, coverage

    club_row_source: dict[int, str] = {}
    if "row" in work.columns and "section" in work.columns:
        for clubno in target_clubs:
            sub = work[work["clubno_int"] == clubno]
            if sub.empty:
                continue
            row_score = _row_coverage_score(sub["row"])
            section_score = _row_coverage_score(sub["section"])
            club_row_source[clubno] = "section" if section_score > row_score else "row"

        if not club_row_source:
            row_col = "row"
            summary["row_column"] = row_col
            work["row_code"] = work[row_col].apply(_normalize_row_code)
        else:
            source_set = set(club_row_source.values())
            summary["row_column"] = source_set.pop() if len(source_set) == 1 else "mixed"

            # Use best row-source per club to avoid one bad source contaminating all clubs.
            def _select_row_code(rec):
                club = rec.get("clubno_int")
                src = club_row_source.get(club, "row")
                return _normalize_row_code(rec.get(src))

            work["row_code"] = work.apply(_select_row_code, axis=1)

        summary["row_column_by_club"] = ", ".join(
            f"{club}:{src}" for club, src in sorted(club_row_source.items())
        )
    elif "row" in work.columns:
        row_col = "row"
        summary["row_column"] = row_col
        work["row_code"] = work[row_col].apply(_normalize_row_code)
    else:
        row_col = "section"
        summary["row_column"] = row_col
        work["row_code"] = work[row_col].apply(_normalize_row_code)

    eligible = work[
        work["row_code"].isin(target_rows)
        & work["board_no_int"].between(start, end, inclusive="both")
    ].copy()

    active_clubs = sorted(
        c
        for c in target_clubs
        if c in set(eligible["clubno_int"].dropna().astype(int).tolist())
    )

    if not active_clubs:
        summary["error"] = "Ingen data fundet for de ønskede klubber på target dato."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    missing_on_date = [c for c in requested_clubs if c not in active_clubs]
    summary["clubs_checked"] = ", ".join(str(c) for c in active_clubs)
    summary["clubs_missing_on_date"] = ", ".join(str(c) for c in missing_on_date)

    work = eligible[eligible["clubno_int"].isin(active_clubs)].copy()

    if work.empty:
        summary["error"] = "Ingen data efter filtrering på klub/række/board-interval."
        report["status"] = "MISSING_CLUB_ROW"
        return report, summary

    work["board_no_int"] = work["board_no_int"].astype(int)
    work["_hand_signature"] = work[hand_cols].fillna("").astype(str).agg("|".join, axis=1)

    grouped = work.groupby(["clubno_int", "row_code", "board_no_int"], dropna=False).agg(
        n_results=("board_no", "size"),
        n_unique_signatures=("_hand_signature", "nunique"),
        signature=("_hand_signature", _mode_or_first),
    ).reset_index()

    # Build report columns per club+row.
    for clubno in active_clubs:
        for row_code in target_rows:
            prefix = f"club{clubno}_{row_code}"
            subset = grouped[
                (grouped["clubno_int"] == clubno) & (grouped["row_code"] == row_code)
            ].set_index("board_no_int")

            report[f"{prefix}_n_results"] = report["board_no"].map(subset["n_results"])
            report[f"{prefix}_n_unique_signatures"] = report["board_no"].map(
                subset["n_unique_signatures"]
            )
            report[f"{prefix}_signature"] = report["board_no"].map(subset["signature"])
            report[f"{prefix}_present"] = (
                report[f"{prefix}_signature"].notna()
                & (report[f"{prefix}_signature"].astype(str) != "")
            )

    for clubno in active_clubs:
        per_row_present_cols = [f"club{clubno}_{row_code}_present" for row_code in target_rows]
        per_row_unique_cols = [
            f"club{clubno}_{row_code}_n_unique_signatures" for row_code in target_rows
        ]
        per_row_signature_cols = [f"club{clubno}_{row_code}_signature" for row_code in target_rows]

        report[f"club{clubno}_all_rows_present"] = report[per_row_present_cols].all(axis=1)
        report[f"club{clubno}_row_internal_mismatch"] = (
            report[per_row_unique_cols].fillna(0).astype(float) > 1
        ).any(axis=1)

        def _rows_equal_for_club(row) -> bool:
            if not row[f"club{clubno}_all_rows_present"]:
                return False
            if row[f"club{clubno}_row_internal_mismatch"]:
                return False
            signatures = [row[c] for c in per_row_signature_cols]
            sig_set = {str(v) for v in signatures if pd.notna(v) and str(v) != ""}
            return len(sig_set) == 1 and len(signatures) == len(target_rows)

        report[f"club{clubno}_rows_equal"] = report.apply(_rows_equal_for_club, axis=1)
        base_sig_col = f"club{clubno}_{target_rows[0]}_signature"
        report[f"club{clubno}_signature"] = report[base_sig_col].where(
            report[f"club{clubno}_rows_equal"],
            pd.NA,
        )

    club_present_cols = [f"club{clubno}_all_rows_present" for clubno in active_clubs]
    club_internal_cols = [f"club{clubno}_row_internal_mismatch" for clubno in active_clubs]
    club_rows_equal_cols = [f"club{clubno}_rows_equal" for clubno in active_clubs]
    club_signature_cols = [f"club{clubno}_signature" for clubno in active_clubs]

    report["all_clubs_rows_present"] = report[club_present_cols].all(axis=1)
    report["any_row_internal_mismatch"] = report[club_internal_cols].any(axis=1)
    report["all_clubs_rows_equal"] = report[club_rows_equal_cols].all(axis=1)

    def _clubs_equal(row) -> bool:
        if not row["all_clubs_rows_present"]:
            return False
        if row["any_row_internal_mismatch"]:
            return False
        if not row["all_clubs_rows_equal"]:
            return False
        signatures = [row[c] for c in club_signature_cols]
        sig_set = {str(v) for v in signatures if pd.notna(v) and str(v) != ""}
        return len(sig_set) == 1 and len(signatures) == len(active_clubs)

    report["clubs_equal"] = report.apply(_clubs_equal, axis=1)

    report["status"] = "OK"
    report.loc[~report["all_clubs_rows_present"], "status"] = "MISSING_CLUB_ROW"
    report.loc[
        report["all_clubs_rows_present"] & report["any_row_internal_mismatch"],
        "status",
    ] = "ROW_INTERNAL_MISMATCH"
    report.loc[
        report["all_clubs_rows_present"]
        & ~report["any_row_internal_mismatch"]
        & ~report["all_clubs_rows_equal"],
        "status",
    ] = "ROW_MISMATCH_WITHIN_CLUB"
    report.loc[
        report["all_clubs_rows_present"]
        & ~report["any_row_internal_mismatch"]
        & report["all_clubs_rows_equal"]
        & ~report["clubs_equal"],
        "status",
    ] = "CLUB_MISMATCH"

    summary["boards_ok"] = int((report["status"] == "OK").sum())
    summary["boards_missing_club_row"] = int((report["status"] == "MISSING_CLUB_ROW").sum())
    summary["boards_row_internal_mismatch"] = int(
        (report["status"] == "ROW_INTERNAL_MISMATCH").sum()
    )
    summary["boards_row_mismatch_within_club"] = int(
        (report["status"] == "ROW_MISMATCH_WITHIN_CLUB").sum()
    )
    summary["boards_club_mismatch"] = int((report["status"] == "CLUB_MISMATCH").sum())
    summary["ok_boards"] = report.loc[report["status"] == "OK", "board_no"].tolist()
    summary["is_consistent"] = (
        summary["boards_checked"] > 0
        and summary["boards_ok"] == summary["boards_checked"]
    )

    for clubno in requested_clubs:
        present_col = f"club{clubno}_all_rows_present"
        rows_equal_col = f"club{clubno}_rows_equal"
        summary[f"club_{clubno}_boards_all_rows_present"] = int(
            report[present_col].sum() if present_col in report.columns else 0
        )
        summary[f"club_{clubno}_boards_rows_equal"] = int(
            report[rows_equal_col].sum() if rows_equal_col in report.columns else 0
        )

    ordered_cols = [
        "board_no",
        "status",
        "all_clubs_rows_present",
        "all_clubs_rows_equal",
        "clubs_equal",
    ]

    for clubno in active_clubs:
        ordered_cols.extend(
            [
                f"club{clubno}_all_rows_present",
                f"club{clubno}_row_internal_mismatch",
                f"club{clubno}_rows_equal",
                f"club{clubno}_signature",
            ]
        )

    for clubno in active_clubs:
        for row_code in target_rows:
            ordered_cols.extend(
                [
                    f"club{clubno}_{row_code}_present",
                    f"club{clubno}_{row_code}_n_results",
                    f"club{clubno}_{row_code}_n_unique_signatures",
                    f"club{clubno}_{row_code}_signature",
                ]
            )

    report = report[[c for c in ordered_cols if c in report.columns]]
    return report, summary


def print_cross_club_board_identity_summary(summary: dict) -> None:
    """Print readable summary from make_cross_club_board_identity_check()."""
    print("\n" + "=" * 70)
    print("BOARD-IDENTITET PÅ TVÆRS AF KLUBBER (TARGET DATO)")
    print("=" * 70)

    if summary.get("error"):
        print(f"\nFejl: {summary['error']}")
        print("\n" + "=" * 70)
        return

    print(f"\nTarget dato: {summary.get('target_date')}")
    print(f"Klubber ønsket: {summary.get('clubs_requested')}")
    if summary.get('clubs_missing_on_date'):
        print(f"Klubber uden data på dato: {summary.get('clubs_missing_on_date')}")
    print(f"Klubber checket: {summary.get('clubs_checked')}")
    print(f"Rækker checket: {summary.get('rows_checked')}")
    if summary.get('row_column_by_club'):
        print(f"Række-kilde pr. klub: {summary.get('row_column_by_club')}")
    print(f"Board-interval: {summary.get('board_start')}–{summary.get('board_end')}")
    print(f"Boards checket: {summary.get('boards_checked')}")
    print(f"Boards OK: {summary.get('boards_ok')}")
    print(f"Boards med manglende klub/række: {summary.get('boards_missing_club_row')}")
    print(f"Boards med intern række-mismatch: {summary.get('boards_row_internal_mismatch')}")
    print(f"Boards med række-mismatch i klub: {summary.get('boards_row_mismatch_within_club')}")
    print(f"Boards med mismatch mellem klubber: {summary.get('boards_club_mismatch')}")

    clubs_requested = [
        s.strip() for s in str(summary.get("clubs_requested", "")).split(",") if s.strip()
    ]
    if clubs_requested:
        print("\nDækning pr. klub:")
        for club_txt in clubs_requested:
            print(
                f"  Club {club_txt}: "
                f"{summary.get(f'club_{club_txt}_boards_all_rows_present', 0)} boards med alle rækker, "
                f"{summary.get(f'club_{club_txt}_boards_rows_equal', 0)} boards med ens rækker"
            )

    verdict = "JA" if summary.get("is_consistent") else "NEJ"
    print(f"\nEr board-fordelinger ens på tværs af klub/række? {verdict}")
    print("\n" + "=" * 70)
