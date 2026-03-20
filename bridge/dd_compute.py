"""Double Dummy computation via endplay/DDS.

Wraps the endplay library to compute:
- Full DD trick tables (all 4 directions × 5 strains)
- Par contracts and scores
- Lead-dependent trick tables for opening lead analysis

Direction mapping (Danish ↔ NESW):
    N → north   Ø → east   S → south   V → west

Strain mapping (field name ↔ endplay Denom):
    NT → nt   S → spades   H → hearts   D → diamonds   C → clubs

Vulnerability mapping:
    "-" → none   "NS" → ns   "ØV" → ew   "Begge" → both

Card canonical format (lead table keys): "<suit_letter><rank>"
    suit_letter: S / H / D / C
    rank:        A K Q J T 9 8 7 6 5 4 3 2
    Example:     "H5"  = ♥5,  "SA" = ♠A
"""
from __future__ import annotations

from typing import Optional

from endplay.types import Card, Deal, Denom, Player, Vul
from endplay.dds import calc_dd_table, solve_board, par

# ---------------------------------------------------------------------------
# Direction adapters
# ---------------------------------------------------------------------------

_DIR_DK = ["N", "Ø", "S", "V"]

_DIR_DK_TO_PLAYER: dict[str, Player] = {
    "N": Player.north,
    "Ø": Player.east,
    "S": Player.south,
    "V": Player.west,
}

_PLAYER_TO_DIR_DK: dict[Player, str] = {v: k for k, v in _DIR_DK_TO_PLAYER.items()}

# ---------------------------------------------------------------------------
# Vulnerability adapter
# ---------------------------------------------------------------------------

_VUL_DK_TO_VUL: dict[str, Vul] = {
    "-": Vul.none,
    "NS": Vul.ns,
    "ØV": Vul.ew,
    "Begge": Vul.both,
}

# ---------------------------------------------------------------------------
# Strain adapter
# ---------------------------------------------------------------------------

# Unicode suit symbols used in the data
_STRAIN_SYM_TO_DENOM: dict[str, Denom] = {
    "NT": Denom.nt,
    "♠": Denom.spades,
    "♥": Denom.hearts,
    "♦": Denom.diamonds,
    "♣": Denom.clubs,
}

# Column-name suffix → Denom (used when building dd_{dir}_{strain} field names)
_FIELD_STRAIN_TO_DENOM: dict[str, Denom] = {
    "NT": Denom.nt,
    "S": Denom.spades,
    "H": Denom.hearts,
    "D": Denom.diamonds,
    "C": Denom.clubs,
}

# Denom → Unicode suit symbol (for par output)
_DENOM_TO_SYM: dict[Denom, str] = {
    Denom.spades: "♠",
    Denom.hearts: "♥",
    Denom.diamonds: "♦",
    Denom.clubs: "♣",
    Denom.nt: "NT",
}

# Card canonical form helpers
_DENOM_TO_SUIT_LETTER: dict[Denom, str] = {
    Denom.spades: "S",
    Denom.hearts: "H",
    Denom.diamonds: "D",
    Denom.clubs: "C",
}

_SUIT_SYM_TO_SUIT_LETTER: dict[str, str] = {
    "♠": "S",
    "♥": "H",
    "♦": "D",
    "♣": "C",
}

# ---------------------------------------------------------------------------
# Deal builder
# ---------------------------------------------------------------------------


def build_deal(row: dict, *, first: Player = Player.north, trump: Denom = Denom.nt) -> Deal:
    """Build an endplay Deal from a board row.

    Expects keys: N_hand, Ø_hand, S_hand, V_hand — all dot-notation S.H.D.C.
    """
    n = row["N_hand"]
    e = row["Ø_hand"]
    s = row["S_hand"]
    w = row["V_hand"]
    return Deal(f"N:{n} {e} {s} {w}", first=first, trump=trump)


# ---------------------------------------------------------------------------
# DD trick table
# ---------------------------------------------------------------------------

_DD_DIRS = ["N", "Ø", "S", "V"]
_DD_STRAINS = ["NT", "S", "H", "D", "C"]


