import copy

import bridge.opening_bid as opening_bid_module

from bridge.opening_bid import suggest_first_round_for_row
from bridge.opening_bid import suggest_opening_for_row


def _run_with_optional_v2(monkeypatch, row, enabled: bool):
    original_load_yaml_file = opening_bid_module._load_yaml_file

    def _patched_load_yaml_file(path):
        data = original_load_yaml_file(path)
        if path.name != "match_config.yaml":
            return data

        root = copy.deepcopy(data) if isinstance(data, dict) else {}
        match_cfg = dict(root.get("match_config") or {})
        if enabled:
            match_cfg["use_systemdefinition_v2"] = True
        else:
            match_cfg.pop("use_systemdefinition_v2", None)
        root["match_config"] = match_cfg
        return root

    monkeypatch.setattr(opening_bid_module, "_load_yaml_file", _patched_load_yaml_file)
    opening_bid_module._load_bundle.cache_clear()
    try:
        return suggest_first_round_for_row(row)
    finally:
        opening_bid_module._load_bundle.cache_clear()


def _run_opening_with_optional_v2(monkeypatch, row, enabled: bool):
    original_load_yaml_file = opening_bid_module._load_yaml_file

    def _patched_load_yaml_file(path):
        data = original_load_yaml_file(path)
        if path.name != "match_config.yaml":
            return data

        root = copy.deepcopy(data) if isinstance(data, dict) else {}
        match_cfg = dict(root.get("match_config") or {})
        if enabled:
            match_cfg["use_systemdefinition_v2"] = True
        else:
            match_cfg.pop("use_systemdefinition_v2", None)
        root["match_config"] = match_cfg
        return root

    monkeypatch.setattr(opening_bid_module, "_load_yaml_file", _patched_load_yaml_file)
    opening_bid_module._load_bundle.cache_clear()
    try:
        return suggest_opening_for_row(row)
    finally:
        opening_bid_module._load_bundle.cache_clear()


def _call_signature(out):
    seq = list(out.get("call_sequence") or [])
    return [
        (
            str(call.get("dealer") or ""),
            str(call.get("display_bid") or ""),
            str(call.get("rule_id") or ""),
        )
        for call in seq
    ]


def _opening_signature(out):
    return (
        str(out.get("dealer") or ""),
        str(out.get("display_bid") or ""),
        str(out.get("rule_id") or ""),
    )


def test_v2_overlay_matches_legacy_for_stayman_overcall_sequence(monkeypatch):
    row = {
        "dealer": "V",
        "vul": "Alle i zonen",
        "N_hand": "K653.QT96.4.A984",
        "Ø_hand": "J8.AJ.KJ853.Q753",
        "S_hand": "A7.K43.AQ62.KJT2",
        "V_hand": "QT942.8752.T97.6",
    }

    legacy = _run_with_optional_v2(monkeypatch, row, enabled=False)
    v2 = _run_with_optional_v2(monkeypatch, row, enabled=True)

    assert _call_signature(v2) == _call_signature(legacy)


def test_v2_overlay_matches_legacy_for_takeout_double_response_sequence(monkeypatch):
    row = {
        "dealer": "Ø",
        "vul": "Ingen i zonen",
        "Ø_hand": "A84.Q73.AQJ74.85",
        "S_hand": "KQ97.AKJ6.K.9743",
        "V_hand": "J62.T542.T863.K2",
        "N_hand": "T53.Q9872.92.J84",
    }

    legacy = _run_with_optional_v2(monkeypatch, row, enabled=False)
    v2 = _run_with_optional_v2(monkeypatch, row, enabled=True)

    assert _call_signature(v2) == _call_signature(legacy)


