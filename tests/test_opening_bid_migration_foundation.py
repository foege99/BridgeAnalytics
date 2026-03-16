import pytest

import bridge.opening_bid as opening_bid_module


@pytest.fixture(autouse=True)
def _clear_opening_bid_bundle_cache():
    opening_bid_module._load_bundle.cache_clear()
    yield
    opening_bid_module._load_bundle.cache_clear()


def _minimal_systemdefinition(version: str = "0.9") -> dict:
    return {
        "system_library": {
            "test_system": {
                "meta": {
                    "name": "Test System",
                    "version": version,
                },
                "shape_definitions": {},
                "opening_threshold_profiles": {},
                "threshold_rule_definitions": {},
                "opening_decision_flow": [],
                "notrump_openings": {},
                "major_opening_logic": [],
                "minor_opening_logic": [],
                "one_nt_response_system": {},
                "hand_strength_model": {},
                "competitive_bidding": {},
            }
        }
    }


def test_systemdefinition_schema_version_prefers_explicit_schema_version():
    raw = _minimal_systemdefinition(version="0.9")
    raw["system_library"]["test_system"]["meta"]["_schema_version"] = "1.0"

    assert opening_bid_module._systemdefinition_schema_version(raw) == "1.0"


def test_validate_systemdefinition_file_warns_about_missing_runtime_keys():
    raw = {
        "system_library": {
            "test_system": {
                "meta": {"version": "0.9"},
            }
        }
    }

    warnings = opening_bid_module._validate_systemdefinition_file(raw, "test.yaml")

    assert any("competitive_bidding" in msg for msg in warnings)
    assert any("shape_definitions" in msg for msg in warnings)


def test_validate_systemdefinition_file_warns_about_invalid_opening_model_type():
    raw = _minimal_systemdefinition(version="1.0")
    raw["system_library"]["test_system"]["opening_model"] = []

    warnings = opening_bid_module._validate_systemdefinition_file(raw, "test.yaml")

    assert any("opening_model" in msg for msg in warnings)


def test_load_bundle_uses_legacy_systemdefinition_by_default(monkeypatch):
    legacy = _minimal_systemdefinition(version="0.9")
    v2 = _minimal_systemdefinition(version="0.9")
    v2["system_library"]["test_system"]["meta"]["_schema_version"] = "1.0"

    def _fake_load_yaml_file(path):
        name = path.name
        if name == "systemdefinition.yaml":
            return legacy
        if name == "systemdefinition_v2.yaml":
            return v2
        if name == "system_profiles.yaml":
            return {"system_profiles": {"default": {"system_definition": "test_system"}}}
        if name == "match_config.yaml":
            return {"match_config": {"NS_system": "default", "EW_system": "default"}}
        if name == "pair_registry.yaml":
            return {"default_system_profile": "default"}
        return {}

    monkeypatch.setattr(opening_bid_module, "_load_yaml_file", _fake_load_yaml_file)

    bundle = opening_bid_module._load_bundle()

    assert bundle["systemdefinition_active"] == legacy
    assert bundle["systemdefinition_schema_version"] == "0.9"
    assert bundle["migration_warnings"] == ()


def test_load_bundle_can_prefer_v2_when_enabled(monkeypatch):
    legacy = _minimal_systemdefinition(version="0.9")
    v2 = _minimal_systemdefinition(version="0.9")
    v2["system_library"]["test_system"]["meta"]["_schema_version"] = "1.0"

    def _fake_load_yaml_file(path):
        name = path.name
        if name == "systemdefinition.yaml":
            return legacy
        if name == "systemdefinition_v2.yaml":
            return v2
        if name == "system_profiles.yaml":
            return {"system_profiles": {"default": {"system_definition": "test_system"}}}
        if name == "match_config.yaml":
            return {
                "match_config": {
                    "NS_system": "default",
                    "EW_system": "default",
                    "use_systemdefinition_v2": True,
                }
            }
        if name == "pair_registry.yaml":
            return {"default_system_profile": "default"}
        return {}

    monkeypatch.setattr(opening_bid_module, "_load_yaml_file", _fake_load_yaml_file)

    bundle = opening_bid_module._load_bundle()
    picked = opening_bid_module._pick_system_def({"system_definition": "test_system"}, bundle)

    assert bundle["systemdefinition_active"] == v2
    assert bundle["systemdefinition_schema_version"] == "1.0"
    assert picked["meta"]["_schema_version"] == "1.0"


