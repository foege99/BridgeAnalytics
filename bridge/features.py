"""
bridge/features.py

Adds hand-based features (HCP/LTC/shape/controls etc.) to scraped result rows.

Expected columns in input DataFrame (from scraper.py):
- N_hand, Ø_hand, S_hand, V_hand  (dot-format S.H.D.C, may be None)
- decl (one of N/S/Ø/V)

Output:
- Individual metrics per seat: N_HCP, N_LTC_adj, N_shape, N_balanced, N_controls, N_aces, N_kings, etc.
- Side metrics: NS_HCP, ØV_HCP, NS_LTC_adj, ØV_LTC_adj, NS_controls, ØV_controls, etc.
- Contract-side metrics (based on decl): Declarer_Side, Declarer_HCP, Defense_HCP, HCP_diff,
  Declarer_LTC_adj, Defense_LTC_adj, LTC_diff, Suit_Index, NT_Index (v1)

Notes:
- LTC is meaningful primarily for suit contracts; we still compute it always.
- NT_Index v1 is set to Declarer_HCP (can be extended later).

Usage (in main.py after df_all is created):
    from bridge.features import add_hand_features
    df_all = add_hand_features(df_all)
"""

from __future__ import annotations

from typing import Optional
import pandas as pd

from bridge.hand_eval import evaluate_hand


def _safe_eval(dot_hand: object) -> dict:
    """
    Evaluate a dot-hand safely. Returns None-like defaults if missing or invalid.
    """
    if dot_hand is None or (isinstance(dot_hand, float) and pd.isna(dot_hand)):
        return {
            "hcp": None,
            "shape": None,
            "shape_shdc": None,
            "balanced": None,
            "dist_pts_shortage": None,
            "ltc_adj": None,
            "controls": None,
            "aces": None,
            "kings": None,
        }

    s = str(dot_hand).strip()
    if not s or s == "None":
        return {
            "hcp": None,
            "shape": None,
            "shape_shdc": None,
            "balanced": None,
            "dist_pts_shortage": None,
            "ltc_adj": None,
            "controls": None,
            "aces": None,
            "kings": None,
        }

    try:
        out = evaluate_hand(s)
        return {
            "hcp": out.get("hcp"),
            "shape": out.get("shape"),
            "shape_shdc": out.get("shape_shdc"),
            "balanced": out.get("balanced"),
            "dist_pts_shortage": out.get("dist_pts_shortage"),
            "ltc_adj": out.get("ltc_adj"),
            "controls": out.get("controls"),
            "aces": out.get("aces"),
            "kings": out.get("kings"),
        }
    except Exception:
        return {
            "hcp": None,
            "shape": None,
            "shape_shdc": None,
            "balanced": None,
            "dist_pts_shortage": None,
            "ltc_adj": None,
            "controls": None,
            "aces": None,
            "kings": None,
        }


def _seat_side(seat: str) -> str:
    """
    Map seat to side.
    N/S -> 'NS'
    Ø/V -> 'ØV'
    """
    return "NS" if seat in ("N", "S") else "ØV"