def test_v2_overlay_matches_legacy_for_negative_double_sequence(monkeypatch):
    row = {
        "dealer": "N",
        "vul": "Ingen i zonen",
        "N_hand": "KQ3.84.AJ7.KJ52",
        "Ø_hand": "A76.Q95.KT862.Q4",
        "S_hand": "J984.KJ73.842.A7",
        "V_hand": "T52.AT62.953.T98",
    }

    legacy = _run_with_optional_v2(monkeypatch, row, enabled=False)
    v2 = _run_with_optional_v2(monkeypatch, row, enabled=True)

    assert _call_signature(v2) == _call_signature(legacy)


def test_v2_overlay_matches_legacy_for_opening_major_choice(monkeypatch):
    row = {
        "dealer": "N",
        "vul": "Ingen i zonen",
        "N_hand": "AKQJ9.8765.3.K2",
    }

    legacy = _run_opening_with_optional_v2(monkeypatch, row, enabled=False)
    v2 = _run_opening_with_optional_v2(monkeypatch, row, enabled=True)

    assert _opening_signature(v2) == _opening_signature(legacy)


def test_v2_overlay_matches_legacy_for_opening_pass_choice(monkeypatch):
    row = {
        "dealer": "S",
        "vul": "Ingen i zonen",
        "S_hand": "T9842.83.742.953",
    }

    legacy = _run_opening_with_optional_v2(monkeypatch, row, enabled=False)
    v2 = _run_opening_with_optional_v2(monkeypatch, row, enabled=True)

    assert _opening_signature(v2) == _opening_signature(legacy)


def test_v2_overlay_matches_legacy_for_opening_one_nt_choice(monkeypatch):
    row = {
        "dealer": "Ø",
        "vul": "Alle i zonen",
        "Ø_hand": "AKQ2.QJ3.A32.J54",
    }

    legacy = _run_opening_with_optional_v2(monkeypatch, row, enabled=False)
    v2 = _run_opening_with_optional_v2(monkeypatch, row, enabled=True)

    assert _opening_signature(v2) == _opening_signature(legacy)


# ---------------------------------------------------------------------------
# Svag 2-åbninger
# ---------------------------------------------------------------------------

def test_weak_two_spades_normal_range():
    """7 HCP + 6-k spar -> 2♠."""
    row = {"dealer": "S", "S_hand": "AJT984.83.742.53"}
    out = suggest_opening_for_row(row)
    assert out["bid"] == "2S", out["rule_id"]
    assert out["rule_id"] == "weak_two_spades"


def test_weak_two_hearts_three_spades():
    """7 HCP + 6-k hjerter + 3 spar (ikke 4) -> 2♥."""
    row = {"dealer": "N", "N_hand": "832.KQT965.742.5"}
    out = suggest_opening_for_row(row)
    assert out["bid"] == "2H", out["rule_id"]
    assert out["rule_id"] == "weak_two_hearts"


def test_weak_two_spades_five_hcp_three_in_suit():
    """5 HCP med K+Q i spar (5 spar-HCP) -> 2♠ (mindst 3 HCP i farven opfyldt)."""
    row = {"dealer": "V", "V_hand": "KQ9742.83.742.53"}
    out = suggest_opening_for_row(row)
    assert out["bid"] == "2S", out["rule_id"]


def test_weak_two_spades_five_hcp_exactly_three_in_suit_k_only():
    """5 HCP med K i spar (3 spar-HCP) + Q i en sidefarge -> 2♠ (grænsetilfælde OK)."""
    row = {"dealer": "S", "S_hand": "K97532.Q3.742.53"}
    out = suggest_opening_for_row(row)
    assert out["bid"] == "2S", out["rule_id"]


def test_weak_two_spades_five_hcp_only_two_in_suit_rejected():
    """5 HCP men kun Q i spar (2 spar-HCP) -> PAS (for få HCP i farven)."""
    row = {"dealer": "S", "S_hand": "Q97532.83.742.K5"}
    out = suggest_opening_for_row(row)
    assert out["bid"] == "PASS", f"Expected PASS, got {out['bid']}"


