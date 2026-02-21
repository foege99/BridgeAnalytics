import pandas as pd
import numpy as np

HENRIK = "Henrik Friis"
PER = "Per Føge Jensen"


def is_ns(seat: str) -> bool:
    return seat in ["N", "S"]


def left_of(seat: str) -> str:
    order = ["N", "Ø", "S", "V"]
    return order[(order.index(seat) + 1) % 4]


def role(row, player):
    positions = {
        row.get("ns1", ""): "N",
        row.get("ns2", ""): "S",
        row.get("ew1", ""): "Ø",
        row.get("ew2", ""): "V",
    }

    seat = positions.get(player, "")
    decl = row.get("decl", "")

    if not seat or not decl:
        return ""

    if seat == decl:
        return "Declarer"

    if is_ns(seat) == is_ns(decl):
        return "Dummy"

    if seat == left_of(decl):
        return "Defense_Leader"

    return "Defense_Partner"


def pct_for(row, player):
    if player in [row.get("ns1", ""), row.get("ns2", "")]:
        return row.get("pct_NS", np.nan)
    if player in [row.get("ew1", ""), row.get("ew2", "")]:
        return row.get("pct_ØV", np.nan)
    return np.nan


# -----------------------------
# v0.1.x explicit status fields
# -----------------------------

def _is_missing(x) -> bool:
    return x is None or (isinstance(x, str) and x.strip() == "")


def _to_float_or_none(x):
    try:
        if _is_missing(x):
            return None
        return float(x)
    except Exception:
        return None


def compute_result_status(row) -> tuple[str, str]:
    """
    v0.1.x conservative rules for club 2183:

    If:
      (contract_raw missing OR decl missing)
      AND pct_NS == 50 AND pct_ØV == 50
    -> NOT_PLAYED_AVERAGE

    If any player name contains "Oversidder"
    -> SITOUT

    Else:
    -> PLAYED

    Important:
    - No heuristics for TL adjustments yet.
    - If pct != 50 and contract missing -> keep PLAYED.
    - source_url/spil_url remains authoritative reference (not touched here).
    """

    contract_raw = row.get("contract_raw")
    decl = row.get("decl")

    pct_ns = _to_float_or_none(row.get("pct_NS"))
    pct_ew = _to_float_or_none(row.get("pct_ØV"))

    names = " ".join(str(row.get(k) or "") for k in ["ns1", "ns2", "ew1", "ew2"])

    # Rule: SITOUT
    if "Oversidder" in names:
        return "SITOUT", "Oversidder"

    # Rule: NOT_PLAYED_AVERAGE
    if (_is_missing(contract_raw) or _is_missing(decl)) and (pct_ns == 50.0 and pct_ew == 50.0):
        return "NOT_PLAYED_AVERAGE", "Ikke spillet (gennemsnit 50/50)"

    # Default
    return "PLAYED", "Spillet"


def add_roles_and_pct(df: pd.DataFrame, henrik: str = HENRIK, per: str = PER) -> pd.DataFrame:
    """
    Adds:
      Henrik_role, Per_role, Henrik_pct, Per_pct
    and v0.1.x:
      result_status_code, result_status_text

    Must not change existing calculations: only adds columns.
    """
    df = df.copy()

    df["Henrik_role"] = df.apply(lambda r: role(r, henrik), axis=1)
    df["Per_role"] = df.apply(lambda r: role(r, per), axis=1)
    df["Henrik_pct"] = df.apply(lambda r: pct_for(r, henrik), axis=1)
    df["Per_pct"] = df.apply(lambda r: pct_for(r, per), axis=1)

    # v0.1.x: status fields (pure metadata)
    df[["result_status_code", "result_status_text"]] = df.apply(
        lambda r: pd.Series(compute_result_status(r)), axis=1
    )

    return df


def make_role_summary(df: pd.DataFrame, henrik: str = HENRIK, per: str = PER) -> pd.DataFrame:
    rows = []
    for player, col_role, col_pct in [
        (henrik, "Henrik_role", "Henrik_pct"),
        (per, "Per_role", "Per_pct"),
    ]:
        for r in ["Declarer", "Dummy", "Defense_Leader", "Defense_Partner"]:
            sub = df[df[col_role] == r]
            rows.append(
                {
                    "Player": player,
                    "Role": r,
                    "Count": len(sub),
                    "Avg_pct": sub[col_pct].mean() if len(sub) else np.nan,
                }
            )

    return pd.DataFrame(rows)