def compute_dd_table(row: dict) -> dict:
    """Compute the full double-dummy trick table for a board.

    Returns a dict with keys dd_{dir}_{strain} for all 4 dirs × 5 strains,
    matching the same schema as data scraped from bridge.dk.

    Also sets dd_valid=True.
    """
    deal = build_deal(row)
    table = calc_dd_table(deal)
    result: dict = {"dd_valid": True}
    for dir_dk in _DD_DIRS:
        player = _DIR_DK_TO_PLAYER[dir_dk]
        for strain_key, denom in _FIELD_STRAIN_TO_DENOM.items():
            result[f"dd_{dir_dk}_{strain_key}"] = table[denom, player]
    return result


# ---------------------------------------------------------------------------
# Par contract
# ---------------------------------------------------------------------------


def compute_par(row: dict) -> dict:
    """Compute par contract and score for a board.

    Returns:
        par_score  : int — par score (positive = NS advantage, negative = EW)
        par_contract : str — e.g. "4♠" or "3NT"
        par_side   : str — "NS" or "ØV"
    """
    deal = build_deal(row)
    table = calc_dd_table(deal)
    vul = _VUL_DK_TO_VUL.get(row.get("vul", "-"), Vul.none)
    dealer = _DIR_DK_TO_PLAYER.get(row.get("dealer", "N"), Player.north)

    par_list = par(table, vul, dealer)
    contracts = list(par_list)
    if not contracts:
        return {"par_score": None, "par_contract": None, "par_side": None}

    score = par_list.score
    c = contracts[0]
    par_side_ew = c.declarer in (Player.east, Player.west)
    par_side = "ØV" if par_side_ew else "NS"
    contract_str = f"{c.level}{_DENOM_TO_SYM[c.denom]}"
    return {"par_score": score, "par_contract": contract_str, "par_side": par_side}


# ---------------------------------------------------------------------------
# Lead card parser
# ---------------------------------------------------------------------------


def parse_lead_card(lead: object) -> Optional[str]:
    """Parse a lead string into a canonical card key ("H5", "SA", …).

    Accepts formats: "♥ 5", "♠A", "♦ T" etc.
    Returns None on invalid input.
    """
    if not lead or not isinstance(lead, str):
        return None
    parts = lead.strip().split()
    if len(parts) == 2:
        suit_sym, rank = parts[0], parts[1]
    elif len(parts) == 1 and len(lead.strip()) >= 2:
        suit_sym = lead.strip()[0]
        rank = lead.strip()[1:]
    else:
        return None

    suit_letter = _SUIT_SYM_TO_SUIT_LETTER.get(suit_sym)
    if not suit_letter:
        return None
    rank = rank.strip().upper()
    if not rank or rank not in "AKQJT98765432":
        return None
    return suit_letter + rank


# ---------------------------------------------------------------------------
# Lead-dependent trick table
# ---------------------------------------------------------------------------


def compute_lead_table(row: dict) -> dict[str, int]:
    """Compute DD declarer-tricks for every legal opening lead.

    Solves the position for each card the opening leader (LHO of declarer)
    can lead. Returns a dict mapping canonical card keys to declarer tricks:

        {"H5": 9, "C3": 7, "CA": 7, …}

    A higher value means more tricks for the declarer (= worse lead for defense).
    The best defensive lead is the card with the lowest declarer-tricks value.

    Returns {} if the row lacks the required fields (strain, decl, hands).
    """
    strain_sym = row.get("strain")
    decl = row.get("decl")
    if not strain_sym or not decl:
        return {}
    denom = _STRAIN_SYM_TO_DENOM.get(strain_sym)
    if denom is None:
        return {}
    declarer_player = _DIR_DK_TO_PLAYER.get(decl)
    if declarer_player is None:
        return {}

    # Leader is LHO of declarer
    leader = Player((declarer_player.value + 1) % 4)

    deal = build_deal(row, first=leader, trump=denom)
    solved = solve_board(deal)

    out: dict[str, int] = {}
    for card, defense_tricks in solved:
        suit_letter = _DENOM_TO_SUIT_LETTER[card.suit]
        rank_str = card.rank.name[1:]  # "RA" → "A", "R5" → "5"
        key = suit_letter + rank_str
        # defense_tricks = tricks for the leader's side; declarer gets the rest
        out[key] = 13 - defense_tricks
    return out
