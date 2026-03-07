"""Lead analysis features based on bridge/lead_analysis_spec.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


_SPEC_FILE = Path(__file__).resolve().with_name("lead_analysis_spec.yaml")

_DEFAULT_SPEC = {
    "validate_lead": {
        "rules": [
            "lead_card must exist in leader_hand",
            "lead_card must match lead_suit",
        ],
        "if_invalid": {
            "lead_valid": False,
            "exclude_from_lead_stats": True,
        },
    },
    "detect_rank_structure": {
        "priority": [
            "singleton",
            "doubleton_top",
            "sequence",
            "interior_sequence",
            "length_lead",
        ],
        "classes": [
            "singleton",
            "doubleton_top",
            "top_of_sequence",
            "interior_sequence",
            "4th_highest",
            "2nd_highest",
            "3rd_5th",
            "top_of_nothing",
            "unclear",
        ],
    },
    "strategic_lead_types": [
        "partner_suit_candidate",
        "trump_lead",
        "passive_lead",
        "attacking_lead",
        "short_suit_lead",
        "standard_long_suit_lead",
        "sequence_lead",
        "unclear",
    ],
    "partner_suit_detection": {
        "leader_length_max": 3,
        "partner_length_min": 5,
        "partner_hcp_min": 8,
        "partner_honor_required": True,
    },
    "player_profile": {
        "notrump_long_suit": {
            "with_honor": "4th_highest",
            "without_honor": "2nd_highest",
        },
        "suit_contract_attitude": {
            "with_honor": "low_card",
            "without_honor": "high_card",
        },
        "trump_contract_leads": {
            "side_suit_only": True,
            "describe_only": [
                "3rd_5th",
            ]
        },
    },
    "output_fields": [
        "lead_valid",
        "lead_rank_class",
        "lead_strategic_class",
        "partner_suit_candidate",
        "trump_lead",
        "lead_profile_match",
        "exclude_from_lead_stats",
    ],
}


def _load_spec() -> dict:
    try:
        import yaml  # type: ignore

        if _SPEC_FILE.exists():
            with _SPEC_FILE.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if isinstance(raw, dict) and isinstance(raw.get("lead_analysis_spec"), dict):
                return raw["lead_analysis_spec"]
    except Exception:
        pass
    return _DEFAULT_SPEC


_SPEC = _load_spec()
_OUTPUT_FIELDS = _SPEC.get("output_fields", _DEFAULT_SPEC["output_fields"])
_PARTNER_CFG = _SPEC.get("partner_suit_detection", _DEFAULT_SPEC["partner_suit_detection"])
_PROFILE_CFG = _SPEC.get("player_profile", _DEFAULT_SPEC["player_profile"])


_SUIT_SYMBOL_TO_LETTER = {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}
_SUIT_LETTER_TO_LETTER = {"S": "S", "H": "H", "D": "D", "C": "C"}
_SUIT_TO_DOT_INDEX = {"S": 0, "H": 1, "D": 2, "C": 3}

_RANK_ORDER = "AKQJT98765432"
_RANK_VALUE = {r: i for i, r in enumerate(_RANK_ORDER[::-1])}
_RANK_TRANSLATE = {"E": "A", "K": "K", "D": "Q", "B": "J", "T": "T"}
_HCP_VALUE = {"A": 4, "K": 3, "Q": 2, "J": 1}
_HONOR_SET = {"A", "K", "Q", "J"}

_SEAT_HAND_COL = {
    "N": "N_hand",
    "S": "S_hand",
    "Ø": "Ø_hand",
    "V": "V_hand",
}
_SEAT_HCP_COL = {
    "N": "N_HCP",
    "S": "S_HCP",
    "Ø": "Ø_HCP",
    "V": "V_HCP",
}
_DECL_TO_LEADER = {
    "N": "Ø",
    "Ø": "S",
    "S": "V",
    "V": "N",
}
_PARTNER = {
    "N": "S",
    "S": "N",
    "Ø": "V",
    "V": "Ø",
}


def _default_output() -> dict:
    return {
        "lead_valid": False,
        "lead_rank_class": "unclear",
        "lead_strategic_class": "unclear",
        "partner_suit_candidate": False,
        "trump_lead": False,
        "lead_profile_match": None,
        "exclude_from_lead_stats": True,
    }


def _normalize_seat(value: object) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().upper()
    if s == "E":
        return "Ø"
    if s == "W":
        return "V"
    if s in ("N", "S", "Ø", "V"):
        return s
    return None


def _normalize_suit(value: object) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if "NT" in s or s == "UT":
        return "NT"
    first = s[0]
    if first in _SUIT_SYMBOL_TO_LETTER:
        return _SUIT_SYMBOL_TO_LETTER[first]
    if first in _SUIT_LETTER_TO_LETTER:
        return _SUIT_LETTER_TO_LETTER[first]
    return None


def _normalize_rank_token(token: object) -> Optional[str]:
    if token is None:
        return None
    s = str(token).strip().upper()
    if not s:
        return None
    if s.startswith("10"):
        return "T"
    first = s[0]
    first = _RANK_TRANSLATE.get(first, first)
    return first if first in _RANK_ORDER else None


def _parse_lead_components(lead: object) -> tuple[Optional[str], Optional[str]]:
    if lead is None or (isinstance(lead, float) and pd.isna(lead)):
        return None, None
    s = str(lead).strip()
    if not s:
        return None, None

    compact = s.replace(" ", "")
    if not compact:
        return None, None

    suit = _normalize_suit(compact[0])
    if suit is None:
        return None, None

    rank_token = compact[1:] if len(compact) > 1 else ""
    rank = _normalize_rank_token(rank_token)
    return suit, rank


def _split_dot_hand(dot_hand: object) -> list[str]:
    if dot_hand is None or (isinstance(dot_hand, float) and pd.isna(dot_hand)):
        return ["", "", "", ""]
    s = str(dot_hand).strip()
    if not s:
        return ["", "", "", ""]
    parts = s.split(".")
    while len(parts) < 4:
        parts.append("")
    return parts[:4]


def _normalize_hand_part(part: str) -> list[str]:
    if not part:
        return []
    clean = part.replace("-", "").replace("—", "").replace(" ", "").upper()
    out: list[str] = []
    i = 0
    while i < len(clean):
        if clean[i:i + 2] == "10":
            out.append("T")
            i += 2
            continue
        rank = _normalize_rank_token(clean[i])
        if rank is not None:
            out.append(rank)
        i += 1
    out = [r for r in out if r in _RANK_VALUE]
    out.sort(key=lambda r: _RANK_VALUE[r], reverse=True)
    return out


def _cards_in_suit(dot_hand: object, suit: Optional[str]) -> list[str]:
    if suit is None or suit not in _SUIT_TO_DOT_INDEX:
        return []
    parts = _split_dot_hand(dot_hand)
    idx = _SUIT_TO_DOT_INDEX[suit]
    return _normalize_hand_part(parts[idx])


def _hand_hcp(dot_hand: object) -> Optional[float]:
    parts = _split_dot_hand(dot_hand)
    if not any(parts):
        return None
    total = 0
    for part in parts:
        for rank in _normalize_hand_part(part):
            total += _HCP_VALUE.get(rank, 0)
    return float(total)


def _seat_hcp(row: pd.Series, seat: str) -> Optional[float]:
    hcp_col = _SEAT_HCP_COL.get(seat)
    if hcp_col and hcp_col in row.index:
        val = row.get(hcp_col)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    hand_col = _SEAT_HAND_COL.get(seat)
    return _hand_hcp(row.get(hand_col)) if hand_col else None


def _rank_index(cards_desc: list[str], lead_rank: Optional[str]) -> Optional[int]:
    if not lead_rank:
        return None
    try:
        return cards_desc.index(lead_rank) + 1
    except ValueError:
        return None


def _is_adjacent_desc(high_rank: str, low_rank: str) -> bool:
    return _RANK_VALUE.get(high_rank, -100) == _RANK_VALUE.get(low_rank, -100) + 1


def _classify_rank(cards_desc: list[str], lead_rank: Optional[str]) -> tuple[str, Optional[int]]:
    if not cards_desc or not lead_rank:
        return "unclear", None

    n_cards = len(cards_desc)
    idx = _rank_index(cards_desc, lead_rank)
    if idx is None:
        return "unclear", None

    if n_cards == 1:
        return "singleton", idx

    if n_cards == 2 and idx == 1:
        return "doubleton_top", idx

    pos = idx - 1
    if idx == 1 and n_cards >= 2 and _is_adjacent_desc(cards_desc[0], cards_desc[1]):
        return "top_of_sequence", idx

    if 0 < pos < (n_cards - 1):
        up = _is_adjacent_desc(cards_desc[pos - 1], cards_desc[pos])
        down = _is_adjacent_desc(cards_desc[pos], cards_desc[pos + 1])
        if up and down:
            return "interior_sequence", idx

    if n_cards >= 4 and idx == 4:
        return "4th_highest", idx

    if n_cards >= 2 and idx == 2:
        return "2nd_highest", idx

    # "3rd_5th" means either 3rd-highest (needs >=3 cards) or
    # 5th-highest (needs >=5 cards).
    if (idx == 3 and n_cards >= 3) or (idx == 5 and n_cards >= 5):
        return "3rd_5th", idx

    if idx == 1:
        return "top_of_nothing", idx

    return "unclear", idx


def _contract_strain(row: pd.Series) -> Optional[str]:
    strain = _normalize_suit(row.get("strain"))
    if strain is not None:
        return strain

    contract = row.get("contract")
    if contract is None or (isinstance(contract, float) and pd.isna(contract)):
        return None

    s = str(contract).strip().upper()
    if not s:
        return None
    if "NT" in s or "UT" in s:
        return "NT"
    for ch in s:
        suit = _normalize_suit(ch)
        if suit in ("S", "H", "D", "C"):
            return suit
    return None


def _has_honor(cards_desc: list[str]) -> bool:
    return any(card in _HONOR_SET for card in cards_desc)


def _compute_partner_candidate(
    leader_cards: list[str],
    partner_cards: list[str],
    partner_hcp: Optional[float],
) -> bool:
    leader_length_max = int(_PARTNER_CFG.get("leader_length_max", 3))
    partner_length_min = int(_PARTNER_CFG.get("partner_length_min", 5))
    partner_hcp_min = float(_PARTNER_CFG.get("partner_hcp_min", 8))
    partner_honor_required = bool(_PARTNER_CFG.get("partner_honor_required", True))

    if len(leader_cards) > leader_length_max:
        return False
    if len(partner_cards) < partner_length_min:
        return False
    if partner_hcp is None or partner_hcp < partner_hcp_min:
        return False
    if partner_honor_required and not _has_honor(partner_cards):
        return False
    return True


def _classify_strategic(
    *,
    rank_class: str,
    partner_suit_candidate: bool,
    trump_lead: bool,
    leader_length: int,
) -> str:
    if partner_suit_candidate:
        return "partner_suit_candidate"
    if trump_lead:
        return "trump_lead"
    if rank_class in ("top_of_sequence", "interior_sequence"):
        return "sequence_lead"
    if leader_length <= 2:
        return "short_suit_lead"
    if rank_class in ("4th_highest", "2nd_highest", "3rd_5th") and leader_length >= 4:
        return "standard_long_suit_lead"
    if rank_class in ("singleton", "doubleton_top", "top_of_nothing"):
        return "attacking_lead"
    if rank_class in ("4th_highest", "2nd_highest", "3rd_5th"):
        return "passive_lead"
    return "unclear"


def _profile_match(
    *,
    contract_strain: Optional[str],
    rank_class: str,
    lead_index: Optional[int],
    leader_cards: list[str],
    trump_lead: bool,
) -> Optional[bool]:
    if not leader_cards or lead_index is None:
        return None

    has_honor = _has_honor(leader_cards)
    n_cards = len(leader_cards)

    nt_cfg = _PROFILE_CFG.get("notrump_long_suit", {})
    suit_cfg = _PROFILE_CFG.get("suit_contract_attitude", {})

    if contract_strain == "NT" and n_cards >= 4:
        if has_honor:
            return rank_class == nt_cfg.get("with_honor", "4th_highest")
        return rank_class == nt_cfg.get("without_honor", "2nd_highest")

    if contract_strain in ("S", "H", "D", "C"):
        if trump_lead:
            return None

        low_card = lead_index >= max(n_cards - 1, 1)
        high_card = lead_index <= min(2, n_cards)

        if has_honor:
            return low_card if suit_cfg.get("with_honor", "low_card") == "low_card" else high_card
        return high_card if suit_cfg.get("without_honor", "high_card") == "high_card" else low_card

    return None


def _analyze_row(row: pd.Series) -> pd.Series:
    result = _default_output()

    lead_suit, lead_rank = _parse_lead_components(row.get("lead"))
    leader = _DECL_TO_LEADER.get(_normalize_seat(row.get("decl")) or "")

    if lead_suit is None or lead_rank is None or leader is None:
        return pd.Series(result)

    row_lead_suit = _normalize_suit(row.get("lead_suit")) if "lead_suit" in row.index else None
    row_lead_card = _normalize_rank_token(row.get("lead_card")) if "lead_card" in row.index else None

    if row_lead_suit is not None and row_lead_suit != lead_suit:
        return pd.Series(result)
    if row_lead_card is not None and row_lead_card != lead_rank:
        return pd.Series(result)

    leader_hand_col = _SEAT_HAND_COL.get(leader)
    if leader_hand_col is None:
        return pd.Series(result)

    leader_cards = _cards_in_suit(row.get(leader_hand_col), lead_suit)
    if lead_rank not in leader_cards:
        return pd.Series(result)

    result["lead_valid"] = True
    result["exclude_from_lead_stats"] = False

    rank_class, lead_index = _classify_rank(leader_cards, lead_rank)
    result["lead_rank_class"] = rank_class

    partner = _PARTNER.get(leader)
    partner_cards = _cards_in_suit(row.get(_SEAT_HAND_COL.get(partner, "")), lead_suit) if partner else []
    partner_hcp = _seat_hcp(row, partner) if partner else None

    partner_suit_candidate = _compute_partner_candidate(leader_cards, partner_cards, partner_hcp)
    result["partner_suit_candidate"] = partner_suit_candidate

    contract_strain = _contract_strain(row)
    trump_lead = contract_strain in ("S", "H", "D", "C") and contract_strain == lead_suit
    result["trump_lead"] = trump_lead

    result["lead_strategic_class"] = _classify_strategic(
        rank_class=rank_class,
        partner_suit_candidate=partner_suit_candidate,
        trump_lead=trump_lead,
        leader_length=len(leader_cards),
    )

    result["lead_profile_match"] = _profile_match(
        contract_strain=contract_strain,
        rank_class=rank_class,
        lead_index=lead_index,
        leader_cards=leader_cards,
        trump_lead=trump_lead,
    )

    return pd.Series(result)


def add_lead_analysis_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add lead-analysis fields to a DataFrame.

    Adds columns (from output_fields in lead_analysis_spec):
    - lead_valid
    - lead_rank_class
    - lead_strategic_class
    - partner_suit_candidate
    - trump_lead
    - lead_profile_match
    - exclude_from_lead_stats
    """
    out = df.copy()

    if out.empty:
        for field in _OUTPUT_FIELDS:
            out[field] = pd.Series(dtype=object)
        return out

    derived = out.apply(_analyze_row, axis=1)

    for field in _OUTPUT_FIELDS:
        if field not in derived.columns:
            derived[field] = _default_output().get(field)

    out = pd.concat([out, derived[_OUTPUT_FIELDS]], axis=1)
    return out