def make_declarer_list(df: pd.DataFrame, henrik: str = HENRIK, per: str = PER) -> pd.DataFrame:
    rows = []
    for player, role_col, pct_col in [
        (henrik, "Henrik_role", "Henrik_pct"),
        (per, "Per_role", "Per_pct"),
    ]:
        sub = df[df[role_col] == "Declarer"].copy()
        sub["Player"] = player
        sub["Player_pct"] = sub[pct_col]

        keep_cols = [
            "tournament_date",
            "board",
            "contract_raw",
            "decl",
            "lead",
            "tricks",
            "pct_NS",
            "pct_ØV",
            "spil_url",
            "Player",
            "Player_pct",
        ]
        for c in keep_cols:
            if c not in sub.columns:
                sub[c] = np.nan
        rows.append(sub[keep_cols])

    if not rows:
        return pd.DataFrame()

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["tournament_date", "board", "Player"])
    return out


def make_tournament_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tournament summary per date, player-oriented (HF/PF).

    Returns columns:
      tournament_date, boards,
      HF_total_pct, PF_total_pct,
      HF_declarer_pct, PF_declarer_pct,
      HF_defense_pct, PF_defense_pct

    Uses columns produced by add_roles_and_pct().
    """
    if df.empty:
        return pd.DataFrame()

    d = df.copy()

    if "tournament_date" not in d.columns:
        return pd.DataFrame()

    # boards = unique boards per date (matches typical 24 etc.)
    if "board" in d.columns:
        boards_series = d.groupby("tournament_date")["board"].nunique()
    else:
        boards_series = d.groupby("tournament_date").size()

    def _mean_where(g: pd.DataFrame, col: str, mask: pd.Series):
        x = g.loc[mask, col]
        return float(x.mean()) if len(x) else np.nan

    rows = []
    for tdate, g in d.groupby("tournament_date"):
        boards = int(boards_series.loc[tdate])

        hf_total = float(g["Henrik_pct"].mean()) if "Henrik_pct" in g.columns else np.nan
        pf_total = float(g["Per_pct"].mean()) if "Per_pct" in g.columns else np.nan

        hf_decl = _mean_where(g, "Henrik_pct", g.get("Henrik_role", "") == "Declarer")
        pf_decl = _mean_where(g, "Per_pct", g.get("Per_role", "") == "Declarer")

        hf_def = _mean_where(
            g, "Henrik_pct", g.get("Henrik_role", "").isin(["Defense_Leader", "Defense_Partner"])
        )
        pf_def = _mean_where(
            g, "Per_pct", g.get("Per_role", "").isin(["Defense_Leader", "Defense_Partner"])
        )

        rows.append(
            {
                "tournament_date": tdate,
                "boards": boards,
                "HF_total_pct": hf_total,
                "PF_total_pct": pf_total,
                "HF_declarer_pct": hf_decl,
                "PF_declarer_pct": pf_decl,
                "HF_defense_pct": hf_def,
                "PF_defense_pct": pf_def,
            }
        )

    out = pd.DataFrame(rows).sort_values("tournament_date")

    for c in [
        "HF_total_pct", "PF_total_pct",
        "HF_declarer_pct", "PF_declarer_pct",
        "HF_defense_pct", "PF_defense_pct",
    ]:
        if c in out.columns:
            out[c] = out[c].round(2)

    return out


def make_evening_role_matrix(df: pd.DataFrame, henrik: str = HENRIK, per: str = PER) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["tournament_date"] = pd.to_datetime(df["tournament_date"])

    def _role_means(sub, player_role_col, player_pct_col):
        roles = ["Declarer", "Defense_Leader", "Defense_Partner"]
        return {r: sub.loc[sub[player_role_col] == r, player_pct_col].mean() for r in roles}

    rows = []
    for d, sub in df.groupby(df["tournament_date"].dt.date):
        h = _role_means(sub, "Henrik_role", "Henrik_pct")
        p = _role_means(sub, "Per_role", "Per_pct")
        rows.append(
            {
                "Date": d,
                "Henrik_Declarer": h["Declarer"],
                "Henrik_Defence_Leader": h["Defense_Leader"],
                "Henrik_Defence_Partner": h["Defense_Partner"],
                "Per_Declarer": p["Declarer"],
                "Per_Defence_Leader": p["Defense_Leader"],
                "Per_Defence_Partner": p["Defense_Partner"],
            }
        )

    return pd.DataFrame(rows).sort_values("Date")


# -----------------------------
# Quarterly summary with CI (no input 'Player' column required)
# -----------------------------

def _ci95(mean: float, std: float, n: int) -> tuple[float, float]:
    if n < 2:
        return mean, mean
    se = std / float(np.sqrt(n))
    return mean - 1.96 * se, mean + 1.96 * se


def make_quarterly_summary_with_ci(df_pair: pd.DataFrame) -> pd.DataFrame:
    """
    Builds quarterly summary for Henrik/Per directly from df_pair, using Henrik_pct/Per_pct.
    Creates the output 'Player' column internally.
    """
    if df_pair.empty:
        return pd.DataFrame()

    df = df_pair.copy()
    if "tournament_date" not in df.columns:
        return pd.DataFrame()

    df["quarter"] = pd.to_datetime(df["tournament_date"]).dt.to_period("Q").astype(str)

    rows = []

    def _add_stats(player_label: str, pct_col: str, role_col: str, role_filter=None):
        if pct_col not in df.columns or role_col not in df.columns:
            return

        sub = df[df[pct_col].notna()].copy()
        if role_filter is not None:
            sub = sub[sub[role_col].isin(role_filter)]

        for q, g in sub.groupby("quarter"):
            s = g[pct_col].dropna()
            n = int(s.count())
            if n == 0:
                continue

            mean = float(s.mean())
            std = float(s.std(ddof=1)) if n >= 2 else 0.0
            lo, hi = _ci95(mean, std, n)

            role_name = "Overall" if role_filter is None else "/".join(role_filter)

            rows.append({
                "quarter": q,
                "Player": player_label,
                "Role": role_name,
                "Count": n,
                "Mean_pct": round(mean, 2),
                "Std": round(std, 2),
                "CI95_low": round(lo, 2),
                "CI95_high": round(hi, 2),
            })

    for player_label, pct_col, role_col in [
        ("Henrik", "Henrik_pct", "Henrik_role"),
        ("Per", "Per_pct", "Per_role"),
    ]:
        _add_stats(player_label, pct_col, role_col, role_filter=None)
        _add_stats(player_label, pct_col, role_col, role_filter=["Declarer"])
        _add_stats(player_label, pct_col, role_col, role_filter=["Defense_Leader"])
        _add_stats(player_label, pct_col, role_col, role_filter=["Defense_Partner"])

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    return out.sort_values(["quarter", "Player", "Role"])


# -----------------------------
# Fields_Pairs: Defence report (keeps current behavior)
# -----------------------------

def make_pair_field_report(df: pd.DataFrame, min_boards: int = 0) -> pd.DataFrame:
    """
    Pair-level report used for Fields_Pairs sheet.

    Output columns:
      Pair, Boards, Defence_avg_pct

    Notes:
      - This is side-specific (NS vs ØV) and may show the same pair twice
        if they appear both as NS_pair and ØV_pair across tournaments.
      - Filters pairs with fewer than min_boards.
      - Sorted by Defence_avg_pct desc.
    """
    if df.empty:
        return pd.DataFrame()

    d = df.copy()

    d["NS_pair"] = d["ns1"].astype(str) + " & " + d["ns2"].astype(str)
    d["ØV_pair"] = d["ew1"].astype(str) + " & " + d["ew2"].astype(str)

    ns = (
        d.groupby("NS_pair")
        .agg(Boards=("board", "count"), Defence_avg_pct=("pct_NS", "mean"))
        .reset_index()
        .rename(columns={"NS_pair": "Pair"})
    )

    ew = (
        d.groupby("ØV_pair")
        .agg(Boards=("board", "count"), Defence_avg_pct=("pct_ØV", "mean"))
        .reset_index()
        .rename(columns={"ØV_pair": "Pair"})
    )

    out = pd.concat([ns, ew], ignore_index=True)

    if min_boards and min_boards > 0:
        out = out[out["Boards"] >= int(min_boards)]

    out = out.sort_values(
        ["Defence_avg_pct", "Boards", "Pair"],
        ascending=[False, False, True]
    ).reset_index(drop=True)

    return out


# -----------------------------
# NEW: Fields_Pairs_Declarer: Declarer report (no duplicates)
# -----------------------------

def make_pair_declarer_report(df: pd.DataFrame, min_boards: int = 0) -> pd.DataFrame:
    """
    Pair-level declarer report, aggregated across NS+ØV so each pair appears once.

    Output columns:
      Pair, Boards, Declarer_avg_pct

    Sorted by Declarer_avg_pct desc.
    """
    if df.empty:
        return pd.DataFrame()

    d = df.copy()

    d["NS_pair"] = d["ns1"].astype(str) + " & " + d["ns2"].astype(str)
    d["ØV_pair"] = d["ew1"].astype(str) + " & " + d["ew2"].astype(str)

    # Identify declarer pair based on decl seat
    d["Declarer_pair"] = np.where(
        d["decl"].isin(["N", "S"]), d["NS_pair"],
        np.where(d["decl"].isin(["Ø", "V"]), d["ØV_pair"], np.nan)
    )

    # Declarer pct depends on which side declarer is on
    d["Declarer_pct"] = np.where(
        d["decl"].isin(["N", "S"]), d["pct_NS"],
        np.where(d["decl"].isin(["Ø", "V"]), d["pct_ØV"], np.nan)
    )

    out = (
        d.dropna(subset=["Declarer_pair"])
        .groupby("Declarer_pair")
        .agg(Boards=("board", "count"), Declarer_avg_pct=("Declarer_pct", "mean"))
        .reset_index()
        .rename(columns={"Declarer_pair": "Pair"})
    )

    if min_boards and min_boards > 0:
        out = out[out["Boards"] >= int(min_boards)]

    out = out.sort_values(
        ["Declarer_avg_pct", "Boards", "Pair"],
        ascending=[False, False, True]
    ).reset_index(drop=True)

    return out
def add_phase21_fields(df, n_min=12):
    """
    Phase 2.1 reference-lag berigelse.

    Forventet input-DataFrame med kolonner:
    - tournament_date (str)
    - board_no (int)
    - section (str)
    - result_status_code (str, fx "PLAYED", "SITOUT", "NOT_PLAYED_AVERAGE")
    - pct (float, 0-100)
    - contract (str)

    Returns original DataFrame + nye kolonner:
    - reference_scope, N_section_played, N_club_played, reference_n_played
    - field_mode_contract, field_mode_count, field_mode_freq
    - top2_contract_1, top2_contract_2, top2_count_1, top2_count_2
    - Board_Type, competitive_flag, expected_pct
    - contract_norm, double_state
    """
    if df.empty:
        print("⚠️ Phase 2.1: Input DataFrame er tom")
        return df

    df = df.copy()

    # === STEP 1: Normaliser kontrakter ===
    df["contract_norm"] = df["contract"].astype(str)
    df["double_state"] = ""

    for idx, row in df.iterrows():
        contract = str(row["contract"])
        if contract.endswith("XX"):
            df.at[idx, "contract_norm"] = contract[:-2]
            df.at[idx, "double_state"] = "XX"
        elif contract.endswith("X"):
            df.at[idx, "contract_norm"] = contract[:-1]
            df.at[idx, "double_state"] = "X"
        else:
            df.at[idx, "contract_norm"] = contract
            df.at[idx, "double_state"] = ""

    # === STEP 2: Initialiser output-kolonner ===
    df["reference_scope"] = None
    df["N_section_played"] = 0
    df["N_club_played"] = 0
    df["reference_n_played"] = 0
    df["field_mode_contract"] = None
    df["field_mode_count"] = None
    df["field_mode_freq"] = None
    df["top2_contract_1"] = None
    df["top2_contract_2"] = None
    df["top2_count_1"] = None
    df["top2_count_2"] = None
    df["Board_Type"] = "LOW_SAMPLE"
    df["competitive_flag"] = False
    df["expected_pct"] = None

    # === STEP 3: Filter kun PLAYED rækker med gyldig pct ===
    played_df = df[
        (df["result_status_code"] == "PLAYED") & (df["pct"].notna())
    ].copy()

    if played_df.empty:
        print("⚠️ Phase 2.1: Ingen PLAYED rækker med gyldig pct")
        return df

    print(f"✓ Phase 2.1: {len(played_df)} PLAYED rækker fundet")

    # === STEP 4: Beregn N_section_played og N_club_played ===
    section_groups = played_df.groupby(
        ["tournament_date", "board_no", "section"]
    ).size()
    club_groups = played_df.groupby(["tournament_date", "board_no"]).size()

    for idx, row in df.iterrows():
        date = row["tournament_date"]
        board = row["board_no"]
        sec = row["section"]
        df.at[idx, "N_section_played"] = section_groups.get((date, board, sec), 0)
        df.at[idx, "N_club_played"] = club_groups.get((date, board), 0)

    # === STEP 5: Vælg reference_scope ===
    for idx, row in df.iterrows():
        n_section = df.at[idx, "N_section_played"]
        n_club = df.at[idx, "N_club_played"]
        if n_section >= n_min:
            df.at[idx, "reference_scope"] = "SECTION"
            df.at[idx, "reference_n_played"] = n_section
        elif n_club >= n_min:
            df.at[idx, "reference_scope"] = "CLUB"
            df.at[idx, "reference_n_played"] = n_club
        else:
            df.at[idx, "reference_scope"] = "LOW_SAMPLE"
            df.at[idx, "reference_n_played"] = n_club

    # === STEP 6: MAIN LOOP – per (tournament_date, board_no, section) ===
    unique_groups = df[["tournament_date", "board_no", "section"]].drop_duplicates()
    print(
        f"✓ Phase 2.1: Behandler {len(unique_groups)} unikke grupper"
        " (turnering+board+sektion)"
    )

    for group_idx, (_, group_row) in enumerate(unique_groups.iterrows(), 1):
        date = group_row["tournament_date"]
        board = group_row["board_no"]
        sec = group_row["section"]

        group_mask = (
            (df["tournament_date"] == date)
            & (df["board_no"] == board)
            & (df["section"] == sec)
        )
        group_indices = df[group_mask].index

        if len(group_indices) == 0:
            continue

        ref_scope = df.at[group_indices[0], "reference_scope"]
        ref_n = df.at[group_indices[0], "reference_n_played"]

        # Bestem referencegruppe
        if ref_scope == "SECTION":
            ref_mask = (
                (played_df["tournament_date"] == date)
                & (played_df["board_no"] == board)
                & (played_df["section"] == sec)
            )
        else:
            ref_mask = (played_df["tournament_date"] == date) & (
                played_df["board_no"] == board
            )

        ref_group = played_df[ref_mask]
        if ref_group.empty:
            continue

        # Tæl kontrakt-frekvenser
        contract_counts = ref_group["contract_norm"].value_counts().to_dict()
        if not contract_counts:
            continue

        sorted_contracts = sorted(
            contract_counts.items(), key=lambda x: x[1], reverse=True
        )
        top1_contract, top1_count = sorted_contracts[0]
        top1_freq = top1_count / ref_n if ref_n > 0 else 0.0
        top2_contract = (
            sorted_contracts[1][0] if len(sorted_contracts) > 1 else None
        )
        top2_count = (
            sorted_contracts[1][1] if len(sorted_contracts) > 1 else None
        )

        # Klassificér Board_Type
        if ref_scope == "LOW_SAMPLE":
            board_type = "LOW_SAMPLE"
        else:
            p1 = top1_count / ref_n if ref_n > 0 else 0.0
            p2 = (
                (top2_count / ref_n)
                if (top2_count is not None and ref_n > 0)
                else 0.0
            )
            if p1 >= 0.70:
                board_type = "Dominant"
            elif (p1 + p2) >= 0.80 and p2 >= 0.25:
                board_type = "Split"
            else:
                board_type = "Wild"

        # Beregn expected_pct
        if top1_count >= 3:
            mode_mask = ref_mask & (played_df["contract_norm"] == top1_contract)
            mode_pcts = played_df[mode_mask]["pct"]
            expected_pct_val = mode_pcts.mean() if len(mode_pcts) > 0 else None
        else:
            expected_pct_val = (
                ref_group["pct"].mean() if len(ref_group) > 0 else None
            )

        for idx in group_indices:
            df.at[idx, "field_mode_contract"] = top1_contract
            df.at[idx, "field_mode_count"] = top1_count
            df.at[idx, "field_mode_freq"] = top1_freq
            df.at[idx, "top2_contract_1"] = top1_contract
            df.at[idx, "top2_count_1"] = top1_count
            df.at[idx, "top2_contract_2"] = top2_contract
            df.at[idx, "top2_count_2"] = top2_count
            df.at[idx, "Board_Type"] = board_type
            df.at[idx, "expected_pct"] = expected_pct_val

        if group_idx % 50 == 0:
            print(f"  ... behandlet {group_idx}/{len(unique_groups)} grupper")

    # === STEP 7: Beregn competitive_flag ===
    df["competitive_flag"] = df["Board_Type"] == "Split"

    # === STEP 8: Statistik ===
    board_type_counts = df["Board_Type"].value_counts().to_dict()
    print(f"\n✓ Phase 2.1 færdig:")
    print(f"  Dominant boards: {board_type_counts.get('Dominant', 0)}")
    print(f"  Split boards (competitive): {board_type_counts.get('Split', 0)}")
    print(f"  Wild boards: {board_type_counts.get('Wild', 0)}")
    print(f"  LOW_SAMPLE boards: {board_type_counts.get('LOW_SAMPLE', 0)}")

    return df
