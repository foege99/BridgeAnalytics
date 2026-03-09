from bridge.auction_state import (
    BidEvidence,
    ValueRange,
    apply_bid_evidence,
    create_auction_state,
    estimate_side_potential,
    explain_partner_knowledge,
)


def test_create_auction_state_keeps_partner_unknown():
    state = create_auction_state(
        perspective_seat="Ø",
        dealer="S",
        vulnerability="Ingen i zonen",
        own_hand_dot="A7653.T65.KQ43.8",
    )

    own = state.seats["Ø"]
    partner = state.seats["V"]

    assert own.known_hand is True
    assert own.hcp_range.low == own.hcp_range.high

    assert partner.known_hand is False
    assert partner.hcp_range.low == 0
    assert partner.hcp_range.high == 37
    assert partner.suit_min["S"] == 0
    assert partner.suit_max["S"] == 13


def test_apply_bid_evidence_updates_partner_range_and_fit():
    state = create_auction_state(
        perspective_seat="Ø",
        dealer="S",
        vulnerability="Ingen i zonen",
        own_hand_dot="A7653.T65.KQ43.8",
    )

    evidence = BidEvidence(
        source="V open 1S",
        hcp_range=ValueRange(11, 21),
        suit_min={"S": 5},
        natural_strain="S",
        notes=["Opening style narrow range"],
    )
    apply_bid_evidence(state, "V", "1S", evidence)

    partner = state.seats["V"]
    assert partner.hcp_range.low == 11
    assert partner.hcp_range.high == 21
    assert partner.suit_min["S"] >= 5

    fit = state.fit_estimates[("ØV", "S")]
    assert fit.length_range.low >= 10
    assert fit.confidence > 0


def test_partner_explanation_and_side_potential_are_range_based():
    state = create_auction_state(
        perspective_seat="Ø",
        dealer="S",
        vulnerability="Ingen i zonen",
        own_hand_dot="A7653.T65.KQ43.8",
    )
    apply_bid_evidence(
        state,
        "V",
        "1S",
        BidEvidence(
            source="V open 1S",
            hcp_range=ValueRange(11, 21),
            suit_min={"S": 5},
            natural_strain="S",
        ),
    )

    lines = explain_partner_knowledge(state, "Ø")
    text = " ".join(lines).lower()
    assert "11-21" in text
    assert "skjulte" in text

    est = estimate_side_potential(state, "Ø", "S")
    assert 0 <= est.tricks_range.low <= est.tricks_range.high <= 13
    assert est.side == "ØV"
    assert any("range" in line.lower() for line in est.reasoning)
