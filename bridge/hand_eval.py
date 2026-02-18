"""
bridge/hand_eval.py

Hand evaluation utilities for BridgeAnalytics.

Input hand format (dot-format):
    "AKT7.QJ3.984.AK2"
= Spades.Hearts.Diamonds.Clubs

This module provides:
- parsing of dot hands
- HCP (High Card Points)
- shape (e.g., "5-3-3-2" and tuple)
- distribution points (simple)
- controls (A=2, K=1) + count of aces/kings
- Adjusted LTC (recommended for suit contracts; also usable as a stability measure in NT)

Design goals:
- deterministic, explainable metrics
- robust to empty suits ("", "-" or "—")
- easy to integrate with pandas feature engineering
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional


# ----------------------------
# Constants
# ----------------------------

SUITS_ORDER = ("S", "H", "D", "C")

HCP_MAP = {"A": 4, "K": 3, "Q": 2, "J": 1}
CONTROL_MAP = {"A": 2, "K": 1}

# Allowed rank characters in your normalized storage (A,K,Q,J,T,9..2)
ALLOWED_RANKS = set("AKQJT98765432")


# ----------------------------
# Data structures
# ----------------------------

@dataclass(frozen=True)
class ParsedHand:
    """
    Parsed representation of a hand.
    suits: dict suit -> string of ranks (e.g., {"S":"AKT7","H":"QJ3","D":"984","C":"AK2"})
    lengths: dict suit -> int
    """
    suits: Dict[str, str]
    lengths: Dict[str, int]

    def dot(self) -> str:
        return ".".join(self.suits[s] for s in SUITS_ORDER)


# ----------------------------
# Parsing
# ----------------------------

def _clean_suit_str(s: str) -> str:
    """
    Normalizes one suit string.
    Accepts:
      "" / "-" / "—" as void
    Filters to ALLOWED_RANKS only.
    Keeps original order (doesn't sort ranks).
    """
    if s is None:
        return ""
    s = s.strip().replace(" ", "")
    if s in ("-", "—"):
        return ""
    # filter out anything unexpected
    return "".join(ch for ch in s if ch in ALLOWED_RANKS)


def parse_hand(dot_hand: str) -> ParsedHand:
    """
    Parse dot-format hand into ParsedHand.

    Examples:
      "AKT7.QJ3.984.AK2"
      "T9875.983.Q.AQ74"
      "...." -> all void suits
    """
    if dot_hand is None:
        dot_hand = ""
    dot_hand = dot_hand.strip()

    parts = dot_hand.split(".")
    # pad / truncate to 4
    parts = (parts + ["", "", "", ""])[:4]
    parts = [_clean_suit_str(p) for p in parts]

    suits = {suit: parts[i] for i, suit in enumerate(SUITS_ORDER)}
    lengths = {suit: len(suits[suit]) for suit in SUITS_ORDER}
    return ParsedHand(suits=suits, lengths=lengths)


# ----------------------------
# Basic metrics
# ----------------------------

def hcp(hand: ParsedHand) -> int:
    """High Card Points: A=4, K=3, Q=2, J=1."""
    total = 0
    for suit in SUITS_ORDER:
        for r in hand.suits[suit]:
            total += HCP_MAP.get(r, 0)
    return total


def controls(hand: ParsedHand) -> Dict[str, int]:
    """
    Controls:
      A = 2
      K = 1
    Returns dict with:
      controls, aces, kings
    """
    aces = 0
    kings = 0
    ctrl = 0
    for suit in SUITS_ORDER:
        ranks = hand.suits[suit]
        if "A" in ranks:
            aces += 1
            ctrl += 2
        if "K" in ranks:
            kings += 1
            ctrl += 1
    return {"controls": ctrl, "aces": aces, "kings": kings}


def shape_tuple(hand: ParsedHand) -> Tuple[int, int, int, int]:
    """Returns suit lengths as a tuple (S, H, D, C)."""
    return (hand.lengths["S"], hand.lengths["H"], hand.lengths["D"], hand.lengths["C"])


def shape_str(hand: ParsedHand, sort_desc: bool = True) -> str:
    """
    Returns a shape string like "5-3-3-2".
    By default sorts lengths descending (common in bridge).
    If sort_desc=False returns S-H-D-C order.
    """
    lens = list(shape_tuple(hand))
    if sort_desc:
        lens.sort(reverse=True)
    return "-".join(str(x) for x in lens)


def is_balanced(hand: ParsedHand) -> bool:
    """
    Balanced heuristic:
      4333, 4432, 5332 are treated as balanced.
    """
    lens = sorted(shape_tuple(hand), reverse=True)
    return lens in ([4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2])


# ----------------------------
# Distribution points (simple)
# ----------------------------

def distribution_points(hand: ParsedHand, method: str = "shortage") -> int:
    """
    Simple distribution points.
    method="shortage":
      void=3, singleton=2, doubleton=1, else 0
    This is traditional for suit contracts and NOT recommended for NT.
    """
    if method != "shortage":
        raise ValueError("Only method='shortage' is implemented.")

    pts = 0
    for suit in SUITS_ORDER:
        l = hand.lengths[suit]
        if l == 0:
            pts += 3
        elif l == 1:
            pts += 2
        elif l == 2:
            pts += 1
    return pts


# ----------------------------
# Adjusted LTC
# ----------------------------

def ltc_adjusted_suit(ranks: str, length: int) -> float:
    """
    Adjusted LTC per suit.

    Base: losers = min(3, length)
    Adjustments:
      - A reduces 1 loser always.
      - K reduces 1 loser if length>=2, else reduces 0.5 if singleton.
      - Q reduces 1 loser if length>=3, else reduces 0.5 if doubleton.
    Clamp to [0, 3].

    This is a stable, explainable "Adjusted LTC light".
    """
    losers = float(min(3, length))

    if length <= 0:
        return 0.0

    has_a = "A" in ranks
    has_k = "K" in ranks
    has_q = "Q" in ranks

    if has_a:
        losers -= 1.0

    if has_k:
        losers -= 1.0 if length >= 2 else 0.5

    if has_q:
        losers -= 1.0 if length >= 3 else (0.5 if length == 2 else 0.0)

    if losers < 0.0:
        losers = 0.0
    if losers > 3.0:
        losers = 3.0
    return losers


def ltc_adjusted(hand: ParsedHand) -> float:
    """
    Adjusted LTC for the whole hand (sum over suits).
    Returns float because we allow half-losers (singleton K, Qx).
    """
    total = 0.0
    for suit in SUITS_ORDER:
        ranks = hand.suits[suit]
        length = hand.lengths[suit]
        total += ltc_adjusted_suit(ranks, length)
    return total


# ----------------------------
# Convenience: evaluate hand
# ----------------------------

def evaluate_hand(dot_hand: str) -> Dict[str, object]:
    """
    Convenience function: takes dot string, returns dict of features.
    """
    ph = parse_hand(dot_hand)
    ctrl = controls(ph)
    return {
        "dot": ph.dot(),
        "hcp": hcp(ph),
        "shape": shape_str(ph, sort_desc=True),
        "shape_shdc": "-".join(str(x) for x in shape_tuple(ph)),  # S-H-D-C order as string
        "balanced": is_balanced(ph),
        "dist_pts_shortage": distribution_points(ph, method="shortage"),
        "ltc_adj": ltc_adjusted(ph),
        "controls": ctrl["controls"],
        "aces": ctrl["aces"],
        "kings": ctrl["kings"],
    }


# ----------------------------
# Side evaluation helpers
# ----------------------------

def evaluate_side(dot_hand_1: str, dot_hand_2: str) -> Dict[str, object]:
    """
    Evaluate two hands as a partnership side (e.g., NS).
    Returns combined and per-hand metrics.
    """
    h1 = parse_hand(dot_hand_1)
    h2 = parse_hand(dot_hand_2)

    e1 = evaluate_hand(dot_hand_1)
    e2 = evaluate_hand(dot_hand_2)

    # Combined shape (sum lengths by suit)
    combined_lengths = {s: h1.lengths[s] + h2.lengths[s] for s in SUITS_ORDER}
    combined_shape_shdc = (combined_lengths["S"], combined_lengths["H"], combined_lengths["D"], combined_lengths["C"])
    combined_shape_sorted = "-".join(str(x) for x in sorted(combined_shape_shdc, reverse=True))

    return {
        "hcp_total": int(e1["hcp"]) + int(e2["hcp"]),
        "ltc_adj_total": float(e1["ltc_adj"]) + float(e2["ltc_adj"]),
        "controls_total": int(e1["controls"]) + int(e2["controls"]),
        "aces_total": int(e1["aces"]) + int(e2["aces"]),
        "kings_total": int(e1["kings"]) + int(e2["kings"]),
        "combined_shape": combined_shape_sorted,
        "combined_shape_shdc": "-".join(str(x) for x in combined_shape_shdc),
        "hand1": e1,
        "hand2": e2,
    }


# ----------------------------
# Self-test
# ----------------------------

if __name__ == "__main__":
    # Example from your debug
    test = "T9875.983.Q.AQ74"
    print("Test hand:", test)
    print(evaluate_hand(test))

    # Quick sanity: HCP should be A(4)+Q(2)+A(4)+Q(2)=12
    # There is also no K/J. Total should be 12.
    # LTC rough check: S length 5 no A/K/Q -> min(3,5)=3
    # H length 3 no A/K/Q -> 3
    # D length 1 with Q singleton -> base 1, Q doesn't help singleton -> 1
    # C length 4 with A+Q -> base 3, -1(A), -1(Q because length>=3) => 1
    # Total = 3+3+1+1 = 8
    print("\nExpected rough HCP=12, LTC~8")
