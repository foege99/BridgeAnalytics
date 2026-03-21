"""
bridge/hole_analysis.py  –  Hulanalyse (Gap Analysis) for Henrik Friis & Per Føge Jensen

Analyserer i ALLE turneringer H+P har spillet, hvad der sker med:

  Zone 1 – Partscore      (delkontrakt)
  Zone 2 – 3NT            (udgang NT)
  Zone 3 – Game Major     (4♥ / 4♠)
  Zone 4 – Game Minor     (5♦ / 5♣)
  Zone 5 – 5 Major        (5♥ / 5♠  – sjældent korrekt)
  Zone 6 – Lilleslem      (6x)
  Zone 7 – Storeslem      (7x)

For hvert board sammenlignes:
  a) Hvad har H+P meldt?
  b) Hvad har resten af feltet meldt (field_mode_contract fra Phase 2.1)?
  c) Hvad siger Double-Dummy (Endplay)?
  d) Hvad er H+P's HCP, LTC, fordelingspoint?

Rapporter:
  zone_summary          – zoneopdelt overblik med avg pct / HCP / LTC
  zone_vs_field         – kryds-tabel: H+P zone vs felt zone
  hcp_profile           – HCP/LTC profil pr zone
  aggression_summary    – over/undermeld rater vs felt og DD
  game_misses           – boards H+P overseer udgang (feltet spiller udgang)
  slam_misses           – boards H+P overseer slem (felt eller DD har slem)
  slam_attempts         – alle slambud med HCP/LTC kontekst
  nt_vs_minor_slam      – spiller 3NT, men DD viser minor-slem tilgængeligt
  overbids              – H+P over DD-maks (overmelder)
  five_major            – 5-major boards (oftest fejlmeldt)

Kræver at pipelinen har kørt:
  add_hand_features()  → NS_HCP, NS_LTC_adj, N_dist_pts_shortage etc.
  add_phase21_fields() → field_mode_contract, top2_contract_1/2
  add_mvp_metrics()    → dd_tricks_declarer, slam_hcp_ok, slam_ltc_ok,
                         contract_required_tricks, play_precision_dd
  scraper              → level, strain, contract, decl, tricks,
                         dd_valid, dd_{N|S|Ø|V}_{NT|S|H|D|C},
                         par_contract, par_side
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

HENRIK = "Henrik Friis"
PER = "Per Føge Jensen"

# ─────────────────────────────────────────────────────────────────────────────
# Contract zone definitions
# ─────────────────────────────────────────────────────────────────────────────

ZONE_ORDER = [
    "Partscore",
    "3NT",
    "Game_Major",
    "Game_Minor",
    "5_Major",
    "Lilleslem",
    "Storeslem",
]

ZONE_LABELS_DK = {
    "Partscore":  "Delkontrakt",
    "3NT":        "3 NT (udgang)",
    "Game_Major": "Udgang Major (4H/4S)",
    "Game_Minor": "Udgang Minor (5K/5R)",
    "5_Major":    "5 Major (overkøb?)",
    "Lilleslem":  "Lilleslem (6x)",
    "Storeslem":  "Storeslem (7x)",
    "Ukendt":     "Ukendt",
    "All":        "Alle kontrakter",
}

# Map Unicode suit characters to internal strain codes used in dd_ columns
_UNICODE_TO_STRAIN = {
    "♠": "S",
    "♥": "H",
    "♦": "D",
    "♣": "C",
}

_KNOWN_STRAINS = {"NT", "SA", "S", "H", "D", "C"}


def classify_zone(level, strain) -> str:
    """
    Map (level, strain) → zone string.

    Strain may be: "NT", "S", "H", "D", "C", or Unicode "♠♥♦♣".
    """
    try:
        lv = int(level)
    except (TypeError, ValueError):
        return "Ukendt"

    if lv < 1 or lv > 7:
        return "Ukendt"

    st = str(strain).strip() if strain else ""
    # Normalise Unicode
    st = _UNICODE_TO_STRAIN.get(st, st).upper()
    # SA is Danish for NT
    if st in ("SA", "NO", ""):
        st = "NT"

    if lv == 7:
        return "Storeslem"
    if lv == 6:
        return "Lilleslem"
    if lv == 5 and st in {"H", "S"}:
        return "5_Major"
    if lv == 5 and st in {"D", "C"}:
        return "Game_Minor"
    if lv == 4 and st in {"H", "S"}:
        return "Game_Major"
    if lv == 3 and st == "NT":
        return "3NT"
    return "Partscore"


def _parse_contract_str(c: object) -> tuple[Optional[int], Optional[str]]:
    """
    Parse a contract string like "4♥", "3NT", "6♣X" → (level, strain).

    Returns (None, None) on failure.
    """
    if c is None or (isinstance(c, float) and math.isnan(c)):
        return None, None
    s = str(c).strip()
    # Strip doubles
    s = s.replace("XX", "").replace("X", "").strip()
    if len(s) < 2:
        return None, None
    try:
        lv = int(s[0])
    except ValueError:
        return None, None
    st_raw = s[1:].upper().strip()
    st = _UNICODE_TO_STRAIN.get(st_raw, st_raw)
    if st in ("SA", "NO"):
        st = "NT"
    return lv, st


# ─────────────────────────────────────────────────────────────────────────────
# Pair-side helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pair_side(row) -> Optional[str]:
    """Return 'NS' or 'ØV' depending on which side Henrik+Per sit."""
    if HENRIK in (row.get("ns1"), row.get("ns2")):
        return "NS"
    if HENRIK in (row.get("ew1"), row.get("ew2")):
        return "ØV"
    return None


def _pair_pct(row) -> Optional[float]:
    side = _pair_side(row)
    if side == "NS":
        v = row.get("pct_NS")
    elif side == "ØV":
        v = row.get("pct_ØV")
    else:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pair_hcp(row) -> Optional[float]:
    """HCP of the pair's side (N+S or Ø+V)."""
    side = _pair_side(row)
    if side == "NS":
        v = row.get("NS_HCP")
    elif side == "ØV":
        v = row.get("ØV_HCP")
    else:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pair_ltc(row) -> Optional[float]:
    """Adjusted LTC of the pair's side."""
    side = _pair_side(row)
    if side == "NS":
        v = row.get("NS_LTC_adj")
    elif side == "ØV":
        v = row.get("ØV_LTC_adj")
    else:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pair_dist_pts(row) -> Optional[float]:
    """Distribution points (shortage) of the pair's side – sum of 2 hands."""
    side = _pair_side(row)
    if side == "NS":
        seats = ("N", "S")
    elif side == "ØV":
        seats = ("Ø", "V")
    else:
        return None
    total = 0.0
    for seat in seats:
        v = row.get(f"{seat}_dist_pts_shortage")
        try:
            total += float(v)
        except (TypeError, ValueError):
            return None
    return total


