"""DataFrame enrichment with double-dummy lead information.

This module adds opening-lead quality metrics derived from double-dummy
analysis to a board/results DataFrame.  Results are cached in the SQLite
database managed by dd_cache so that each unique deal is solved at most once.

New columns added by enrich_lead_tables()
-----------------------------------------
lead_dd_tricks      : int   — declarer tricks achievable after the actual lead
                              (double-dummy, with perfect play from both sides)
dd_best_lead        : str   — canonical key of the best defensive opening lead,
                              i.e. the lead that minimises declarer tricks
                              e.g. "C3" (= ♣3)
dd_best_lead_tricks : int   — declarer tricks after the best defensive lead
lead_cost           : int   — lead_dd_tricks - dd_best_lead_tricks  (≥ 0)
                              0 means the actual lead was optimal for defence

New columns added by enrich_dd_fallback()
-----------------------------------------
Fills dd_{dir}_{strain} cells and sets dd_valid=True for rows where
dd_valid is False but the four hands are present.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from bridge.dd_compute import (
    compute_dd_table,
    compute_lead_table,
    parse_lead_card,
)
from bridge.dd_cache import (
    get_deal_hash,
    get_dd_table,
    save_dd_table,
    get_lead_table,
    save_lead_table,
)

# ---------------------------------------------------------------------------
# Strain symbol → field-name key mapping (for cache lookups)
# ---------------------------------------------------------------------------

_STRAIN_SYM_TO_KEY: dict[str, str] = {
    "NT": "NT",
    "♠": "S",
    "♥": "H",
    "♦": "D",
    "♣": "C",
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HAND_COLS = ["N_hand", "Ø_hand", "S_hand", "V_hand"]


def _has_hands(row: pd.Series) -> bool:
    return all(
        isinstance(row.get(c), str) and row.get(c)
        for c in _HAND_COLS
    )


def _get_or_compute_lead_table(
    row: pd.Series,
) -> Optional[dict[str, int]]:
    """Return (possibly cached) lead table for the row's contract/declarer.

    Returns None if key information is missing.
    """
    strain_sym = row.get("strain")
    decl = row.get("decl")
    if not strain_sym or not decl or not _has_hands(row):
        return None

    strain_key = _STRAIN_SYM_TO_KEY.get(str(strain_sym))
    if strain_key is None:
        return None

    deal_hash = get_deal_hash(row.to_dict())
    if deal_hash is None:
        return None

    # Cache hit
    cached = get_lead_table(deal_hash, strain_key, str(decl))
    if cached is not None:
        return cached

    # Cache miss — compute and store
    lead_table = compute_lead_table(row.to_dict())
    if lead_table:
        save_lead_table(deal_hash, strain_key, str(decl), lead_table)
    return lead_table or None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich_dd_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """Fill in DD trick table for rows where dd_valid is False.

    Rows without all four hands are skipped.  Computed results are cached.
    Modifies a copy of the DataFrame in-place and returns it.
    """
    out = df.copy()

    mask = out.get("dd_valid", pd.Series([False] * len(out))).apply(
        lambda v: v is False or v == 0
    )
    candidates = out[mask]
    if candidates.empty:
        return out

    _DD_COLS = [f"dd_{d}_{s}"
                for d in ["N", "Ø", "S", "V"]
                for s in ["NT", "S", "H", "D", "C"]]

    for idx, row in candidates.iterrows():
        if not _has_hands(row):
            continue

        deal_hash = get_deal_hash(row.to_dict())
        if deal_hash is None:
            continue

        # Check cache first
        cached = get_dd_table(deal_hash) if deal_hash else None
        if cached is None:
            try:
                cached = compute_dd_table(row.to_dict())
                save_dd_table(deal_hash, cached)
            except Exception:
                continue

        for col, val in cached.items():
            if col in out.columns:
                out.at[idx, col] = val
        out.at[idx, "dd_valid"] = True

    return out


def enrich_lead_tables(df: pd.DataFrame) -> pd.DataFrame:
    """Add lead-dependent DD columns to a results DataFrame.

    For each row that has:
    - all four hands
    - a valid strain and declarer direction
    - a non-empty lead field

    the function computes (or looks up) the DD lead table and populates:
    - lead_dd_tricks
    - dd_best_lead
    - dd_best_lead_tricks
    - lead_cost

    Rows that cannot be solved (missing data, endplay errors) get NaN / None.
    Results are cached in SQLite so each unique (deal, strain, declarer) triple
    is solved only once.
    """
    out = df.copy()

    # Initialise new columns with None
    for col in ["lead_dd_tricks", "dd_best_lead", "dd_best_lead_tricks", "lead_cost"]:
        if col not in out.columns:
            out[col] = None

    for idx, row in out.iterrows():
        if not _has_hands(row):
            continue

        lead_table = _get_or_compute_lead_table(row)
        if not lead_table:
            continue

        # Best defensive lead = card giving minimum declarer tricks (tie-break: key order)
        best_card = min(lead_table, key=lambda k: (lead_table[k], k))
        best_tricks = lead_table[best_card]
        out.at[idx, "dd_best_lead"] = best_card
        out.at[idx, "dd_best_lead_tricks"] = best_tricks

        # Tricks after the actual lead
        lead_raw = row.get("lead")
        lead_key = parse_lead_card(lead_raw) if lead_raw else None
        if lead_key and lead_key in lead_table:
            actual_tricks = lead_table[lead_key]
            out.at[idx, "lead_dd_tricks"] = actual_tricks
            out.at[idx, "lead_cost"] = actual_tricks - best_tricks

    return out