def add_hand_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds hand and derived features to df.
    Returns a copy (does not mutate input).
    """
    out = df.copy()

    # --- Individual seat metrics ---
    seat_map = {
        "N": "N_hand",
        "S": "S_hand",
        "Ø": "Ø_hand",
        "V": "V_hand",
    }

    for seat, col in seat_map.items():
        evals = out[col].apply(_safe_eval)

        out[f"{seat}_HCP"] = evals.apply(lambda d: d["hcp"])
        out[f"{seat}_shape"] = evals.apply(lambda d: d["shape"])
        out[f"{seat}_shape_SHDC"] = evals.apply(lambda d: d["shape_shdc"])
        out[f"{seat}_balanced"] = evals.apply(lambda d: d["balanced"])
        out[f"{seat}_dist_pts_shortage"] = evals.apply(lambda d: d["dist_pts_shortage"])
        out[f"{seat}_LTC_adj"] = evals.apply(lambda d: d["ltc_adj"])
        out[f"{seat}_controls"] = evals.apply(lambda d: d["controls"])
        out[f"{seat}_aces"] = evals.apply(lambda d: d["aces"])
        out[f"{seat}_kings"] = evals.apply(lambda d: d["kings"])

    # --- Side totals (NS and ØV) ---
    def _sum2(a, b):
        if a is None or b is None:
            return None
        if (isinstance(a, float) and pd.isna(a)) or (isinstance(b, float) and pd.isna(b)):
            return None
        return float(a) + float(b)

    out["NS_HCP"] = out.apply(lambda r: _sum2(r["N_HCP"], r["S_HCP"]), axis=1)
    out["ØV_HCP"] = out.apply(lambda r: _sum2(r["Ø_HCP"], r["V_HCP"]), axis=1)

    out["NS_LTC_adj"] = out.apply(lambda r: _sum2(r["N_LTC_adj"], r["S_LTC_adj"]), axis=1)
    out["ØV_LTC_adj"] = out.apply(lambda r: _sum2(r["Ø_LTC_adj"], r["V_LTC_adj"]), axis=1)

    out["NS_controls"] = out.apply(lambda r: _sum2(r["N_controls"], r["S_controls"]), axis=1)
    out["ØV_controls"] = out.apply(lambda r: _sum2(r["Ø_controls"], r["V_controls"]), axis=1)

    out["NS_aces"] = out.apply(lambda r: _sum2(r["N_aces"], r["S_aces"]), axis=1)
    out["ØV_aces"] = out.apply(lambda r: _sum2(r["Ø_aces"], r["V_aces"]), axis=1)

    out["NS_kings"] = out.apply(lambda r: _sum2(r["N_kings"], r["S_kings"]), axis=1)
    out["ØV_kings"] = out.apply(lambda r: _sum2(r["Ø_kings"], r["V_kings"]), axis=1)

    # --- Declarer/Defense side derived metrics ---
    def _decl_side(decl: object) -> Optional[str]:
        if decl is None or (isinstance(decl, float) and pd.isna(decl)):
            return None
        d = str(decl).strip()
        if d not in ("N", "S", "Ø", "V"):
            return None
        return _seat_side(d)

    out["Declarer_Side"] = out["decl"].apply(_decl_side)

    def _pick_side(row, side: str, metric: str):
        if side == "NS":
            return row.get(f"NS_{metric}")
        if side == "ØV":
            return row.get(f"ØV_{metric}")
        return None

    def _other_side(side: Optional[str]) -> Optional[str]:
        if side == "NS":
            return "ØV"
        if side == "ØV":
            return "NS"
        return None

    def _calc_row(row):
        ds = row.get("Declarer_Side")
        os = _other_side(ds) if ds else None

        decl_hcp = _pick_side(row, ds, "HCP") if ds else None
        def_hcp = _pick_side(row, os, "HCP") if os else None

        decl_ltc = _pick_side(row, ds, "LTC_adj") if ds else None
        def_ltc = _pick_side(row, os, "LTC_adj") if os else None

        hcp_diff = (decl_hcp - def_hcp) if (decl_hcp is not None and def_hcp is not None) else None
        ltc_diff = (def_ltc - decl_ltc) if (decl_ltc is not None and def_ltc is not None) else None

        suit_index = (24.0 - decl_ltc) if (decl_ltc is not None) else None
        nt_index = decl_hcp  # v1

        return pd.Series({
            "Declarer_HCP": decl_hcp,
            "Defense_HCP": def_hcp,
            "HCP_diff": hcp_diff,

            "Declarer_LTC_adj": decl_ltc,
            "Defense_LTC_adj": def_ltc,
            "LTC_diff": ltc_diff,

            "Suit_Index": suit_index,
            "NT_Index": nt_index,
        })

    derived = out.apply(_calc_row, axis=1)
    out = pd.concat([out, derived], axis=1)

    return out