def test_weak_two_spades_five_hcp_only_jacks_rejected():
    """5 HCP men kun J+J i spar (2 spar-HCP) -> PAS."""
    row = {"dealer": "S", "S_hand": "J97532.J3.742.Q5"}
    out = suggest_opening_for_row(row)
    assert out["bid"] == "PASS"


def test_weak_two_hearts_four_spades_rejected():
    """6-k hjerter men 4 spar -> PAS (gemmer major)."""
    row = {"dealer": "N", "N_hand": "KJ74.AJT965.2.53"}
    out = suggest_opening_for_row(row)
    # Should not open 2H with 4 spades; 10 HCP also exceeds weak-two range.
    assert out["bid"] != "2H", f"Forventet ikke 2H, fik {out['bid']}"


def test_weak_two_spades_ten_hcp_upper_limit():
    """10 HCP + 6-k spar -> 2♠ (øvre grænse)."""
    row = {"dealer": "Ø", "Ø_hand": "AKQJ65.83.742.53"}
    out = suggest_opening_for_row(row)
    assert out["bid"] == "2S"


def test_weak_two_eleven_hcp_too_strong():
    """11 HCP + 6-k spar -> åbner 1♠ (for stærk til svag 2)."""
    row = {"dealer": "S", "S_hand": "AKQJ65.A83.42.53"}
    out = suggest_opening_for_row(row)
    assert out["bid"] != "2S", f"11 HCP bør ikke åbne 2♠, fik {out['bid']}"


def test_weak_two_v2_matches_legacy_for_spades(monkeypatch):
    """V2 overlay producerer samme 2♠-åbning som legacy."""
    row = {"dealer": "S", "S_hand": "AJT984.83.742.53"}
    legacy = _run_opening_with_optional_v2(monkeypatch, row, enabled=False)
    v2 = _run_opening_with_optional_v2(monkeypatch, row, enabled=True)
    assert _opening_signature(legacy) == _opening_signature(v2)


# ---------------------------------------------------------------------------
# Kompetitative 2-indmeldinger (svag 2-indmelding + Michaels cuebid)
# ---------------------------------------------------------------------------

def _find_call(seq, seat, call_no=1):
    n = 0
    for c in seq:
        if str(c.get("dealer", "")) == seat:
            n += 1
            if n == call_no:
                return c
    return None


