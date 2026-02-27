"""
bridge/mvp_metrics.py

MVP Analysis Framework – Phase 1.

Adds three groups of metrics to the main result DataFrame:

A. Contract quality (melding)
B. Execution quality (spilføring)
C. Lead & defence (udspil/modspil)

All computations are deterministic heuristics operating on existing
Phase 2.1 / reference-layer columns.  The function ``add_mvp_metrics``
is the single entry-point: call it after ``add_hand_features`` and
``add_phase21_fields`` have run.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# DD column helpers
# ---------------------------------------------------------------------------

# Strain values as produced by the scraper (and stored in 'strain' column)
_SUIT_STRAINS = {"S", "H", "D", "C"}

# Mapping from strain value to the key used in dd_ column names
# The scraper already uses NT/S/H/D/C so the mapping is identity.
_STRAIN_TO_DD_KEY: dict[str, str] = {
    "NT": "NT",
    "S": "S",
    "H": "H",
    "D": "D",
    "C": "C",
}

# Valid declarers (compass, Danish notation)
_VALID_DECL = {"N", "S", "Ø", "V"}


def _dd_tricks_for_decl(row: pd.Series) -> Optional[int]:
    """
    Return the double-dummy trick count for the actual declarer + strain.

    Returns None when dd_valid is False/missing, decl or strain is unknown,
    or the specific dd column is missing/null.
    """
    if not row.get("dd_valid", False):
        return None

    decl = row.get("decl")
    strain = row.get("strain")

    if not decl or decl not in _VALID_DECL:
        return None

    strain_key = _STRAIN_TO_DD_KEY.get(str(strain).upper() if strain else "")
    if strain_key is None:
        return None

    col = f"dd_{decl}_{strain_key}"
    val = row.get(col)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# A. Contract quality helpers
# ---------------------------------------------------------------------------

def _combined_hcp(row: pd.Series) -> Optional[float]:
    ns = row.get("NS_HCP")
    ov = row.get("ØV_HCP")
    if ns is None or ov is None:
        return None
    if isinstance(ns, float) and math.isnan(ns):
        return None
    if isinstance(ov, float) and math.isnan(ov):
        return None
    return float(ns) + float(ov)


def _expected_level_hcp(combined_hcp: Optional[float]) -> Optional[int]:
    if combined_hcp is None:
        return None
    raw = math.floor((combined_hcp - 20) / 3) + 1
    return max(1, min(7, raw))


def _ltc_combined(row: pd.Series) -> Optional[float]:
    """
    Return declaring side's combined adjusted LTC.

    Uses Declarer_Side (from features.py) to pick NS_LTC_adj or ØV_LTC_adj.
    Falls back to trying both if Declarer_Side is unavailable.
    """
    side = row.get("Declarer_Side")
    if side == "NS":
        val = row.get("NS_LTC_adj")
    elif side == "ØV":
        val = row.get("ØV_LTC_adj")
    else:
        # If decl can tell us the side, derive it
        decl = row.get("decl")
        if decl in ("N", "S"):
            val = row.get("NS_LTC_adj")
        elif decl in ("Ø", "V"):
            val = row.get("ØV_LTC_adj")
        else:
            return None

    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return float(val)


def _contract_required_tricks(level) -> Optional[int]:
    if level is None:
        return None
    try:
        return 6 + int(level)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# C. Lead & defence helpers
# ---------------------------------------------------------------------------

_SUIT_SYMBOL_MAP = {
    "♠": "S",
    "♥": "H",
    "♦": "D",
    "♣": "C",
}

_SUIT_LETTER_MAP = {
    "S": "S",
    "H": "H",
    "D": "D",
    "C": "C",
}


def _extract_lead_suit(lead: object) -> str:
    """
    Extract suit from a lead string.

    Handles:
    - Suit-symbol prefix: '♠A', '♥7', '♦2', '♣K'  -> 'S', 'H', 'D', 'C'
    - ASCII letter prefix: 'SA', 'H7', 'DK', 'CQ'   -> 'S', 'H', 'D', 'C'
    - Everything else                                 -> 'ukendt'
    """
    if lead is None or (isinstance(lead, float) and math.isnan(lead)):
        return "ukendt"
    s = str(lead).strip()
    if not s:
        return "ukendt"

    first = s[0]
    if first in _SUIT_SYMBOL_MAP:
        return _SUIT_SYMBOL_MAP[first]
    if first.upper() in _SUIT_LETTER_MAP:
        return _SUIT_LETTER_MAP[first.upper()]

    return "ukendt"


def _extract_lead_card(lead: object) -> Optional[str]:
    """
    Normalize lead card to the rank part (everything after the suit prefix).

    Returns None if lead is missing.
    """
    if lead is None or (isinstance(lead, float) and math.isnan(lead)):
        return None
    s = str(lead).strip()
    if not s:
        return None

    first = s[0]
    # Strip suit symbol or letter prefix
    if first in _SUIT_SYMBOL_MAP:
        card = s[1:].strip().upper() if len(s) > 1 else ""
    elif first.upper() in _SUIT_LETTER_MAP:
        card = s[1:].strip().upper() if len(s) > 1 else ""
    else:
        card = s.upper()

    return card if card else None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def add_mvp_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add MVP analysis metrics to the result DataFrame.

    Prerequisites (columns expected to already exist):
      From scraper:
        contract, level, strain, decl, tricks, lead
        dd_valid, dd_{N|S|Ø|V}_{NT|S|H|D|C}
      From features.py (add_hand_features):
        NS_HCP, ØV_HCP, NS_LTC_adj, ØV_LTC_adj, Declarer_Side
      From phase21_reference.py (add_phase21_fields):
        pct_vs_expected (optional – computed if expected_pct present)

    New columns added
    -----------------
    A. Contract quality
      Combined_HCP, expected_level_hcp, level_gap_hcp,
      contract_aggression_hcp,
      LTC_combined, expected_tricks_ltc, contract_required_tricks,
      ltc_trick_gap, ltc_soundness_flag,
      slam_attempted, slam_hcp_ok, slam_ltc_ok

    B. Execution quality
      dd_tricks_declarer, play_precision_dd, contract_hardness_dd,
      pct_vs_expected (added if missing)

    C. Lead & defence
      lead_suit, lead_card
    """
    out = df.copy()

    # ------------------------------------------------------------------
    # Ensure pct_vs_expected is present (B.3 – already in pipeline but
    # compute defensively if it's missing and expected_pct is available)
    # ------------------------------------------------------------------
    if "pct_vs_expected" not in out.columns:
        if "pct_NS" in out.columns and "expected_pct" in out.columns:
            pct_ns = pd.to_numeric(out["pct_NS"], errors="coerce")
            exp = pd.to_numeric(out["expected_pct"], errors="coerce")
            out["pct_vs_expected"] = pct_ns - exp
        else:
            out["pct_vs_expected"] = np.nan

    # ------------------------------------------------------------------
    # A1. HCP-based contract quality
    # ------------------------------------------------------------------
    out["Combined_HCP"] = out.apply(_combined_hcp, axis=1)

    out["expected_level_hcp"] = out["Combined_HCP"].apply(_expected_level_hcp)

    level_numeric = pd.to_numeric(out.get("level", pd.Series(dtype=float)), errors="coerce")
    out["level_gap_hcp"] = level_numeric - pd.to_numeric(out["expected_level_hcp"], errors="coerce")

    def _aggression(gap):
        if gap is None or (isinstance(gap, float) and math.isnan(gap)):
            return None
        if gap >= 1:
            return "overbid"
        if gap <= -1:
            return "underbid"
        return "ok"

    out["contract_aggression_hcp"] = out["level_gap_hcp"].apply(_aggression)

    # ------------------------------------------------------------------
    # A2. LTC-based contract quality (suit contracts only)
    # ------------------------------------------------------------------
    out["LTC_combined"] = out.apply(_ltc_combined, axis=1)

    strain_series = out.get("strain", pd.Series(dtype=str))

    def _expected_tricks_ltc(row):
        strain = row.get("strain")
        if strain not in _SUIT_STRAINS:
            return None
        ltc = row.get("LTC_combined")
        if ltc is None or (isinstance(ltc, float) and math.isnan(ltc)):
            return None
        return 24.0 - ltc

    out["expected_tricks_ltc"] = out.apply(_expected_tricks_ltc, axis=1)

    out["contract_required_tricks"] = level_numeric.apply(
        lambda x: (6 + int(x)) if pd.notna(x) else None
    )

    def _ltc_trick_gap(row):
        e = row.get("expected_tricks_ltc")
        r = row.get("contract_required_tricks")
        if e is None or r is None:
            return None
        if isinstance(e, float) and math.isnan(e):
            return None
        if isinstance(r, float) and math.isnan(r):
            return None
        return float(e) - float(r)

    out["ltc_trick_gap"] = out.apply(_ltc_trick_gap, axis=1)

    def _ltc_soundness_flag(gap):
        if gap is None or (isinstance(gap, float) and math.isnan(gap)):
            return None
        return "sound" if gap >= 0 else "stretch"

    out["ltc_soundness_flag"] = out["ltc_trick_gap"].apply(_ltc_soundness_flag)

    # ------------------------------------------------------------------
    # A3. Slam flags
    # ------------------------------------------------------------------
    out["slam_attempted"] = level_numeric >= 6

    def _slam_hcp_ok(row):
        chcp = row.get("Combined_HCP")
        if chcp is None or (isinstance(chcp, float) and math.isnan(chcp)):
            return None
        return bool(chcp >= 33)

    out["slam_hcp_ok"] = out.apply(_slam_hcp_ok, axis=1)

    def _slam_ltc_ok(row):
        ltc = row.get("LTC_combined")
        if ltc is None or (isinstance(ltc, float) and math.isnan(ltc)):
            return None
        return bool(ltc <= 12)

    out["slam_ltc_ok"] = out.apply(_slam_ltc_ok, axis=1)

    # ------------------------------------------------------------------
    # B1. Trick delta vs DD
    # ------------------------------------------------------------------
    out["dd_tricks_declarer"] = out.apply(_dd_tricks_for_decl, axis=1)

    tricks_numeric = pd.to_numeric(out.get("tricks", pd.Series(dtype=float)), errors="coerce")

    def _play_precision_dd(row):
        dd = row.get("dd_tricks_declarer")
        if dd is None:
            return None
        t = row.get("tricks")
        if t is None or (isinstance(t, float) and math.isnan(t)):
            return None
        try:
            return int(t) - int(dd)
        except (TypeError, ValueError):
            return None

    out["play_precision_dd"] = out.apply(_play_precision_dd, axis=1)

    # ------------------------------------------------------------------
    # B2. Contract hardness vs DD
    # ------------------------------------------------------------------
    def _contract_hardness_dd(row):
        dd = row.get("dd_tricks_declarer")
        req = row.get("contract_required_tricks")
        if dd is None or req is None:
            return None
        if isinstance(req, float) and math.isnan(req):
            return None
        return int(dd) - int(req)

    out["contract_hardness_dd"] = out.apply(_contract_hardness_dd, axis=1)

    # ------------------------------------------------------------------
    # C. Lead & defence
    # ------------------------------------------------------------------
    lead_col = out.get("lead", pd.Series([None] * len(out)))
    out["lead_suit"] = lead_col.apply(_extract_lead_suit)
    out["lead_card"] = lead_col.apply(_extract_lead_card)

    return out