def test_load_bundle_merges_v2_overlay_with_legacy_base(monkeypatch):
    legacy = _minimal_systemdefinition(version="0.9")
    legacy["system_library"]["test_system"]["competitive_bidding"] = {
        "takeout_double": {"minimum_strength": {"hcp_min": 12}},
    }
    v2_overlay = {
        "system_library": {
            "test_system": {
                "meta": {
                    "_schema_version": "1.0",
                    "version": "1.0",
                },
                "competitive_bidding": {
                    "schema": "context_node_rules",
                    "contexts": {
                        "doubles": {
                            "nodes": {
                                "takeout": {
                                    "minimum_strength": {"hcp_min": 14},
                                }
                            }
                        }
                    }
                },
            }
        }
    }

    def _fake_load_yaml_file(path):
        name = path.name
        if name == "systemdefinition.yaml":
            return legacy
        if name == "systemdefinition_v2.yaml":
            return v2_overlay
        if name == "system_profiles.yaml":
            return {"system_profiles": {"default": {"system_definition": "test_system"}}}
        if name == "match_config.yaml":
            return {
                "match_config": {
                    "NS_system": "default",
                    "EW_system": "default",
                    "use_systemdefinition_v2": True,
                }
            }
        if name == "pair_registry.yaml":
            return {"default_system_profile": "default"}
        return {}

    monkeypatch.setattr(opening_bid_module, "_load_yaml_file", _fake_load_yaml_file)

    bundle = opening_bid_module._load_bundle()
    picked = opening_bid_module._pick_system_def({"system_definition": "test_system"}, bundle)

    assert picked["shape_definitions"] == {}
    assert picked["competitive_bidding"]["schema"] == "context_node_rules"
    assert bundle["systemdefinition_schema_version"] == "1.0"


def test_competitive_bidding_v2_adapter_preserves_current_getters(monkeypatch):
    v2_sys_def = _minimal_systemdefinition(version="1.0")
    v2_sys_def["system_library"]["test_system"]["competitive_bidding"] = {
        "schema": "context_node_rules",
        "contexts": {
            "doubles": {
                "interpretation_priority": {
                    "order": [
                        "lead_directing_after_artificial_opponent_call",
                        "takeout_when_partner_unbid_or_only_passed",
                        "negative_when_partner_has_contract_bid",
                        "penalty_as_fallback",
                    ]
                },
                "nodes": {
                    "lead_directing": {
                        "enabled_by_profile_flag": True,
                    },
                    "takeout": {
                        "minimum_strength": {"hcp_min": 14},
                    },
                    "negative": {
                        "enabled": True,
                        "applies_up_to": {"level": "2S"},
                        "minimum_strength": {"hcp_min": 7},
                    },
                    "penalty": {
                        "sacrifice_evaluation": {
                            "sacrifice_detection": {
                                "own_game_likely_when": {"estimated_combined_ns_hcp_min": 25}
                            }
                        }
                    },
                },
            },
            "overcalls": {
                "natural": {
                    "one_notrump": {
                        "strength": {"hcp_range": [16, 18]},
                        "shape": "balanced",
                        "requirements": {"stopper_in_opponents_suit": True},
                    }
                }
            },
            "responses": {
                "takeout_double": {
                    "new_suit_response": {
                        "forcing": False,
                    }
                }
            },
        },
    }

    monkeypatch.setattr(
        opening_bid_module,
        "_system_def_for_seat",
        lambda _seat: v2_sys_def["system_library"]["test_system"],
    )

    comp = opening_bid_module._competitive_bidding_for_seat("N")
    neg = opening_bid_module._negative_double_params_for_seat("N")
    one_nt = opening_bid_module._one_nt_overcall_params_for_seat("N")

    assert comp["takeout_double"]["minimum_strength"]["hcp_min"] == 14
    assert comp["doubles_interpretation_priority"]["order"][0] == "lead_directing_after_artificial_opponent_call"
    assert neg["hcp_min"] == 7
    assert one_nt["hcp_min"] == 16
    assert one_nt["hcp_max"] == 18


def test_opening_flow_v2_adapter_prefers_context_node_steps_over_legacy_list():
    sys_def = {
        "opening_decision_flow": [
            {"step": "legacy_threshold"},
            {"step": "legacy_pass"},
        ],
        "opening_model": {
            "schema": "context_node_rules",
            "contexts": {
                "decision_flow": {
                    "nodes": {
                        "first_round_opening": {
                            "steps": [
                                {"id": "evaluate_opening_threshold"},
                                {"id": "evaluate_1NT_opening"},
                                {"id": "evaluate_major_opening"},
                                {"id": "evaluate_minor_opening"},
                                {"id": "if_no_opening_then_pass"},
                            ]
                        }
                    }
                }
            },
        },
    }

    steps = opening_bid_module._opening_decision_flow_steps(sys_def)

    assert steps == [
        "evaluate_opening_threshold",
        "evaluate_1NT_opening",
        "evaluate_major_opening",
        "evaluate_minor_opening",
        "if_no_opening_then_pass",
    ]