def test_weak_two_overcall_spades_after_1C():
    """Ø med 6 spar og 5 HCP indmelder 2♠ efter N åbner 1♣."""
    row = {
        "dealer": "N",
        # N: 14 HCP, 5 klør, 3-2-3-5, under 1NT-område -> åbner 1♣
        "N_hand": "AQ2.43.K32.AJ532",
        # Ø: 5 HCP (K+Q i spar), 6 spar -> svag 2-indmelding
        "Ø_hand": "KQT965.83.742.53",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    n_call = _find_call(seq, "N", 1)
    oe_call = _find_call(seq, "Ø", 1)
    assert n_call is not None and n_call.get("bid") == "1C", f"N bør åbne 1♣, fik {n_call}"
    assert oe_call is not None
    assert oe_call.get("bid") == "2S", oe_call.get("rule_id")
    assert oe_call.get("rule_id") == "weak_two_competitive_overcall"


def test_weak_two_overcall_hearts_after_1C():
    """Ø med 6 hjerter og 5 HCP indmelder 2♥ efter N åbner 1♣."""
    row = {
        "dealer": "N",
        "N_hand": "AQ2.43.K32.AJ532",
        # Ø: 5 HCP (K+Q i hjerter), 6 hjerter, 2 spar -> svag 2♥
        "Ø_hand": "83.KQT965.742.53",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    oe_call = _find_call(seq, "Ø", 1)
    assert oe_call is not None
    assert oe_call.get("bid") == "2H", oe_call.get("rule_id")
    assert oe_call.get("rule_id") == "weak_two_competitive_overcall"


def test_michaels_cuebid_2D_over_1C():
    """Ø med 5-5 i majorerne (7 HCP) indmelder Michaels 2♦ over N 1♣."""
    row = {
        "dealer": "N",
        "N_hand": "AQ2.43.K32.AJ532",
        # Ø: K(3) i spar + K(3)+J(1) i hjerter = 7 HCP, 5 spar + 5 hjerter
        "Ø_hand": "KT965.KJ874.2.53",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    oe_call = _find_call(seq, "Ø", 1)
    assert oe_call is not None
    assert oe_call.get("bid") == "2D", oe_call.get("rule_id")
    assert oe_call.get("rule_id") == "michaels_cuebid_over_minor"


def test_weak_two_overcall_hearts_after_1D():
    """Ø med 6 hjerter og 5 HCP indmelder 2♥ efter N åbner 1♦."""
    row = {
        "dealer": "N",
        # N: 12 HCP, 5 ruder, 3-2-5-3 shape -> åbner 1♦
        "N_hand": "AJ2.43.KJ874.K32",
        "Ø_hand": "83.KQT965.742.53",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    n_call = _find_call(seq, "N", 1)
    oe_call = _find_call(seq, "Ø", 1)
    assert n_call is not None and n_call.get("bid") == "1D", f"N bør åbne 1♦, fik {n_call}"
    assert oe_call is not None
    assert oe_call.get("bid") == "2H", oe_call.get("rule_id")
    assert oe_call.get("rule_id") == "weak_two_competitive_overcall"


def test_two_D_over_1D_blocked_as_michaels_not_natural():
    """Ø med 6 ruder kan IKKE indmelde 2♦ naturligt over 1♦ (er Michaels cuebid)."""
    row = {
        "dealer": "N",
        "N_hand": "AJ2.43.KJ874.K32",
        # Ø: 7 HCP, 6 ruder - 2♦ er modpartens farve/Michaels -> PAS
        "Ø_hand": "83.QJ2.KJT965.53",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    oe_call = _find_call(seq, "Ø", 1)
    assert oe_call is not None
    assert oe_call.get("bid") == "PASS", (
        f"Ø bør ikke indmelde 2♦ naturligt over 1♦, fik {oe_call.get('bid')} "
        f"({oe_call.get('rule_id')})"
    )


def test_weak_two_overcall_spades_after_1H():
    """Ø med 6 spar og 5 HCP indmelder 2♠ efter N åbner 1♥."""
    row = {
        "dealer": "N",
        # N: 11 HCP, 5 hjerter -> åbner 1♥
        "N_hand": "AJ2.KJ853.842.K32",
        "Ø_hand": "KQT965.83.742.53",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    n_call = _find_call(seq, "N", 1)
    oe_call = _find_call(seq, "Ø", 1)
    assert n_call is not None and n_call.get("bid") == "1H", f"N bør åbne 1♥, fik {n_call}"
    assert oe_call is not None
    assert oe_call.get("bid") == "2S", oe_call.get("rule_id")
    assert oe_call.get("rule_id") == "weak_two_competitive_overcall"


# ---------------------------------------------------------------------------
# Svar på minor-åbning: 4-k major vises på 1-plans niveau
# ---------------------------------------------------------------------------

def test_responder_shows_4card_heart_over_1D_not_raises_minor():
    """V svarer 1♥ med 4 hjerter og 4 klør over 1♦ - ikke 2♦ eller 2♣."""
    row = {
        "dealer": "Ø",
        # Ø: balanced 14 HCP, 4S 3H 4D 2C -> opens 1D
        "Ø_hand": "AJ52.K32.KQ54.J2",
        # V: 9 HCP, 2S 4H 3D 4C -> should respond 1H
        "V_hand": "52.AJ87.932.KJ87",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    oe_call = _find_call(seq, "Ø", 1)
    v_call = _find_call(seq, "V", 1)
    assert oe_call is not None and oe_call.get("bid") == "1D", f"Ø bør åbne 1♦, fik {oe_call}"
    assert v_call is not None
    assert v_call.get("bid") == "1H", (
        f"V bør svare 1♥ (4-k hjerter prioriterer over minor-støtte), fik {v_call.get('bid')} "
        f"({v_call.get('rule_id')})"
    )
    assert v_call.get("rule_id") == "responder_one_level_major_over_minor"


def test_responder_shows_4card_heart_over_1C_weak_hand():
    """V svarer 1♥ med 4 hjerter + 4 klør og 7 HCP over 1♣ - 2♣ undlades."""
    row = {
        "dealer": "Ø",
        # Ø: 14 HCP, 5C, below 1NT range -> opens 1C
        "Ø_hand": "AQ2.43.K32.AJ532",
        # V: 7 HCP, 3S 4H 3D 4C -> should respond 1H
        "V_hand": "Q32.KJ87.932.J87",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    v_call = _find_call(seq, "V", 1)
    assert v_call is not None
    assert v_call.get("bid") == "1H", (
        f"V bør svare 1♥ over 1♣, fik {v_call.get('bid')} ({v_call.get('rule_id')})"
    )
    assert v_call.get("rule_id") == "responder_one_level_major_over_minor"


def test_opener_rebids_1nt_balanced_after_1d_1h():
    """Ø genmelder 1NT (jævn 12-14 HCP) efter 1♦-1♥ - viser ikke 4♠."""
    row = {
        "dealer": "Ø",
        # Ø: balanced 14 HCP, 4S 3H 4D 2C -> opens 1D, then 1NT rebid (not 1S)
        "Ø_hand": "AJ52.K32.KQ54.J2",
        "V_hand":  "52.AJ87.932.KJ87",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    oe_call_2 = _find_call(seq, "Ø", 2)
    assert oe_call_2 is not None
    assert oe_call_2.get("bid") == "1NT", (
        f"Ø bør genholde 1NT med jævn hånd, fik {oe_call_2.get('bid')} "
        f"({oe_call_2.get('rule_id')})"
    )
    assert oe_call_2.get("rule_id") == "opener_rebid_1nt_balanced_after_1m_1M"


def test_opener_raises_2h_with_4card_support_after_1d_1h():
    """Ø hæver til 2♥ med 4-k hjertestøtte selvom hånd er jævn."""
    row = {
        "dealer": "Ø",
        # Ø: 3S 4H 4D 2C (13 HCP) -> opens 1D, then raises 2H (4-card support)
        "Ø_hand": "A52.KJ32.KQ54.J2",
        "V_hand":  "52.AJ87.932.KJ87",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    oe_call_2 = _find_call(seq, "Ø", 2)
    assert oe_call_2 is not None
    assert oe_call_2.get("bid") == "2H", (
        f"Ø bør hæve til 2♥ med 4-k støtte, fik {oe_call_2.get('bid')} "
        f"({oe_call_2.get('rule_id')})"
    )


# ---------------------------------------------------------------------------
# Landy og Cappelletti over modparts 1NT
# ---------------------------------------------------------------------------

def test_landy_2c_both_majors_classic():
    """V (EW/nordic_standard) byder 2♣ Landy med 5-5 i majorerne og 11 HCP over S's 1NT."""
    row = {
        "dealer": "N",
        # N/Ø pas -> S åbner 1NT (17 HCP, jævn)
        "N_hand": "5.JT76.JT8543.K9",
        "S_hand": "A86.KQ32.AK6.JT5",
        "Ø_hand": "K743..Q97.Q87632",
        "V_hand": "QJT92.A9854.2.A4",   # 5S + 5H + 11 HCP -> Landy 2C
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    v_call = _find_call(seq, "V", 1)
    assert v_call is not None, "V skal have en melding"
    assert v_call.get("bid") == "2C", (
        f"V bør byde 2♣ Landy (5-5 majorer, 11 HCP), fik {v_call.get('bid')} "
        f"({v_call.get('rule_id')})"
    )
    assert v_call.get("rule_id") == "landy_2c_both_majors"


def test_landy_2c_5_4_majors():
    """V byder 2♣ Landy med 5-4 i majorerne (minimum) og 11 HCP."""
    row = {
        "dealer": "S",
        # S: 15 HCP, balanceret 3-3-3-4 -> åbner 1NT
        "S_hand": "A84.KJ3.AJ2.Q543",
        "V_hand": "QJT92.AK85.73.J4",   # 5S + 4H + 11 HCP -> Landy 2C
        "N_hand": "T73.Q764.K854.T9",
        "Ø_hand": "K65.T2.Q96.AKJ76",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    v_call = _find_call(seq, "V", 1)
    assert v_call is not None
    assert v_call.get("bid") == "2C", (
        f"V bør byde 2♣ Landy (5-4 majorer, 11 HCP), fik {v_call.get('bid')} "
        f"({v_call.get('rule_id')})"
    )
    assert v_call.get("rule_id") == "landy_2c_both_majors"


def test_landy_rejected_only_one_major():
    """V har kun 5 spar og ingen klæbrig hjertekort -> ingen Landy, naturlig indmelding."""
    row = {
        "dealer": "S",
        "S_hand": "AK4.KJ3.AJ2.Q543",   # 1NT
        "V_hand": "QJT982.A3.K74.J4",   # 6S + 2H + 11 HCP -> naturlig 2S, ikke Landy
        "N_hand": "T3.Q764.Q854.T92",
        "Ø_hand": "765.JT52.963.AK76",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    v_call = _find_call(seq, "V", 1)
    assert v_call is not None
    assert v_call.get("bid") != "2C" or v_call.get("rule_id") != "landy_2c_both_majors", (
        f"V bør IKKE byde Landy 2♣ med kun én major, fik {v_call.get('bid')} ({v_call.get('rule_id')})"
    )


def test_cappelletti_2d_both_majors():
    """N (NS/henrik_per_custom) byder 2♦ Cappelletti med 5-5 i majorerne over V's 1NT."""
    row = {
        "dealer": "V",
        # V: 15 HCP, balanceret 3-3-3-4 -> 1NT (EW åbner), N er 2. hånd
        "V_hand": "KQ4.AJ3.K75.QT43",
        "N_hand": "QJT92.AK854.73.4",    # 5S + 5H + 11 HCP -> Cappelletti 2D
        "S_hand": "KT8.Q73.Q98.J653",
        "Ø_hand": "A765.T6.J642.AT2",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    n_call = _find_call(seq, "N", 1)
    assert n_call is not None, "N skal have en melding"
    assert n_call.get("bid") == "2D", (
        f"N bør byde 2♦ Cappelletti (5-5 majorer, 11 HCP), fik {n_call.get('bid')} "
        f"({n_call.get('rule_id')})"
    )
    assert n_call.get("rule_id") == "cappelletti_2d_both_majors"


def test_cappelletti_2h_hearts_minor():
    """N byder 2♥ Cappelletti med 5 hjerter + 4 klør over V's 1NT."""
    row = {
        "dealer": "V",
        # V: 15 HCP, balanceret -> 1NT, N er 2. hånd
        "V_hand": "KQ4.AJ3.K75.QT43",
        "N_hand": "J84.AKQ97.73.QJ87",   # 2H + 5H + 2D + 4C + 12 HCP -> 2H Cappelletti
        "S_hand": "KT72.T63.Q98.T953",
        "Ø_hand": "A965.85.JT642.A4",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    n_call = _find_call(seq, "N", 1)
    assert n_call is not None
    assert n_call.get("bid") == "2H", (
        f"N bør byde 2♥ Cappelletti (5H + 4C, 12 HCP), fik {n_call.get('bid')} "
        f"({n_call.get('rule_id')})"
    )
    assert n_call.get("rule_id") == "cappelletti_2h_hearts_minor"


def test_cappelletti_2s_spades_minor():
    """N byder 2♠ Cappelletti med 5 spar + 4 ruder over V's 1NT."""
    row = {
        "dealer": "V",
        # V: 15 HCP, balanceret -> 1NT, N er 2. hånd
        "V_hand": "KQ4.AJ3.K75.QT43",
        "N_hand": "AKJ97.43.QJT8.J4",    # 5S + 2H + 4D + 2C + 12 HCP -> 2S Cappelletti
        "S_hand": "T62.Q965.632.A97",
        "Ø_hand": "854.KT87.A97.T653",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    n_call = _find_call(seq, "N", 1)
    assert n_call is not None
    assert n_call.get("bid") == "2S", (
        f"N bør byde 2♠ Cappelletti (5S + 4D, 12 HCP), fik {n_call.get('bid')} "
        f"({n_call.get('rule_id')})"
    )
    assert n_call.get("rule_id") == "cappelletti_2s_spades_minor"


def test_cappelletti_2c_one_suiter():
    """N byder 2♣ Cappelletti (enfarvet) med 6 ruder og 11 HCP over V's 1NT."""
    row = {
        "dealer": "V",
        # V: 15 HCP, balanceret -> 1NT, N er 2. hånd
        "V_hand": "KQ4.AJ3.K75.QT43",
        "N_hand": "J84.T3.AKQT76.J4",    # 2S+2H+6D+2C + 11 HCP, ingen 5-4 major/minor -> 2C enfarvet
        "S_hand": "KT72.Q965.32.T975",
        "Ø_hand": "A965.AK87.T84.632",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    n_call = _find_call(seq, "N", 1)
    assert n_call is not None
    assert n_call.get("bid") == "2C", (
        f"N bør byde 2♣ Cappelletti (enfarvet 6D, 11 HCP), fik {n_call.get('bid')} "
        f"({n_call.get('rule_id')})"
    )
    assert n_call.get("rule_id") == "cappelletti_2c_one_suiter"


# ---------------------------------------------------------------------------
# Landy responses (partner byder Landy 2♣ = begge majorer)
# ---------------------------------------------------------------------------

def test_landy_response_2s_prefer_spades():
    """Ø svarer 2♠ til V's Landy 2♣ med 4 spar, 0 hjerter og kun 5 HCP (lavt nok til signoff)."""
    row = {
        "dealer": "N",
        "N_hand": "5.JT76.JT8543.K9",
        "S_hand": "A86.KQ32.AK6.JT5",
        "Ø_hand": "K743..9763.Q8532",   # 4S + 0H + 5 HCP -> støttepct 5+3=8 < 10 -> 2S
        "V_hand": "QJT92.A9854.2.A4",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    # Ø's 1st call = PASS (som åbner); Ø's 2nd call = Landy-svar
    oe_call = _find_call(seq, "Ø", 2)
    assert oe_call is not None
    assert oe_call.get("bid") == "2S", (
        f"Ø bør svare 2♠ til Landy (4S, 0H, 5 HCP), fik {oe_call.get('bid')} ({oe_call.get('rule_id')})"
    )
    assert oe_call.get("rule_id") == "landy_response_2s_prefer_spades"


def test_landy_response_3s_invitation_with_void():
    """Ø svarer 3♠ (invitation) med 4 spar, renonce i hjerter og 7 HCP (spil 1-casen).

    7 HCP + 3 distributionsbonus (renonce i V's sidefarve hjerter) = 10 støttepkt -> invitation.
    """
    row = {
        "dealer": "N",
        "N_hand": "5.JT76.JT8543.K9",
        "S_hand": "A86.KQ32.AK6.JT5",
        "Ø_hand": "K743..Q97.Q87632",   # 4S + 0H + 7 HCP + renonce -> 10 støttepkt -> 3S
        "V_hand": "QJT92.A9854.2.A4",
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    oe_call = _find_call(seq, "Ø", 2)
    assert oe_call is not None
    assert oe_call.get("bid") == "3S", (
        f"Ø bør svare 3♠ (invitation, 7 HCP + renonce) til Landy, fik {oe_call.get('bid')} ({oe_call.get('rule_id')})"
    )
    assert oe_call.get("rule_id") == "landy_response_3s_invitation"


def test_landy_response_2h_prefer_hearts():
    """Ø svarer 2♥ til V's Landy 2♣ med 0 spar og 4 hjerter."""
    row = {
        "dealer": "S",
        "S_hand": "A84.KJ3.AJ2.Q543",   # 15 HCP -> 1NT
        "V_hand": "QJT92.AK854.2.A4",   # Landy 2C (5S+5H)
        "N_hand": "T73.Q764.K854.T9",
        "Ø_hand": ".QT986.Q9632.J87",   # 0S + 5H + 5 HCP -> 2H
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    # Ø er dealer her, så Ø's 1. kald er PAS (åbner), 2. kald er Landy-svar
    oe_call = _find_call(seq, "Ø", 1)  # dealer=S: Ø har ingen PAS før Landy-svar
    assert oe_call is not None
    assert oe_call.get("bid") == "2H", (
        f"Ø bør svare 2♥ til Landy (0S, 5H), fik {oe_call.get('bid')} ({oe_call.get('rule_id')})"
    )
    assert oe_call.get("rule_id") == "landy_response_2h_prefer_hearts"


def test_landy_response_2d_equal_majors():
    """Ø svarer 2♦ (kunstig) med 3-3 i majorerne – beder V vælge."""
    row = {
        "dealer": "S",
        "S_hand": "A84.KJ3.AJ2.Q543",   # 15 HCP -> 1NT
        "V_hand": "QJT92.AK854.2.A4",   # Landy 2C
        "N_hand": "T73.Q764.K854.T9",
        "Ø_hand": "K82.Q93.Q963.J87",   # 3S + 3H + 8 HCP -> 2D (equal majors)
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    # dealer=S: Ø har ingen åbner-PAS, første kald = Landy-svar
    oe_call = _find_call(seq, "Ø", 1)
    assert oe_call is not None
    assert oe_call.get("bid") == "2D", (
        f"Ø bør svare 2♦ med 3-3 i majorerne, fik {oe_call.get('bid')} ({oe_call.get('rule_id')})"
    )
    assert "landy_response_2d" in oe_call.get("rule_id", "")


def test_landy_response_3h_invitation():
    """Ø svarer 3♥ (invitation) med 4 hjerter og 10 HCP til V's Landy."""
    row = {
        "dealer": "S",
        "S_hand": "A84.KJ3.AJ2.Q543",   # 15 HCP -> 1NT
        "V_hand": "KJT92.AK854.2.A4",   # Landy 2C (11 HCP)
        "N_hand": "T73.Q764.K854.T9",
        "Ø_hand": "Q82.AJT6.Q963.J8",   # 3S + 4H + 10 HCP (A+J hjerter) -> 3H invitation
    }
    out = suggest_first_round_for_row(row)
    seq = out.get("call_sequence", [])
    # dealer=S: Ø har ingen åbner-PAS, første kald = Landy-svar
    oe_call = _find_call(seq, "Ø", 1)
    assert oe_call is not None
    assert oe_call.get("bid") == "3H", (
        f"Ø bør svare 3♥ (invitation, 4H 10 HCP) til Landy, fik {oe_call.get('bid')} ({oe_call.get('rule_id')})"
    )
    assert oe_call.get("rule_id") == "landy_response_3h_invitation"