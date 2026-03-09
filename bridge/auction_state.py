"""Range-based auction state for information-safe bidding evaluation.

Design rule:
- A seat may use own hand exactly.
- Partner and opponents are represented as ranges inferred from public bidding.
- No hidden-card leakage is allowed in state updates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping

from bridge.hand_eval import controls as calc_controls
from bridge.hand_eval import hcp as calc_hcp
from bridge.hand_eval import ltc_adjusted
from bridge.hand_eval import parse_hand


SEATS = ("N", "Ø", "S", "V")
SUITS = ("S", "H", "D", "C")
SIDE_OF = {"N": "NS", "S": "NS", "Ø": "ØV", "V": "ØV"}
PARTNER_OF = {"N": "S", "S": "N", "Ø": "V", "V": "Ø"}
NEXT_SEAT = {"N": "Ø", "Ø": "S", "S": "V", "V": "N"}


def _normalize_seat(seat: object) -> str | None:
    s = str(seat or "").strip().upper()
    if s == "E":
        s = "Ø"
    if s == "W":
        s = "V"
    return s if s in SEATS else None


def _normalize_strain(strain: object) -> str | None:
    s = str(strain or "").strip().upper()
    suit_map = {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}
    if s in suit_map:
        s = suit_map[s]
    if s in ("S", "H", "D", "C", "NT"):
        return s
    return None


def _strain_order(strain: str) -> int:
    return {"C": 1, "D": 2, "H": 3, "S": 4, "NT": 5}.get(strain, 0)


def _parse_contract_bid(bid: object) -> tuple[int, str] | None:
    txt = str(bid or "").strip().upper().replace(" ", "")
    if txt in ("PASS", "PAS", "X", "XX"):
        return None
    m = re.match(r"^([1-7])(NT|S|H|D|C|♠|♥|♦|♣)$", txt)
    if not m:
        return None
    lvl = int(m.group(1))
    strain = _normalize_strain(m.group(2))
    if strain is None:
        return None
    return lvl, strain


def _is_higher_contract(candidate: str | None, reference: str | None) -> bool:
    c = _parse_contract_bid(candidate)
    r = _parse_contract_bid(reference)
    if c is None:
        return False
    if r is None:
        return True
    if c[0] > r[0]:
        return True
    return c[0] == r[0] and _strain_order(c[1]) > _strain_order(r[1])


@dataclass(frozen=True)
class ValueRange:
    low: float
    high: float

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"Invalid range: {self.low} > {self.high}")

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0

    def clamp(self, low: float, high: float) -> "ValueRange":
        lo = max(low, self.low)
        hi = min(high, self.high)
        if lo > hi:
            lo = hi
        return ValueRange(lo, hi)

    def pretty(self, decimals: int = 1) -> str:
        def _fmt(v: float) -> str:
            if abs(v - round(v)) < 1e-9:
                return str(int(round(v)))
            return f"{v:.{decimals}f}"

        return f"{_fmt(self.low)}-{_fmt(self.high)}"


def _intersect_keep_current_on_conflict(
    current: ValueRange,
    incoming: ValueRange,
) -> tuple[ValueRange, bool]:
    lo = max(current.low, incoming.low)
    hi = min(current.high, incoming.high)
    if lo > hi:
        return current, False
    return ValueRange(lo, hi), True


@dataclass
class BidEvidence:
    source: str
    hcp_range: ValueRange | None = None
    ltc_range: ValueRange | None = None
    controls_range: ValueRange | None = None
    suit_min: dict[str, int] = field(default_factory=dict)
    suit_max: dict[str, int] = field(default_factory=dict)
    natural_strain: str | None = None
    fit_with_partner_strain: str | None = None
    forcing_state: str | None = None
    artificial: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class SeatEstimate:
    seat: str
    known_hand: bool = False
    hcp_range: ValueRange = field(default_factory=lambda: ValueRange(0.0, 37.0))
    ltc_range: ValueRange = field(default_factory=lambda: ValueRange(0.0, 12.0))
    controls_range: ValueRange = field(default_factory=lambda: ValueRange(0.0, 12.0))
    suit_min: dict[str, int] = field(default_factory=lambda: {s: 0 for s in SUITS})
    suit_max: dict[str, int] = field(default_factory=lambda: {s: 13 for s in SUITS})
    shown_natural_suits: set[str] = field(default_factory=set)
    forcing_state: str = "passable"
    artificial_calls_seen: int = 0
    evidence_log: list[str] = field(default_factory=list)


@dataclass
class FitEstimate:
    side: str
    strain: str
    length_range: ValueRange
    confidence: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class CallRecord:
    seat: str
    bid: str
    source: str


@dataclass
class SidePotentialEstimate:
    side: str
    strain: str
    hcp_range: ValueRange
    ltc_range: ValueRange
    fit_range: ValueRange
    tricks_range: ValueRange
    confidence: float
    reasoning: list[str] = field(default_factory=list)


@dataclass
class AuctionState:
    perspective_seat: str
    dealer: str
    vulnerability: str
    next_to_act: str
    seats: dict[str, SeatEstimate]
    calls: list[CallRecord] = field(default_factory=list)
    fit_estimates: dict[tuple[str, str], FitEstimate] = field(default_factory=dict)
    highest_contract: str | None = None
    assumptions: list[str] = field(default_factory=list)


def create_auction_state(
    perspective_seat: str,
    dealer: str,
    vulnerability: str,
    own_hand_dot: str | None = None,
) -> AuctionState:
    """Create a fresh auction state from one seat perspective.

    Partner/opponents start as broad ranges and are tightened only via bid evidence.
    """
    perspective = _normalize_seat(perspective_seat)
    dealer_norm = _normalize_seat(dealer)
    if perspective is None:
        raise ValueError(f"Invalid perspective seat: {perspective_seat}")
    if dealer_norm is None:
        raise ValueError(f"Invalid dealer seat: {dealer}")

    seats = {s: SeatEstimate(seat=s) for s in SEATS}
    out = AuctionState(
        perspective_seat=perspective,
        dealer=dealer_norm,
        vulnerability=str(vulnerability or ""),
        next_to_act=dealer_norm,
        seats=seats,
        assumptions=[
            "Only perspective hand is exact.",
            "Partner/opponents are modeled as ranges inferred from public calls.",
        ],
    )

    if own_hand_dot is not None and str(own_hand_dot).strip() not in ("", "None"):
        _load_exact_hand(out, perspective, str(own_hand_dot))

    return out


def _load_exact_hand(state: AuctionState, seat: str, hand_dot: str) -> None:
    parsed = parse_hand(hand_dot)
    hcp_val = float(calc_hcp(parsed))
    ltc_val = float(ltc_adjusted(parsed))
    ctr_val = float(calc_controls(parsed).get("controls", 0))

    s = state.seats[seat]
    s.known_hand = True
    s.hcp_range = ValueRange(hcp_val, hcp_val)
    s.ltc_range = ValueRange(ltc_val, ltc_val)
    s.controls_range = ValueRange(ctr_val, ctr_val)
    for suit in SUITS:
        ln = int(parsed.lengths[suit])
        s.suit_min[suit] = ln
        s.suit_max[suit] = ln
    s.evidence_log.append("Exact hand loaded for perspective seat.")


def _safe_apply_suit_bounds(seat_state: SeatEstimate) -> None:
    for suit in SUITS:
        if seat_state.suit_min[suit] > seat_state.suit_max[suit]:
            seat_state.suit_max[suit] = seat_state.suit_min[suit]


def _apply_evidence_to_seat(seat_state: SeatEstimate, evidence: BidEvidence) -> None:
    if evidence.hcp_range is not None:
        new_rng, ok = _intersect_keep_current_on_conflict(seat_state.hcp_range, evidence.hcp_range)
        if ok:
            seat_state.hcp_range = new_rng.clamp(0.0, 37.0)
        else:
            seat_state.evidence_log.append("Conflicting HCP evidence ignored.")

    if evidence.ltc_range is not None:
        new_rng, ok = _intersect_keep_current_on_conflict(seat_state.ltc_range, evidence.ltc_range)
        if ok:
            seat_state.ltc_range = new_rng.clamp(0.0, 12.0)
        else:
            seat_state.evidence_log.append("Conflicting LTC evidence ignored.")

    if evidence.controls_range is not None:
        new_rng, ok = _intersect_keep_current_on_conflict(seat_state.controls_range, evidence.controls_range)
        if ok:
            seat_state.controls_range = new_rng.clamp(0.0, 12.0)
        else:
            seat_state.evidence_log.append("Conflicting controls evidence ignored.")

    for suit, min_len in evidence.suit_min.items():
        strain = _normalize_strain(suit)
        if strain in SUITS:
            seat_state.suit_min[strain] = max(seat_state.suit_min[strain], int(min_len))

    for suit, max_len in evidence.suit_max.items():
        strain = _normalize_strain(suit)
        if strain in SUITS:
            seat_state.suit_max[strain] = min(seat_state.suit_max[strain], int(max_len))

    natural = _normalize_strain(evidence.natural_strain)
    if natural in SUITS:
        seat_state.shown_natural_suits.add(str(natural))
        # Natural bid defaults to 4+ unless a stronger bound was provided.
        seat_state.suit_min[str(natural)] = max(seat_state.suit_min[str(natural)], 4)

    if evidence.fit_with_partner_strain is not None:
        strain = _normalize_strain(evidence.fit_with_partner_strain)
        if strain in SUITS:
            # Explicit fit-showing evidence usually promises at least 3 cards.
            seat_state.suit_min[str(strain)] = max(seat_state.suit_min[str(strain)], 3)

    if evidence.forcing_state:
        seat_state.forcing_state = str(evidence.forcing_state)

    if evidence.artificial:
        seat_state.artificial_calls_seen += 1

    _safe_apply_suit_bounds(seat_state)

    seat_state.evidence_log.append(evidence.source)
    for note in evidence.notes:
        seat_state.evidence_log.append(str(note))


def _update_fit_estimate(
    state: AuctionState,
    seat: str,
    strain: str,
    reason: str,
) -> None:
    side = SIDE_OF[seat]
    partner = PARTNER_OF[seat]
    own = state.seats[seat]
    mate = state.seats[partner]

    fit_min = own.suit_min[strain] + mate.suit_min[strain]
    fit_max = own.suit_max[strain] + mate.suit_max[strain]
    fit_range = ValueRange(float(max(0, min(13, fit_min))), float(max(0, min(13, fit_max))))

    own_unc = own.suit_max[strain] - own.suit_min[strain]
    mate_unc = mate.suit_max[strain] - mate.suit_min[strain]
    confidence = max(0.10, min(0.95, 1.0 - (own_unc + mate_unc) / 26.0))

    key = (side, strain)
    prev = state.fit_estimates.get(key)
    reasons = list(prev.reasons) if prev is not None else []
    reasons.append(reason)

    state.fit_estimates[key] = FitEstimate(
        side=side,
        strain=strain,
        length_range=fit_range,
        confidence=confidence,
        reasons=reasons,
    )


def apply_bid_evidence(
    state: AuctionState,
    seat: str,
    bid: str,
    evidence: BidEvidence,
) -> AuctionState:
    """Apply one public call to auction state.

    This mutates and returns `state` to keep usage simple in bidding loops.
    """
    seat_norm = _normalize_seat(seat)
    if seat_norm is None:
        raise ValueError(f"Invalid seat: {seat}")

    state.calls.append(CallRecord(seat=seat_norm, bid=str(bid), source=evidence.source))

    if _is_higher_contract(str(bid), state.highest_contract):
        state.highest_contract = str(bid)

    _apply_evidence_to_seat(state.seats[seat_norm], evidence)

    natural = _normalize_strain(evidence.natural_strain)
    if natural in SUITS:
        _update_fit_estimate(state, seat_norm, str(natural), f"Natural {bid} by {seat_norm}.")

    explicit_fit = _normalize_strain(evidence.fit_with_partner_strain)
    if explicit_fit in SUITS:
        _update_fit_estimate(state, seat_norm, str(explicit_fit), f"Fit-showing {bid} by {seat_norm}.")

    state.next_to_act = NEXT_SEAT[seat_norm]
    return state


def _fit_bonus(fit_cards: int) -> int:
    if fit_cards >= 10:
        return 2
    if fit_cards >= 9:
        return 1
    return 0


def estimate_side_potential(
    state: AuctionState,
    perspective_seat: str,
    strain: str,
) -> SidePotentialEstimate:
    """Estimate side trick interval using ranges only (no hidden cards)."""
    seat = _normalize_seat(perspective_seat)
    strain_norm = _normalize_strain(strain)
    if seat is None:
        raise ValueError(f"Invalid perspective seat: {perspective_seat}")
    if strain_norm is None:
        raise ValueError(f"Invalid strain: {strain}")

    side = SIDE_OF[seat]
    side_seats = [s for s in SEATS if SIDE_OF[s] == side]

    hcp_rng = ValueRange(
        sum(state.seats[s].hcp_range.low for s in side_seats),
        sum(state.seats[s].hcp_range.high for s in side_seats),
    )
    ltc_rng = ValueRange(
        sum(state.seats[s].ltc_range.low for s in side_seats),
        sum(state.seats[s].ltc_range.high for s in side_seats),
    )

    if strain_norm == "NT":
        fit_rng = ValueRange(0.0, 0.0)
        low = 6.0 + (hcp_rng.low - 24.0) / 3.0
        high = 6.0 + (hcp_rng.high - 20.0) / 2.8
        reasoning = [
            "NT estimate from side HCP range inferred from bids.",
            "No hidden partner cards are used.",
        ]
    else:
        fit_key = (side, strain_norm)
        fit_obj = state.fit_estimates.get(fit_key)
        if fit_obj is not None:
            fit_rng = fit_obj.length_range
        else:
            s1, s2 = side_seats
            fit_rng = ValueRange(
                float(state.seats[s1].suit_min[strain_norm] + state.seats[s2].suit_min[strain_norm]),
                float(state.seats[s1].suit_max[strain_norm] + state.seats[s2].suit_max[strain_norm]),
            ).clamp(0.0, 13.0)

        fit_bonus_low = _fit_bonus(int(round(fit_rng.low)))
        fit_bonus_high = _fit_bonus(int(round(fit_rng.high)))

        ltc_low = 24.0 - ltc_rng.high
        ltc_high = 24.0 - ltc_rng.low

        hcp_low = 6.0 + (hcp_rng.low - 22.0) / 3.0
        hcp_high = 6.0 + (hcp_rng.high - 18.0) / 2.7

        low = min(ltc_low + 0.5 * fit_bonus_low, hcp_low + 0.3 * fit_bonus_low)
        high = max(ltc_high + 0.7 * fit_bonus_high, hcp_high + 0.5 * fit_bonus_high)

        reasoning = [
            f"Suit estimate from side LTC range {ltc_rng.pretty()} and HCP range {hcp_rng.pretty()}.",
            f"Fit estimate in {strain_norm}: {fit_rng.pretty()} cards.",
            "All partner/opponent values are bid-inferred ranges only.",
        ]

    tricks_rng = ValueRange(max(0.0, min(13.0, low)), max(0.0, min(13.0, high)))
    if tricks_rng.low > tricks_rng.high:
        tricks_rng = ValueRange(tricks_rng.high, tricks_rng.low)

    # Confidence declines as ranges widen.
    uncertainty = (hcp_rng.width / 30.0) + (ltc_rng.width / 12.0) + (fit_rng.width / 13.0)
    confidence = max(0.05, min(0.95, 1.0 - uncertainty / 3.0))

    return SidePotentialEstimate(
        side=side,
        strain=strain_norm,
        hcp_range=hcp_rng,
        ltc_range=ltc_rng,
        fit_range=fit_rng,
        tricks_range=tricks_rng,
        confidence=confidence,
        reasoning=reasoning,
    )


def explain_partner_knowledge(state: AuctionState, perspective_seat: str) -> list[str]:
    """Return human-readable explanation of partner range from public calls."""
    seat = _normalize_seat(perspective_seat)
    if seat is None:
        raise ValueError(f"Invalid perspective seat: {perspective_seat}")

    partner = PARTNER_OF[seat]
    p = state.seats[partner]
    shown = ", ".join(sorted(p.shown_natural_suits)) if p.shown_natural_suits else "ingen tydeligt vist"
    trail = "; ".join(p.evidence_log[-3:]) if p.evidence_log else "ingen endnu"

    return [
        f"Makker ({partner}) estimeres til {p.hcp_range.pretty()} HCP.",
        f"Makker LTC-range: {p.ltc_range.pretty()}, kontroller: {p.controls_range.pretty()}.",
        f"Naturligt viste farver: {shown}.",
        f"Grundlag fra meldinger: {trail}.",
        "Skon bygger kun pa offentlig melding + egen hand, aldrig pa skjulte makkerkort.",
    ]