def _pair_controls(row) -> Optional[float]:
    """Controls (A=2, K=1) of the pair's side – sum of 2 hands."""
    side = _pair_side(row)
    if side == "NS":
        seats = ("N", "S")
    elif side == "ØV":
        seats = ("Ø", "V")
    else:
        return None
    total = 0.0
    for seat in seats:
        v = row.get(f"{seat}_controls")
        try:
            total += float(v)
        except (TypeError, ValueError):
            return None
    return total


# ─────────────────────────────────────────────────────────────────────────────
# Filter
# ─────────────────────────────────────────────────────────────────────────────

def filter_pair_boards(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows where both Henrik and Per appear at the table."""
    names = {HENRIK, PER}
    mask = df.apply(
        lambda r: names.issubset(
            {r.get("ns1"), r.get("ns2"), r.get("ew1"), r.get("ew2")}
        ),
        axis=1,
    )
    return df[mask].copy()


def _is_played(row) -> bool:
    code = row.get("result_status_code", "PLAYED")
    return code in ("PLAYED", None, "")


# ─────────────────────────────────────────────────────────────────────────────
# DD best zone for a given side
# ─────────────────────────────────────────────────────────────────────────────

def _dd_best_zone_for_side(row, side: str) -> Optional[str]:
    """
    Inspect the full DD table and return the best *makeable* zone for the side.

    "Best" = highest zone in ZONE_ORDER that is achievable by at least one
    declarer from that side in at least one strain.

    Returns None when dd_valid is False/missing.
    """
    if not row.get("dd_valid", False):
        return None

    decls = ["N", "S"] if side == "NS" else ["Ø", "V"]
    best_rank = -1
    best_zone = None

    for decl in decls:
        for strain in ["NT", "S", "H", "D", "C"]:
            col = f"dd_{decl}_{strain}"
            val = row.get(col)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                continue
            try:
                tricks = int(val)
            except (TypeError, ValueError):
                continue
            level = tricks - 6
            if level < 1:
                continue
            zone = classify_zone(level, strain)
            if zone in ZONE_ORDER:
                rank = ZONE_ORDER.index(zone)
                if rank > best_rank:
                    best_rank = rank
                    best_zone = zone

    return best_zone


def _dd_max_tricks_minor_for_side(row, side: str) -> Optional[int]:
    """Max tricks in any minor suit for the given side."""
    if not row.get("dd_valid", False):
        return None
    decls = ["N", "S"] if side == "NS" else ["Ø", "V"]
    best = None
    for decl in decls:
        for ms in ("D", "C"):
            col = f"dd_{decl}_{ms}"
            val = row.get(col)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                continue
            try:
                t = int(val)
                if best is None or t > best:
                    best = t
            except (TypeError, ValueError):
                pass
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Feature enrichment
# ─────────────────────────────────────────────────────────────────────────────

def add_hole_analysis_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds hole-analysis columns to a *pair-filtered* DataFrame.

    New columns
    -----------
    pair_side          : 'NS' or 'ØV'
    pair_pct           : H+P's matchpoint percentage
    pair_hcp           : combined HCP of H+P's side
    pair_ltc           : combined adjusted LTC of H+P's side
    pair_dist_pts      : combined distribution/shortage points of H+P's side
    pair_controls      : combined controls (A=2, K=1) of H+P's side
    pair_zone          : contract zone H+P is in
    field_zone         : zone of field_mode_contract (from Phase 2.1)
    dd_best_zone       : best makeable zone for H+P's side from DD
    zone_vs_field      : underbid / ok / overbid vs field zone
    zone_vs_dd         : underbid / ok / overbid vs DD best zone
    is_game_miss       : True when field is in game and H+P are in partscore
    is_slam_miss       : True when field or DD has slam and H+P are below slam
    is_overcontract    : True when H+P's zone is above their DD maximum
    nt_instead_of_minor_slam : plays 3NT but DD shows minor slam available
    five_major_avoidable: plays 5M but DD maximum is only 4M
    dd_minor_max_tricks: max tricks available in minor suits for H+P's side
    """
    out = df.copy()

    # --- Core pair metrics ---
    out["pair_side"]     = out.apply(_pair_side,     axis=1)
    out["pair_pct"]      = out.apply(_pair_pct,      axis=1)
    out["pair_hcp"]      = out.apply(_pair_hcp,      axis=1)
    out["pair_ltc"]      = out.apply(_pair_ltc,      axis=1)
    out["pair_dist_pts"] = out.apply(_pair_dist_pts, axis=1)
    out["pair_controls"] = out.apply(_pair_controls, axis=1)

    # --- Contract zone for H+P ---
    out["pair_zone"] = out.apply(
        lambda r: classify_zone(r.get("level"), r.get("strain")), axis=1
    )

    # --- Field zone from phase21 field_mode_contract ---
    def _field_zone(c):
        lv, st = _parse_contract_str(c)
        if lv is None:
            return None
        return classify_zone(lv, st)

    if "field_mode_contract" in out.columns:
        out["field_zone"] = out["field_mode_contract"].apply(_field_zone)
    else:
        out["field_zone"] = None

    # --- DD best zone for H+P's side ---
    out["dd_best_zone"] = out.apply(
        lambda r: _dd_best_zone_for_side(r, r.get("pair_side") or "NS"), axis=1
    )

    # --- DD max tricks in minor for H+P's side ---
    out["dd_minor_max_tricks"] = out.apply(
        lambda r: _dd_max_tricks_minor_for_side(r, r.get("pair_side") or "NS"), axis=1
    )

    # --- zone_vs_field and zone_vs_dd ---
    def _zone_gap(pair_z, ref_z) -> Optional[str]:
        if not pair_z or not ref_z:
            return None
        if pair_z not in ZONE_ORDER or ref_z not in ZONE_ORDER:
            return None
        d = ZONE_ORDER.index(pair_z) - ZONE_ORDER.index(ref_z)
        if d < 0:
            return "underbid"
        if d > 0:
            return "overbid"
        return "ok"

    out["zone_vs_field"] = out.apply(
        lambda r: _zone_gap(r.get("pair_zone"), r.get("field_zone")), axis=1
    )
    out["zone_vs_dd"] = out.apply(
        lambda r: _zone_gap(r.get("pair_zone"), r.get("dd_best_zone")), axis=1
    )

    # --- Binary diagnosis flags ---

    def _is_game_miss(r) -> bool:
        pz = r.get("pair_zone")
        fz = r.get("field_zone")
        return (
            pz == "Partscore"
            and fz in {"3NT", "Game_Major", "Game_Minor"}
        )

    def _is_slam_miss(r) -> bool:
        pz = r.get("pair_zone")
        if pz in {"Lilleslem", "Storeslem"}:
            return False
        fz = r.get("field_zone")
        ddz = r.get("dd_best_zone")
        return (
            (fz in {"Lilleslem", "Storeslem"} if fz else False)
            or (ddz in {"Lilleslem", "Storeslem"} if ddz else False)
        )

    def _is_overcontract(r) -> bool:
        pz = r.get("pair_zone")
        ddz = r.get("dd_best_zone")
        if not pz or not ddz:
            return False
        if pz not in ZONE_ORDER or ddz not in ZONE_ORDER:
            return False
        return ZONE_ORDER.index(pz) > ZONE_ORDER.index(ddz)

    def _nt_instead_of_minor_slam(r) -> bool:
        """Plays 3NT while DD shows minor slam (12+ tricks in D or C) for their side."""
        if r.get("pair_zone") != "3NT":
            return False
        mt = r.get("dd_minor_max_tricks")
        return mt is not None and mt >= 12

    def _five_major_avoidable(r) -> bool:
        """Plays 5M while DD maximum is only 4M level or lower for their side (avoidable)."""
        if r.get("pair_zone") != "5_Major":
            return False
        ddz = r.get("dd_best_zone")
        if not ddz or ddz not in ZONE_ORDER:
            return False
        return ZONE_ORDER.index(ddz) <= ZONE_ORDER.index("Game_Major")

    out["is_game_miss"]              = out.apply(_is_game_miss,              axis=1)
    out["is_slam_miss"]              = out.apply(_is_slam_miss,              axis=1)
    out["is_overcontract"]           = out.apply(_is_overcontract,           axis=1)
    out["nt_instead_of_minor_slam"]  = out.apply(_nt_instead_of_minor_slam,  axis=1)
    out["five_major_avoidable"]      = out.apply(_five_major_avoidable,      axis=1)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Helpers shared across reports
# ─────────────────────────────────────────────────────────────────────────────

def _played_mask(df: pd.DataFrame) -> pd.Series:
    return df.apply(_is_played, axis=1)


def _zone_label(zone: str) -> str:
    return ZONE_LABELS_DK.get(zone, zone)


def _round_or_none(v, decimals: int = 1):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return round(f, decimals)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Report 1 – Zone Summary
# ─────────────────────────────────────────────────────────────────────────────

def make_zone_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Zoneopdelt overblik:
    zone, Zone_DK, Boards, Avg_pct, Avg_HCP, Avg_LTC, Avg_dist_pts,
    Making_pct (andel kontrakter der bliver gjort),
    Avg_vs_field (gennemsnitlig pct-afvigelse vs felt).
    """
    played = df[_played_mask(df)].copy()
    rows = []

    for zone in ZONE_ORDER:
        sub = played[played["pair_zone"] == zone]
        n = len(sub)
        if n == 0:
            continue

        pct     = pd.to_numeric(sub["pair_pct"],      errors="coerce")
        hcp     = pd.to_numeric(sub["pair_hcp"],      errors="coerce")
        ltc     = pd.to_numeric(sub["pair_ltc"],      errors="coerce")
        dist    = pd.to_numeric(sub["pair_dist_pts"], errors="coerce")
        ctrl    = pd.to_numeric(sub["pair_controls"], errors="coerce")

        # Making rate
        if "tricks" in sub.columns and "contract_required_tricks" in sub.columns:
            tricks_n = pd.to_numeric(sub["tricks"], errors="coerce")
            req_n    = pd.to_numeric(sub["contract_required_tricks"], errors="coerce")
            valid    = tricks_n.notna() & req_n.notna()
            making   = (tricks_n[valid] >= req_n[valid]).sum()
            making_n = valid.sum()
            making_pct = making / making_n * 100 if making_n > 0 else np.nan
        else:
            making_pct = np.nan

        # Average pct deviation vs field
        if "pct_vs_expected" in sub.columns:
            pvs = pd.to_numeric(sub["pct_vs_expected"], errors="coerce")
            avg_vs_field = pvs.mean()
        else:
            avg_vs_field = np.nan

        rows.append({
            "Zone":          zone,
            "Zone_DK":       _zone_label(zone),
            "Boards":        n,
            "Avg_pct":       _round_or_none(pct.mean()),
            "Avg_HCP":       _round_or_none(hcp.mean()),
            "Avg_LTC":       _round_or_none(ltc.mean()),
            "Avg_dist_pts":  _round_or_none(dist.mean()),
            "Avg_controls":  _round_or_none(ctrl.mean()),
            "Making_pct":    _round_or_none(making_pct),
            "Avg_pct_vs_felt": _round_or_none(avg_vs_field),
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Report 2 – Zone vs Field cross-tab
# ─────────────────────────────────────────────────────────────────────────────

def make_zone_vs_field(df: pd.DataFrame) -> pd.DataFrame:
    """
    Kryds-tabel: H+P's zone (rækker) vs feltets zone (kolonner).

    Viser antal boards og gennemsnitlig pct for H+P i hvert kombinationsfelt.
    Inkl. opsummerings-diagonal: 'ok', 'underbid', 'overbid'.
    """
    played = df[
        _played_mask(df)
        & df["field_zone"].notna()
        & df["pair_zone"].notna()
    ].copy()

    if played.empty:
        return pd.DataFrame()

    rows = []
    for pair_z in ZONE_ORDER:
        for field_z in ZONE_ORDER:
            sub = played[
                (played["pair_zone"] == pair_z)
                & (played["field_zone"] == field_z)
            ]
            n = len(sub)
            if n == 0:
                continue
            avg_pct = pd.to_numeric(sub["pair_pct"], errors="coerce").mean()
            avg_hcp = pd.to_numeric(sub["pair_hcp"], errors="coerce").mean()
            rows.append({
                "H+P_Zone":       pair_z,
                "H+P_Zone_DK":    _zone_label(pair_z),
                "Felt_Zone":      field_z,
                "Felt_Zone_DK":   _zone_label(field_z),
                "Boards":         n,
                "Avg_pair_pct":   _round_or_none(avg_pct),
                "Avg_HCP":        _round_or_none(avg_hcp),
                "Resultat":       (
                    "ok" if pair_z == field_z
                    else ("undermeld" if ZONE_ORDER.index(pair_z) < ZONE_ORDER.index(field_z)
                          else "overmeld")
                ),
            })

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["Felt_Zone", "H+P_Zone"])
        .reset_index(drop=True)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Report 3 – HCP / LTC profile per zone
# ─────────────────────────────────────────────────────────────────────────────

def make_hcp_profile_by_zone(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per zone: HCP og LTC statistik (min, p25, median, mean, p75, max).
    Belyser hvad H+P typisk har af HP/LTC i de enkelte niveauer.
    """
    played = df[_played_mask(df)].copy()
    rows = []

    for zone in ZONE_ORDER:
        sub = played[played["pair_zone"] == zone]
        n = len(sub)
        if n == 0:
            continue

        hcp  = pd.to_numeric(sub["pair_hcp"],      errors="coerce").dropna()
        ltc  = pd.to_numeric(sub["pair_ltc"],      errors="coerce").dropna()
        dist = pd.to_numeric(sub["pair_dist_pts"], errors="coerce").dropna()
        ctrl = pd.to_numeric(sub["pair_controls"], errors="coerce").dropna()

        row: dict = {
            "Zone":    zone,
            "Zone_DK": _zone_label(zone),
            "Boards":  n,
        }

        if len(hcp) > 0:
            row.update({
                "HCP_min":    int(hcp.min()),
                "HCP_p25":    _round_or_none(hcp.quantile(0.25)),
                "HCP_median": _round_or_none(hcp.median()),
                "HCP_mean":   _round_or_none(hcp.mean()),
                "HCP_p75":    _round_or_none(hcp.quantile(0.75)),
                "HCP_max":    int(hcp.max()),
            })

        if len(ltc) > 0:
            row.update({
                "LTC_min":    _round_or_none(ltc.min()),
                "LTC_p25":    _round_or_none(ltc.quantile(0.25)),
                "LTC_median": _round_or_none(ltc.median()),
                "LTC_mean":   _round_or_none(ltc.mean()),
                "LTC_p75":    _round_or_none(ltc.quantile(0.75)),
                "LTC_max":    _round_or_none(ltc.max()),
            })

        if len(dist) > 0:
            row.update({
                "Dist_pts_mean":   _round_or_none(dist.mean()),
                "Dist_pts_median": _round_or_none(dist.median()),
            })

        if len(ctrl) > 0:
            row.update({
                "Controls_mean":   _round_or_none(ctrl.mean()),
                "Controls_median": _round_or_none(ctrl.median()),
            })

        rows.append(row)

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Report 4 – Aggression summary (over/undermeld rater)
# ─────────────────────────────────────────────────────────────────────────────

def make_zone_aggression_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Opsummering pr zone af under/ok/overmeld rater mod felt (Phase 2.1) og DD.

    Kolonner:
      Zone, Boards,
      vs_Felt_under_pct, vs_Felt_ok_pct, vs_Felt_over_pct,
      vs_DD_under_pct,   vs_DD_ok_pct,   vs_DD_over_pct,
      N_game_misses, N_slam_misses, N_overcontracts
    """
    played = df[_played_mask(df)].copy()
    rows = []

    for zone in ZONE_ORDER + ["All"]:
        if zone == "All":
            sub = played
        else:
            sub = played[played["pair_zone"] == zone]
        n = len(sub)
        if n == 0:
            continue

        def _pct_val(col: str, val: str) -> Optional[float]:
            if col not in sub.columns:
                return None
            s = sub[col].dropna()
            if len(s) == 0:
                return None
            return _round_or_none((s == val).sum() / len(s) * 100)

        rows.append({
            "Zone":               zone,
            "Zone_DK":            _zone_label(zone),
            "Boards":             n,
            "vs_Felt_under_pct":  _pct_val("zone_vs_field", "underbid"),
            "vs_Felt_ok_pct":     _pct_val("zone_vs_field", "ok"),
            "vs_Felt_over_pct":   _pct_val("zone_vs_field", "overbid"),
            "vs_DD_under_pct":    _pct_val("zone_vs_dd",    "underbid"),
            "vs_DD_ok_pct":       _pct_val("zone_vs_dd",    "ok"),
            "vs_DD_over_pct":     _pct_val("zone_vs_dd",    "overbid"),
            "N_game_misses":      int(sub.get("is_game_miss",    pd.Series(dtype=bool)).astype(bool).sum()),
            "N_slam_misses":      int(sub.get("is_slam_miss",    pd.Series(dtype=bool)).astype(bool).sum()),
            "N_overcontracts":    int(sub.get("is_overcontract", pd.Series(dtype=bool)).astype(bool).sum()),
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Common column lists for detail reports
# ─────────────────────────────────────────────────────────────────────────────

_BASE_COLS = [
    "tournament_date", "board", "section",
    "contract", "decl",
    "pair_side", "pair_pct", "pair_hcp", "pair_ltc", "pair_dist_pts",
]

_FIELD_COLS = [
    "field_zone", "field_mode_contract", "top2_contract_1", "top2_contract_2",
]

_DD_COLS = [
    "dd_best_zone", "dd_tricks_declarer", "play_precision_dd",
]

_SLAM_EXTRA = [
    "NS_HCP", "ØV_HCP",
    "slam_hcp_ok", "slam_ltc_ok",
    "ltc_soundness_flag",
    "par_contract", "par_side",
]


def _keep(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    available = [c for c in cols if c in df.columns]
    return df[available].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Report 5 – Game misses
# ─────────────────────────────────────────────────────────────────────────────

def make_game_miss_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Boards hvor H+P spiller delkontrakt mens feltet er i udgang (3NT/4M/5m).
    Viser HCP/LTC kontekst – er det fordi de har for lidt, eller er de gået glip?
    """
    sub = df[df.get("is_game_miss", pd.Series(False, index=df.index)).astype(bool)].copy()
    if sub.empty:
        return pd.DataFrame()

    cols = (
        _BASE_COLS
        + ["pair_zone", "pair_controls"]
        + _FIELD_COLS
        + _DD_COLS
        + ["tricks", "contract_required_tricks", "spil_url"]
    )
    return _keep(sub.sort_values("pair_pct"), cols)


# ─────────────────────────────────────────────────────────────────────────────
# Report 6 – Slam misses
# ─────────────────────────────────────────────────────────────────────────────

def make_slam_miss_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Boards hvor H+P overser slem:
    - feltet er i 6x/7x, ELLER
    - DD's maks for H+P's side er slem.

    Viser HCP, LTC, kontroller til diagnosticering.
    """
    sub = df[df.get("is_slam_miss", pd.Series(False, index=df.index)).astype(bool)].copy()
    if sub.empty:
        return pd.DataFrame()

    cols = (
        _BASE_COLS
        + ["pair_zone", "pair_controls"]
        + _FIELD_COLS
        + _DD_COLS
        + _SLAM_EXTRA
        + ["spil_url"]
    )
    return _keep(sub.sort_values("pair_pct"), cols)


# ─────────────────────────────────────────────────────────────────────────────
# Report 7 – Slam attempts (alle slem-bud med kontekst)
# ─────────────────────────────────────────────────────────────────────────────

def make_slam_attempts_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Alle boards H+P byder lilleslem eller storeslem.
    Viser om HCP/LTC holder vand samt DD og feltresultat.
    """
    sub = df[df.get("pair_zone", pd.Series(dtype=str)).isin({"Lilleslem", "Storeslem"})].copy()
    if sub.empty:
        return pd.DataFrame()

    cols = (
        _BASE_COLS
        + ["pair_zone", "pair_controls"]
        + _FIELD_COLS
        + _DD_COLS
        + _SLAM_EXTRA
        + ["tricks", "contract_required_tricks", "spil_url"]
    )
    return _keep(sub.sort_values("tournament_date"), cols)


# ─────────────────────────────────────────────────────────────────────────────
# Report 8 – 3NT i stedet for minor-slem (system-hul)
# ─────────────────────────────────────────────────────────────────────────────

def make_nt_vs_minor_slam_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Systemhul: H+P spiller 3NT, men DD viser at minor-slem (6♦/6♣) var
    til stede for deres side (12+ tricks i diamond eller clubs).

    Hvad var HCP og LTC? Overser de minor-slem systematisk?
    """
    flag = "nt_instead_of_minor_slam"
    sub = df[df.get(flag, pd.Series(False, index=df.index)).astype(bool)].copy()
    if sub.empty:
        return pd.DataFrame()

    # Include DD tricks for minors so we can see how many tricks were available
    minor_dd_cols = []
    for decl in ("N", "S", "Ø", "V"):
        for ms in ("D", "C"):
            col = f"dd_{decl}_{ms}"
            if col in df.columns:
                minor_dd_cols.append(col)

    cols = (
        _BASE_COLS
        + ["pair_controls"]
        + _FIELD_COLS
        + ["dd_best_zone", "dd_minor_max_tricks"]
        + _SLAM_EXTRA
        + minor_dd_cols
        + ["spil_url"]
    )
    return _keep(sub, cols)


# ─────────────────────────────────────────────────────────────────────────────
# Report 9 – Overbids (H+P over DD-maks)
# ─────────────────────────────────────────────────────────────────────────────

def make_overbid_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Boards hvor H+P melder højere end hvad DD viser er muligt for deres side.
    Overbids resulterer typisk i very low pct – se mønstre.
    """
    sub = df[df.get("is_overcontract", pd.Series(False, index=df.index)).astype(bool)].copy()
    if sub.empty:
        return pd.DataFrame()

    cols = (
        _BASE_COLS
        + ["pair_zone"]
        + _FIELD_COLS
        + ["dd_best_zone", "dd_tricks_declarer", "play_precision_dd",
           "tricks", "contract_required_tricks",
           "ltc_soundness_flag", "contract_aggression_hcp"]
        + ["spil_url"]
    )
    return _keep(sub.sort_values("pair_pct"), cols)


# ─────────────────────────────────────────────────────────────────────────────
# Report 10 – 5 Major boards
# ─────────────────────────────────────────────────────────────────────────────

def make_five_major_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Alle boards H+P spiller 5-major (5♥/5♠).

    5-Major er næsten altid enten:
    - Et fejlmeldt spil (man skulle have stoppet i 4M eller forsøgt slem)
    - Konkurrencebud (modstander forcement til 5)
    - Sjældent korrekt som frivilligt niveau

    Columns: flag om det er 'avoidable' (DD max var kun 4M), og om det gik.
    """
    sub = df[df.get("pair_zone", pd.Series(dtype=str)) == "5_Major"].copy()
    if sub.empty:
        return pd.DataFrame()

    cols = (
        _BASE_COLS
        + _FIELD_COLS
        + ["dd_best_zone", "dd_tricks_declarer", "play_precision_dd",
           "tricks", "contract_required_tricks",
           "five_major_avoidable"]
        + ["spil_url"]
    )
    return _keep(sub, cols)


# ─────────────────────────────────────────────────────────────────────────────
# Report 11 – HCP-zone skævhed (sammenligning til felt med 5-HP-bånd)
# ─────────────────────────────────────────────────────────────────────────────

def make_hcp_zone_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """
    For hvert HCP-interval (bånd á 3 HCP) viser, hvilken zone H+P typisk spiller
    og hvad feltet typisk spiller. Belyser systematiske under/overmeld i HP-bands.

    HCP bands: <20, 20-22, 23-25, 26-28, 29-32, 33-35, 36+
    """
    played = df[_played_mask(df)].copy()
    if played.empty:
        return pd.DataFrame()

    hcp_bands = [
        ("<20",   0,  19),
        ("20-22", 20, 22),
        ("23-25", 23, 25),
        ("26-28", 26, 28),
        ("29-32", 29, 32),
        ("33-35", 33, 35),
        ("36+",   36, 40),
    ]

    rows = []
    for label, lo, hi in hcp_bands:
        hcp_s = pd.to_numeric(played["pair_hcp"], errors="coerce")
        sub = played[(hcp_s >= lo) & (hcp_s <= hi)]
        n = len(sub)
        if n == 0:
            continue

        pair_zone_vc  = sub["pair_zone"].value_counts()
        field_zone_vc = (
            sub["field_zone"].value_counts()
            if "field_zone" in sub.columns
            else pd.Series(dtype=int)
        )
        avg_pct = pd.to_numeric(sub["pair_pct"], errors="coerce").mean()

        row: dict = {
            "HCP_band":        label,
            "Boards":          n,
            "Avg_pct":         _round_or_none(avg_pct),
            "H+P_top_zone":    pair_zone_vc.idxmax() if len(pair_zone_vc) > 0 else None,
            "H+P_pct_top":     _round_or_none(pair_zone_vc.max() / n * 100) if len(pair_zone_vc) > 0 else None,
            "Felt_top_zone":   field_zone_vc.idxmax() if len(field_zone_vc) > 0 else None,
            "Felt_pct_top":    _round_or_none(field_zone_vc.max() / n * 100) if len(field_zone_vc) > 0 else None,
        }
        # Add per-zone counts
        for zone in ZONE_ORDER:
            row[f"H+P_{zone}"]   = int(pair_zone_vc.get(zone, 0))
            row[f"Felt_{zone}"]  = int(field_zone_vc.get(zone, 0))
        rows.append(row)

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Report 12 – Slam-kvalitet (HCP/LTC ved slem vs andelen der lykkes)
# ─────────────────────────────────────────────────────────────────────────────

def make_slam_quality_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyse af alle slembud:
    - Hvornår byder H+P slem (HCP/LTC niveau)?
    - Hvornår lykkes slemnene?
    - Sammenlign med felt og DD.

    Viser mulige perioder med forkert slam-threshold.
    """
    slam_zones = {"Lilleslem", "Storeslem"}
    slam_or_miss = df[
        df.get("pair_zone", pd.Series(dtype=str)).isin(slam_zones)
        | df.get("is_slam_miss", pd.Series(False, index=df.index)).astype(bool)
    ].copy()

    if slam_or_miss.empty:
        return pd.DataFrame()

    cols = (
        _BASE_COLS
        + ["pair_zone", "pair_controls", "five_major_avoidable",
           "is_slam_miss", "is_overcontract"]
        + _FIELD_COLS
        + _DD_COLS
        + _SLAM_EXTRA
        + ["tricks", "contract_required_tricks",
           "ltc_soundness_flag", "contract_aggression_hcp",
           "spil_url"]
    )
    return _keep(slam_or_miss.sort_values("tournament_date"), cols)


# ─────────────────────────────────────────────────────────────────────────────
# Report descriptions (exported to main.py for Excel annotation)
# ─────────────────────────────────────────────────────────────────────────────

# Each value is a list of strings.
# Lines that end with ":" and are uppercased are written in bold by main.py.
REPORT_DESCRIPTIONS: dict[str, list[str]] = {
    "zone_summary": [
        "HVAD SER DU:",
        "En række per kontraktzone med samlet statistik for alle H+P boards i den zone.",
        "",
        "SAADAN FORTOLKES DET:",
        "Sammenlign Avg_pct paa tvaers af zoner for at se om H+P klarer sig bedre i",
        "bestemte niveauer.  Avg_pct_vs_felt < 0 betyder at H+P ligger under feltets",
        "gennemsnit i den zone.  Making_pct < 50% tyder paa systematisk overbud.",
        "",
        "KOLONNER:",
        "Zone              – Intern zone-kode (Partscore, 3NT, Game_Major ...)",
        "Zone_DK           – Dansk betegnelse",
        "Boards            – Antal boards i zonen",
        "Avg_pct           – Gennemsnitlig matchpoint-procent for H+P",
        "Avg_HCP           – Gennemsnitlige highcard-point for H+P's side",
        "Avg_LTC           – Gennemsnitlig Losing Trick Count (lavere = bedre hand)",
        "Avg_dist_pts      – Gennemsnitlige fordelingspoint (shortage-point)",
        "Avg_controls      – Gennemsnitligt antal kontroller (As=2, Kongepar=1)",
        "Making_pct        – Andel boards kontrakten gik hjem (%)",
        "Avg_pct_vs_felt   – Afvigelse fra feltets forventede pct (positiv = bedre end felt)",
    ],
    "zone_vs_field": [
        "HVAD SER DU:",
        "Kryds-tabel over alle kombinationer af H+P-zone og feltets hyppigste zone.",
        "Viser antal boards og gennemsnitlig pct for hvert par af zoner.",
        "",
        "SAADAN FORTOLKES DET:",
        "'undermeld' = H+P stopper i en lavere zone end feltet.",
        "'overmeld'  = H+P melder til en hoejere zone end feltet.",
        "Kig paa Avg_pair_pct for disse boards – er fejlene dyre?",
        "Raekker med Resultat = 'ok' er boards H+P og feltet er enige om niveau.",
        "",
        "KOLONNER:",
        "H+P_Zone      – Den zone H+P spillede i",
        "H+P_Zone_DK   – Dansk betegnelse for H+P's zone",
        "Felt_Zone     – Feltets dominerende zone (field_mode_contract omsat til zone)",
        "Felt_Zone_DK  – Dansk betegnelse for feltets zone",
        "Boards        – Antal boards med denne kombination",
        "Avg_pair_pct  – H+P's gennemsnitlige matchpoint-pct paa disse boards",
        "Avg_HCP       – Gennemsnitlig HCP for H+P's side",
        "Resultat      – ok / undermeld / overmeld",
    ],
    "hcp_profile": [
        "HVAD SER DU:",
        "Statistisk spredning (minimum, kvartiler, median, gennemsnit, max) af HCP",
        "og LTC for hvert kontraktniveau.",
        "",
        "SAADAN FORTOLKES DET:",
        "Afslorer om H+P byder slem med for lidt HCP (HCP_min for Lilleslem meget lavt).",
        "Eller om de altid stopper i delkontrakt selv med 25+ HCP.",
        "LTC_mean betragtes med fordel mod standard-taerskler:",
        "  Partscore <= 9,  3NT/Game <= 7,  Lilleslem <= 4,  Storeslem <= 2",
        "",
        "KOLONNER:",
        "HCP_min/p25/median/mean/p75/max  – Statistisk HCP-fordeling",
        "LTC_min/p25/median/mean/p75/max  – Statistisk LTC-fordeling (lavere = staerkere)",
        "Dist_pts_mean / median           – Fordelingspoint (shortage) gennemsnit og median",
        "Controls_mean / median           – Kontroller (As=2, Km=1) gennemsnit og median",
    ],
    "hcp_zone_distribution": [
        "HVAD SER DU:",
        "For hvert HCP-interval (< 20, 20-22, 23-25 ...) vises antallet af boards",
        "H+P og feltet spiller i hver kontraktzone.",
        "",
        "SAADAN FORTOLKES DET:",
        "Sammenlign H+P_<zone> med Felt_<zone> kolonnerne paa samme HCP-baand.",
        "Eksempel: Hvis H+P med 26-28 HCP oftere er i Partscore end feltet, er det",
        "et signal om systematisk undermeld ved moderate styrker.",
        "Felt_top_zone viser hvad flertallet af andre par meldte med samme HCP.",
        "",
        "KOLONNER:",
        "HCP_band           – HCP-interval (f.eks. '23-25')",
        "Boards             – Antal boards i intervallet",
        "Avg_pct            – H+P's gennemsnitlige matchpoint-pct",
        "H+P_top_zone       – Den zone H+P oftest spillede i",
        "H+P_pct_top        – Andel boards i H+P's topzone (%)",
        "Felt_top_zone      – Den zone feltet oftest spillede i",
        "Felt_pct_top       – Andel boards i feltets topzone (%)",
        "H+P_<zone>         – Antal H+P boards i den specifikke kontraktzone",
        "Felt_<zone>        – Antal felt-boards i den specifikke kontraktzone",
    ],
    "aggression_summary": [
        "HVAD SER DU:",
        "Undermeldsrate, korrekt rate og overmeldsrate per zone sammenlignet",
        "med feltets kontrakter (vs Felt) og double-dummy analyse (vs DD).",
        "Raekken 'All' opsummerer alle zoner samlet.",
        "",
        "SAADAN FORTOLKES DET:",
        "vs_Felt_under_pct > 20% i Game_Major = H+P stopper for tidligt i major-spil.",
        "vs_DD_over_pct > 15% = H+P overmelder systematisk ift. DD's maksimum.",
        "N_game_misses og N_slam_misses er absolutte antal – se detaljer",
        "i arkene Hul_Udgange_Misset og Hul_Slem_Misset.",
        "",
        "KOLONNER:",
        "vs_Felt_under_pct  – % boards H+P er i lavere zone end feltet",
        "vs_Felt_ok_pct     – % boards H+P og feltet er enige om zone",
        "vs_Felt_over_pct   – % boards H+P er i hoejere zone end feltet",
        "vs_DD_under_pct    – % boards H+P er under DD's maks-zone",
        "vs_DD_ok_pct       – % boards H+P er paa DD's maks-zone",
        "vs_DD_over_pct     – % boards H+P er over DD's maks-zone (overbud)",
        "N_game_misses      – Antal oversete udgangsbud sammenlignet med felt",
        "N_slam_misses      – Antal oversete slembud sammenlignet med felt/DD",
        "N_overcontracts    – Antal bud over DD's maks-niveau",
    ],
    "game_misses": [
        "HVAD SER DU:",
        "Alle boards H+P stopte i delkontrakt mens feltet spillede udgang",
        "(3NT, 4H/4S eller 5R/5K).  Sorteret med lavest pct oeverst.",
        "",
        "SAADAN FORTOLKES DET:",
        "pair_hcp >= 25 med undermeld er et klart meldemassigt problem.",
        "pair_hcp < 23 kan retfaerdiggoere stop i delkontrakt (for lidt til udgang).",
        "Sammenlign dd_best_zone med pair_zone for at se om DD ogsaa anbefalede udgang.",
        "Klik paa spil_url for at aabne braettet direkte paa spilresultater.dk.",
        "",
        "KOLONNER:",
        "tournament_date           – Turneringsdato",
        "board                     – Braetnummer",
        "contract / decl            – H+P's kontrakt og melder",
        "pair_side                 – H+P's side (NS eller OV)",
        "pair_pct                  – H+P's matchpoint-procent",
        "pair_hcp                  – H+P's samlede HCP (begge haender)",
        "pair_ltc                  – H+P's Losing Trick Count",
        "pair_dist_pts             – H+P's fordelingspoint (shortage)",
        "field_zone                – Feltets zone baseret paa field_mode_contract",
        "field_mode_contract       – Feltets hyppigste kontrakt",
        "dd_best_zone              – DD's bedste zone for H+P's side",
        "dd_tricks_declarer        – DD's beregnede stikantal for H+P's melder",
        "spil_url                  – Link til braettet paa spilresultater.dk",
    ],
    "slam_misses": [
        "HVAD SER DU:",
        "Boards H+P gik glip af slem: feltet spillede 6x/7x ELLER",
        "DD viser 12+ stik tilgaengeligt for H+P's side.",
        "",
        "SAADAN FORTOLKES DET:",
        "slam_hcp_ok = True: HCP understotter slem (>= 28 for lilleslem).",
        "slam_ltc_ok = True: LTC understotter slem (<= 4 for lilleslem).",
        "pair_controls: slem kraever typisk >= 8 kontroller for sikker lilleslem.",
        "Boards med slam_hcp_ok = True OG slam_ltc_ok = True er klare systemsvagheder",
        "– fundamentet var til stede, men H+P naaede ikke frem til slem.",
        "",
        "KOLONNER:",
        "pair_controls    – Kontroller (As=2, Km=1) for H+P's side",
        "slam_hcp_ok      – HCP-grundlag OK (True/False)",
        "slam_ltc_ok      – LTC-grundlag OK (True/False)",
        "par_contract     – Optimal kontrakt ifoel DD (par-kontrakt)",
        "par_side         – Hvilken side par-kontrakten tilhoerer",
        "NS_HCP / OV_HCP  – HCP for henholdsvis Nord-Syd og Ost-Vest",
    ],
    "slam_attempts": [
        "HVAD SER DU:",
        "Alle boards H+P byder lilleslem (6x) eller storeslem (7x).",
        "Sorteret kronologisk.",
        "",
        "SAADAN FORTOLKES DET:",
        "Brug slam_hcp_ok og slam_ltc_ok til at vurdere budkvaliteten.",
        "play_precision_dd viser om spillet matchede DD's forventning:",
        "  Positiv = bedre end DD forventede,  negativ = daarligere.",
        "Boards med slam_hcp_ok = False OG slam_ltc_ok = False er spekulativt slem.",
        "",
        "KOLONNER:",
        "pair_controls             – Kontroller for H+P's side",
        "slam_hcp_ok               – HCP-grundlag OK (True/False)",
        "slam_ltc_ok               – LTC-grundlag OK (True/False)",
        "tricks                    – Faktisk antal stik opnaaet",
        "contract_required_tricks  – Noedvendige stik for kontrakten",
        "play_precision_dd         – Afvigelse fra DD's forventede stikantal",
    ],
    "slam_quality": [
        "HVAD SER DU:",
        "Kombineret rapport over alle slembud OG alle slem-misser samlet",
        "med HCP/LTC-kontekst og DD-sammenligning.",
        "",
        "SAADAN FORTOLKES DET:",
        "Giver det samlede slem-billede.  Mange is_slam_miss = True boards med",
        "slam_hcp_ok = True er et klart tegn paa slem-aversion (man undgaar slem",
        "selv om fundamentet er der).  Mange slembud med slam_hcp_ok = False er",
        "spekulativt slem.",
        "ltc_soundness_flag: 'sound' = godt fundament, 'marginal' = paa kanten,",
        "'unsound' = svagt fundament.",
        "",
        "KOLONNER:",
        "is_slam_miss              – True: H+P oversa slem (felt/DD havde slem)",
        "is_overcontract           – True: H+P meldte over DD's maks",
        "ltc_soundness_flag        – sound / marginal / unsound baseret paa LTC",
        "contract_aggression_hcp   – HCP-afvigelse fra norm for kontrakten",
        "par_contract              – Optimal kontrakt ifoel DD",
    ],
    "nt_vs_minor_slam": [
        "HVAD SER DU:",
        "Boards H+P spiller 3NT, men DD viser at minor-slem (6R eller 6K)",
        "var tilgaengeligt for H+P's side (12+ DD-stik i en minor).",
        "",
        "SAADAN FORTOLKES DET:",
        "Dette er typisk et systemhul: H+P mangler en mekanisme til at",
        "opdage minor-slem af 3NT-vejen.  dd_minor_max_tricks viser antallet",
        "af DD-stik i den bedste minor for H+P's side.",
        "Kig paa slam_hcp_ok for at se om HCP-fundamentet var til stede.",
        "",
        "KOLONNER:",
        "dd_minor_max_tricks   – DD-stik i den bedste minor for H+P's side",
        "slam_hcp_ok           – HCP-grundlag for slem til stede",
        "slam_ltc_ok           – LTC-grundlag for slem til stede",
        "dd_{N|S|O|V}_{R|K}    – DD-stik for hvert saedet i Ruder/Klor",
    ],
    "overbids": [
        "HVAD SER DU:",
        "Boards H+P melder til en hoejere zone end DD's maksimum for deres side.",
        "Sorteret med lavest pct oeverst (de dyreste fejl forst).",
        "",
        "SAADAN FORTOLKES DET:",
        "Overbids koster matchpoint.  contract_aggression_hcp = faktisk HCP minus",
        "typisk HCP-krav for kontrakten – negativ vaerdi = underbygget bud.",
        "ltc_soundness_flag = 'unsound' bekraefter svagt LTC-fundament.",
        "dd_tricks_declarer viser hvad DD mener man maksimalt kan tage.",
        "",
        "KOLONNER:",
        "dd_best_zone              – DD's maks-zone for H+P's side",
        "dd_tricks_declarer        – DD's beregnede stikantal for melderen",
        "play_precision_dd         – Afvigelse fra DD's forventede stikantal",
        "contract_required_tricks  – Noedvendige stik for H+P's kontrakt",
        "contract_aggression_hcp   – HCP-afvigelse fra norm (negativ = underbygget)",
        "ltc_soundness_flag        – sound / marginal / unsound",
    ],
    "five_major": [
        "HVAD SER DU:",
        "Alle boards H+P spiller 5H eller 5S.",
        "",
        "SAADAN FORTOLKES DET:",
        "5-Major er naesten altid et fejlniveau – man bor enten stoppe i 4M",
        "eller forsoege slem.  five_major_avoidable = True betyder at DD's maks",
        "kun er 4M – dvs. man meldte sig en etage for hoejt uden grund.",
        "Spiller alle andre 4M er det et klart meldefejl.  Spiller andre 6M,",
        "burde man have budt slem i stedet.",
        "",
        "KOLONNER:",
        "five_major_avoidable      – True: DD viser maks er kun 4M (undgaaeligt overbud)",
        "dd_best_zone              – DD's bedste zone for H+P's side",
        "dd_tricks_declarer        – DD's beregnede stikantal",
        "tricks                    – Faktisk antal stik opnaaet",
        "contract_required_tricks  – Noedvendige stik (11 for 5M)",
        "play_precision_dd         – Afvigelse fra DD's forventede stikantal",
    ],
}


def get_pair_metadata(df_pair: pd.DataFrame) -> dict:
    """
    Return basic metadata about the H+P board population.

    Returns:
        dict with keys: n_boards, n_tournaments, date_from, date_to
    """
    n_boards = len(df_pair)

    if "tournament_id" in df_pair.columns:
        n_tournaments = int(df_pair["tournament_id"].nunique())
    elif "tournament_date" in df_pair.columns:
        n_tournaments = int(
            pd.to_datetime(df_pair["tournament_date"], errors="coerce")
            .dt.date.nunique()
        )
    else:
        n_tournaments = 0

    if "tournament_date" in df_pair.columns:
        dates = pd.to_datetime(df_pair["tournament_date"], errors="coerce").dropna()
        date_from = str(dates.min().date()) if len(dates) > 0 else "?"
        date_to   = str(dates.max().date()) if len(dates) > 0 else "?"
    else:
        date_from = date_to = "?"

    return {
        "n_boards":      n_boards,
        "n_tournaments": n_tournaments,
        "date_from":     date_from,
        "date_to":       date_to,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def make_hole_analysis(df: pd.DataFrame) -> dict:
    """
    Komplet hulanalyse for Henrik Friis & PerFøge Jensen.

    Input:
      Fuldt beriget DataFrame efter pipeline:
      add_hand_features → add_phase21_fields → add_mvp_metrics

    Output: dict med følgende DataFrames:
      "zone_summary"         – zoneoverblik m. pct/HCP/LTC
      "zone_vs_field"        – kryds-tabel H+P zone vs felt zone
      "hcp_profile"          – HCP/LTC statistik pr zone
      "hcp_zone_distribution"– HCP-bånd med zone-fordeling vs felt
      "aggression_summary"   – undermeld/ok/overmeld rater vs felt og DD
      "game_misses"          – oversete udgange
      "slam_misses"          – oversete slemmer
      "slam_attempts"        – alle slembud med kontekst
      "slam_quality"         – samlet slam-kvalitetsanalyse
      "nt_vs_minor_slam"     – 3NT spillet men minor-slem tilgængeligt (DD)
      "overbids"             – kontrakter over DD-maximum
      "five_major"           – 5-major boards
      "_metadata"            – dict med n_boards, n_tournaments, date_from, date_to
    """
    _empty: dict = {
        k: pd.DataFrame()
        for k in [
            "zone_summary", "zone_vs_field", "hcp_profile",
            "hcp_zone_distribution", "aggression_summary",
            "game_misses", "slam_misses", "slam_attempts", "slam_quality",
            "nt_vs_minor_slam", "overbids", "five_major",
        ]
    }
    _empty["_metadata"] = {"n_boards": 0, "n_tournaments": 0, "date_from": "?", "date_to": "?"}

    # 1. Filter to boards where both H+P appear
    df_pair = filter_pair_boards(df)
    if df_pair.empty:
        return _empty

    # 2. Enrich with hole-analysis features
    df_pair = add_hole_analysis_features(df_pair)

    # 3. Generate all reports
    return {
        "zone_summary":          make_zone_summary(df_pair),
        "zone_vs_field":         make_zone_vs_field(df_pair),
        "hcp_profile":           make_hcp_profile_by_zone(df_pair),
        "hcp_zone_distribution": make_hcp_zone_distribution(df_pair),
        "aggression_summary":    make_zone_aggression_summary(df_pair),
        "game_misses":           make_game_miss_report(df_pair),
        "slam_misses":           make_slam_miss_report(df_pair),
        "slam_attempts":         make_slam_attempts_report(df_pair),
        "slam_quality":          make_slam_quality_report(df_pair),
        "nt_vs_minor_slam":      make_nt_vs_minor_slam_report(df_pair),
        "overbids":              make_overbid_report(df_pair),
        "five_major":            make_five_major_report(df_pair),
        "_metadata":             get_pair_metadata(df_pair),
    }
