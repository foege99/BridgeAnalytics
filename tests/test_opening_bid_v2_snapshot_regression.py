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