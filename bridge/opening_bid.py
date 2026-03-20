"""Opening-bid suggestion engine driven by YAML system configuration.

MVP scope:
- Suggest only the dealer's first call from a fresh auction.
- Return one bid (e.g., PASS, 1NT, 1S, 1H, 1D, 1C).
- Keep YAML declarative; Python evaluates and selects.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Mapping

from bridge.auction_state import (
    BidEvidence,
    ValueRange,
    apply_bid_evidence,
    create_auction_state,
    estimate_side_potential,
    explain_partner_knowledge,
)
from bridge.hand_eval import hcp as calc_hcp
from bridge.hand_eval import parse_hand


def _normalize_seat(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s == "E":
        return "Ø"
    if s == "W":
        return "V"
    if s in ("N", "S", "Ø", "V"):
        return s
    return None


def _seat_side(seat: str) -> str:
    return "NS" if seat in ("N", "S") else "ØV"


def _to_display_bid(bid: str) -> str:
    b = str(bid or "").strip().upper().replace(" ", "")
    if b in ("PASS", "PAS"):
        return "PAS"
    if b.endswith("NT"):
        return b
    suit_map = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
    if len(b) >= 2 and b[0].isdigit() and b[-1] in suit_map:
        return f"{b[:-1]}{suit_map[b[-1]]}"
    return str(bid)


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:
        return {}

    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _deep_merge_dicts(base: Any, overlay: Any) -> dict[str, Any]:
    base_map = _mapping_dict(base)
    overlay_map = _mapping_dict(overlay)
    if not base_map:
        return dict(overlay_map)
    if not overlay_map:
        return dict(base_map)

    out = dict(base_map)
    for key, overlay_value in overlay_map.items():
        base_value = out.get(key)
        if isinstance(base_value, Mapping) and isinstance(overlay_value, Mapping):
            out[key] = _deep_merge_dicts(base_value, overlay_value)
        else:
            out[key] = overlay_value
    return out


def _system_library_from_raw(raw_sysdef: Any) -> dict[str, Any]:
    sys_lib = (_mapping_dict(raw_sysdef).get("system_library", {}) or {})
    return _mapping_dict(sys_lib)


def _systemdefinition_schema_version(raw_sysdef: Any) -> str:
    sys_lib = _system_library_from_raw(raw_sysdef)
    if not sys_lib:
        return "0.9"

    first_name = next(iter(sys_lib.keys()), None)
    first_sys = _mapping_dict(sys_lib.get(first_name)) if first_name is not None else {}
    meta = _mapping_dict(first_sys.get("meta"))

    version = str(
        meta.get("_schema_version")
        or meta.get("schema_version")
        or meta.get("version")
        or "0.9"
    ).strip()
    return version or "0.9"


def _validate_systemdefinition_file(raw_sysdef: Any, source_name: str) -> list[str]:
    warnings: list[str] = []
    sys_lib = _system_library_from_raw(raw_sysdef)
    if not sys_lib:
        return [f"{source_name}: mangler system_library eller kunne ikke indlaeses som mapping."]

    runtime_required = (
        "meta",
        "shape_definitions",
        "opening_threshold_profiles",
        "threshold_rule_definitions",
        "notrump_openings",
        "major_opening_logic",
        "minor_opening_logic",
        "one_nt_response_system",
        "hand_strength_model",
        "competitive_bidding",
    )

    for sys_name, raw_sys in sys_lib.items():
        sys_def = _mapping_dict(raw_sys)
        if not sys_def:
            warnings.append(f"{source_name}:{sys_name} er ikke et mapping.")
            continue

        for key in runtime_required:
            if key not in sys_def:
                warnings.append(f"{source_name}:{sys_name} mangler runtime-noeglen '{key}'.")

        flow = sys_def.get("opening_decision_flow")
        if flow is not None and not isinstance(flow, list):
            warnings.append(f"{source_name}:{sys_name} har opening_decision_flow i ugyldigt format.")

        opening_model = sys_def.get("opening_model")
        if opening_model is not None and not isinstance(opening_model, Mapping):
            warnings.append(f"{source_name}:{sys_name} har opening_model i ugyldigt format.")

        competitive = sys_def.get("competitive_bidding")
        if competitive is not None and not isinstance(competitive, Mapping):
            warnings.append(f"{source_name}:{sys_name} har competitive_bidding i ugyldigt format.")

    return warnings


def _use_systemdefinition_v2(bundle: Mapping[str, Any]) -> bool:
    match_cfg = _mapping_dict(_mapping_dict(bundle.get("match_config")).get("match_config"))
    return bool(match_cfg.get("use_systemdefinition_v2")) and bool(bundle.get("systemdefinition_v2"))


def _active_systemdefinition_from_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if _use_systemdefinition_v2(bundle):
        return _mapping_dict(bundle.get("systemdefinition_v2_merged") or bundle.get("systemdefinition_v2"))
    return _mapping_dict(bundle.get("systemdefinition"))


@lru_cache(maxsize=1)
def _load_bundle() -> dict[str, Any]:
    base = Path(__file__).resolve().parent
    raw_systemdefinition = _load_yaml_file(base / "systemdefinition.yaml")
    raw_systemdefinition_v2 = _load_yaml_file(base / "systemdefinition_v2.yaml")
    merged_systemdefinition_v2 = _deep_merge_dicts(raw_systemdefinition, raw_systemdefinition_v2)
    system_profiles = _load_yaml_file(base / "system_profiles.yaml")
    match_config = _load_yaml_file(base / "match_config.yaml")
    pair_registry = _load_yaml_file(base / "pair_registry.yaml")

    out = {
        "systemdefinition": raw_systemdefinition,
        "systemdefinition_v2": raw_systemdefinition_v2,
        "systemdefinition_v2_merged": merged_systemdefinition_v2,
        "system_profiles": system_profiles,
        "match_config": match_config,
        "pair_registry": pair_registry,
    }

    warnings = _validate_systemdefinition_file(raw_systemdefinition, "systemdefinition.yaml")
    if raw_systemdefinition_v2:
        warnings.extend(_validate_systemdefinition_file(merged_systemdefinition_v2, "systemdefinition_v2.yaml"))

    active_systemdefinition = _active_systemdefinition_from_bundle(out)
    out["systemdefinition_active"] = active_systemdefinition
    out["systemdefinition_schema_version"] = _systemdefinition_schema_version(active_systemdefinition)
    out["migration_warnings"] = tuple(warnings)

    return out


def _shape_matches(shape_shdc: tuple[int, int, int, int], allowed_shapes: list[Any]) -> bool:
    target = sorted(shape_shdc, reverse=True)
    for shp in allowed_shapes or []:
        if not isinstance(shp, list) and not isinstance(shp, tuple):
            continue
        try:
            vals = [int(x) for x in shp]
        except Exception:
            continue
        if sorted(vals, reverse=True) == target:
            return True
    return False


def _build_context(hand_dot: str) -> dict[str, Any]:
    ph = parse_hand(str(hand_dot))
    spades = ph.lengths["S"]
    hearts = ph.lengths["H"]
    diamonds = ph.lengths["D"]
    clubs = ph.lengths["C"]
    lengths_sorted = sorted([spades, hearts, diamonds, clubs], reverse=True)

    return {
        "hcp": int(calc_hcp(ph)),
        "spades": int(spades),
        "hearts": int(hearts),
        "diamonds": int(diamonds),
        "clubs": int(clubs),
        "longest_1": int(lengths_sorted[0]),
        "longest_2": int(lengths_sorted[1]),
        "shape_shdc": (int(spades), int(hearts), int(diamonds), int(clubs)),
        "clubs_honors_AKQJ": sum(1 for ch in ph.suits["C"] if ch in "AKQJ"),
        "diamonds_honors_AKQJ": sum(1 for ch in ph.suits["D"] if ch in "AKQJ"),
    }


def _shape_text(ctx: Mapping[str, Any]) -> str:
    return (
        f"S{int(ctx['spades'])}-H{int(ctx['hearts'])}-"
        f"D{int(ctx['diamonds'])}-C{int(ctx['clubs'])}"
    )


def _pick_profile(dealer: str, bundle: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    profiles = (bundle.get("system_profiles", {}) or {}).get("system_profiles", {}) or {}
    match_cfg = (bundle.get("match_config", {}) or {}).get("match_config", {}) or {}
    pair_reg = bundle.get("pair_registry", {}) or {}

    side = _seat_side(dealer)
    key = "NS_system" if side == "NS" else "EW_system"
    profile_name = match_cfg.get(key)

    if isinstance(profile_name, str) and profile_name in profiles:
        return profile_name, profiles[profile_name]

    default_name = pair_reg.get("default_system_profile")
    if isinstance(default_name, str) and default_name in profiles:
        return default_name, profiles[default_name]

    if profiles:
        first_name = next(iter(profiles.keys()))
        return first_name, profiles.get(first_name, {}) or {}

    return None, {}


def _pick_system_def(profile_cfg: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    active_sysdef = _active_systemdefinition_from_bundle(bundle)
    sys_lib = _system_library_from_raw(active_sysdef or bundle.get("systemdefinition_active") or bundle.get("systemdefinition"))
    if not sys_lib:
        return {}

    sys_name = profile_cfg.get("system_definition")
    if isinstance(sys_name, str) and sys_name in sys_lib:
        return sys_lib[sys_name] or {}

    first_name = next(iter(sys_lib.keys()))
    return sys_lib.get(first_name, {}) or {}


def _evaluate_opening_threshold(
    ctx: dict[str, Any],
    profile_cfg: dict[str, Any],
    sys_def: dict[str, Any],
) -> tuple[bool, str]:
    style = profile_cfg.get("opening_threshold_style")
    profiles = sys_def.get("opening_threshold_profiles", {}) or {}
    threshold_cfg = profiles.get(style) or profiles.get("nordic_default") or {}
    first_seat_cfg = threshold_cfg.get("first_seat", {}) or {}
    rule = str(first_seat_cfg.get("rule") or "").strip()

    if not rule:
        return True, "Threshold: ingen specifik regel (OK)."

    if rule == "hcp_minimum":
        min_hcp = first_seat_cfg.get("min_hcp")
        if min_hcp is None:
            defs = sys_def.get("threshold_rule_definitions", {}) or {}
            min_hcp = (
                ((defs.get("hcp_minimum", {}) or {}).get("parameters", {}) or {}).get("min_hcp", 12)
            )
        ok = int(ctx["hcp"]) >= int(min_hcp)
        return ok, f"Threshold: HCP-minimum {int(ctx['hcp'])}>={int(min_hcp)} ({'OK' if ok else 'NEJ'})."

    if rule == "rule_of_20":
        score = int(ctx["hcp"]) + int(ctx["longest_1"]) + int(ctx["longest_2"])
        ok = score >= 20
        return (
            ok,
            f"Threshold: Rule of 20 = {int(ctx['hcp'])}+{int(ctx['longest_1'])}+{int(ctx['longest_2'])}={score} ({'OK' if ok else 'NEJ'}).",
        )

    if rule == "rule_of_15":
        score = int(ctx["hcp"]) + int(ctx["spades"])
        ok = score >= 15
        return ok, f"Threshold: Rule of 15 = {int(ctx['hcp'])}+{int(ctx['spades'])}={score} ({'OK' if ok else 'NEJ'})."

    if rule == "light_open":
        longest = max(int(ctx["spades"]), int(ctx["hearts"]), int(ctx["diamonds"]), int(ctx["clubs"]))
        ok = int(ctx["hcp"]) >= 8 and longest >= 5
        return (
            ok,
            f"Threshold: light_open med HCP={int(ctx['hcp'])} og længste farve={longest} ({'OK' if ok else 'NEJ'}).",
        )

    # Unknown threshold rule: conservative fallback.
    ok = int(ctx["hcp"]) >= 12
    return ok, f"Threshold: ukendt regel '{rule}', fallback HCP>=12 ({'OK' if ok else 'NEJ'})."


def _evaluate_one_nt(
    ctx: dict[str, Any],
    profile_cfg: dict[str, Any],
    sys_def: dict[str, Any],
) -> tuple[str | None, str | None, str]:
    nt = ((sys_def.get("notrump_openings", {}) or {}).get("one_nt", {}) or {})
    strength = nt.get("strength", {}) or {}
    min_hcp = int(strength.get("min_hcp", 15))
    max_hcp = int(strength.get("max_hcp", 17))

    if not (min_hcp <= int(ctx["hcp"]) <= max_hcp):
        return None, None, f"1NT-check: afvist (HCP {int(ctx['hcp'])} udenfor {min_hcp}-{max_hcp})."

    shapes = sys_def.get("shape_definitions", {}) or {}
    shape_ref = nt.get("shape_reference", "balanced_shapes")
    allowed = shapes.get(shape_ref, shapes.get("balanced_shapes", []))
    if not _shape_matches(ctx["shape_shdc"], allowed):
        return None, None, f"1NT-check: afvist (shape {_shape_text(ctx)} er ikke balanceret)."

    policy = profile_cfg.get("one_nt_major_policy", "deny_any_5_card_major")
    spades = int(ctx["spades"])
    hearts = int(ctx["hearts"])

    if policy == "allow_5m_except_opposite_major_doubleton":
        if (spades == 5 and hearts == 2) or (hearts == 5 and spades == 2):
            return None, None, "1NT-check: afvist (5-k major med modsatte major doubleton)."
        return "1NT", "one_nt_allow_5m_except_opposite_major_doubleton", "1NT-check: OK under allow_5m-policy."

    if policy == "deny_any_5_card_major":
        if spades <= 4 and hearts <= 4:
            return "1NT", "one_nt_deny_any_5_card_major", "1NT-check: OK (ingen 5-k major)."
        return None, None, "1NT-check: afvist (5-k major ikke tilladt under deny_any_5_card_major)."

    # Unknown NT policy: fallback to deny any 5-card major.
    if spades <= 4 and hearts <= 4:
        return "1NT", "one_nt_fallback_deny_5m", "1NT-check: OK via fallback-policy."

    return None, None, "1NT-check: afvist under fallback-policy."


def _safe_eval_condition(expr: str, ctx: Mapping[str, Any]) -> bool:
    if not expr:
        return False
    safe_locals = {
        "hcp": int(ctx["hcp"]),
        "spades": int(ctx["spades"]),
        "hearts": int(ctx["hearts"]),
        "diamonds": int(ctx["diamonds"]),
        "clubs": int(ctx["clubs"]),
        "clubs_honors_AKQJ": int(ctx["clubs_honors_AKQJ"]),
        "diamonds_honors_AKQJ": int(ctx["diamonds_honors_AKQJ"]),
    }
    try:
        return bool(eval(expr, {"__builtins__": {}}, safe_locals))
    except Exception:
        return False


def _exception_matches(exception_if: Mapping[str, Any], ctx: Mapping[str, Any]) -> bool:
    for key, expected in (exception_if or {}).items():
        if key.endswith("_min"):
            base = key[:-4]
            if float(ctx.get(base, -10**9)) < float(expected):
                return False
            continue
        if key.endswith("_max"):
            base = key[:-4]
            if float(ctx.get(base, 10**9)) > float(expected):
                return False
            continue
        if ctx.get(key) != expected:
            return False
    return True


def _evaluate_suit_opening(
    ctx: dict[str, Any],
    profile_cfg: dict[str, Any],
    sys_def: dict[str, Any],
    logic_key: str,
    style_key: str,
) -> tuple[str | None, str | None, str]:
    style = profile_cfg.get(style_key)
    logic = sys_def.get(logic_key, []) or []
    label = "Major" if style_key == "major_style" else "Minor"
    style_block_found = False

    for block in logic:
        when = block.get("when", {}) or {}
        if when.get(style_key) != style:
            continue
        style_block_found = True

        for rule in (block.get("rules", []) or []):
            cond = str(rule.get("condition") or "").strip()
            if not _safe_eval_condition(cond, ctx):
                continue

            open_bid = rule.get("open")
            if isinstance(open_bid, str):
                return open_bid, rule.get("id"), f"{label}-check: match {rule.get('id')} -> {_to_display_bid(open_bid)}."

            default_open = rule.get("default_open")
            if isinstance(default_open, str):
                exc = rule.get("exception", {}) or {}
                exc_if = exc.get("if", {}) or {}
                if _exception_matches(exc_if, ctx):
                    exc_open = exc.get("open")
                    if isinstance(exc_open, str):
                        return exc_open, rule.get("id"), f"{label}-check: exception i {rule.get('id')} -> {_to_display_bid(exc_open)}."
                return default_open, rule.get("id"), f"{label}-check: default i {rule.get('id')} -> {_to_display_bid(default_open)}."

    if not style_block_found:
        return None, None, f"{label}-check: ingen regelblok for style '{style}'."
    return None, None, f"{label}-check: ingen regel matchede."


def _opening_flow_step_name(raw_step: Any) -> str | None:
    if isinstance(raw_step, str):
        step = raw_step.strip()
        return step or None

    step_map = _mapping_dict(raw_step)
    if not step_map:
        return None

    for key in ("step", "action", "id", "name"):
        val = step_map.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _opening_flow_steps_from_list(raw_steps: Any) -> list[str]:
    if not isinstance(raw_steps, list):
        return []
    out: list[str] = []
    for raw_step in raw_steps:
        step = _opening_flow_step_name(raw_step)
        if step is not None:
            out.append(step)
    return out


def _opening_decision_flow_steps(sys_def: Mapping[str, Any]) -> list[str]:
    default_steps = [
        "evaluate_opening_threshold",
        "evaluate_1NT_opening",
        "evaluate_major_opening",
        "evaluate_minor_opening",
        "if_no_opening_then_pass",
    ]

    sys_map = _mapping_dict(sys_def)

    # v1.0-style flow (context/node model) takes precedence when present.
    opening_model = _mapping_dict(sys_map.get("opening_model"))
    contexts = _mapping_dict(opening_model.get("contexts"))
    for ctx_key in ("decision_flow", "opening_flow", "first_round"):
        ctx = _mapping_dict(contexts.get(ctx_key))
        steps = _opening_flow_steps_from_list(ctx.get("steps"))
        if steps:
            return steps

        nodes = _mapping_dict(ctx.get("nodes"))
        for node in nodes.values():
            node_map = _mapping_dict(node)
            steps = _opening_flow_steps_from_list(node_map.get("steps"))
            if steps:
                return steps

    # Legacy flow list.
    legacy_steps = _opening_flow_steps_from_list(sys_map.get("opening_decision_flow"))
    if legacy_steps:
        return legacy_steps

    return list(default_steps)


def suggest_opening_for_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Suggest dealer's first call using YAML system + profile settings."""
    dealer = _normalize_seat(row.get("dealer"))
    if dealer is None:
        return {
            "dealer": None,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "dealer_unknown",
            "explanation": "Dealer mangler, bruger PAS som fallback.",
            "log_lines": [
                "Kontekst: dealer ukendt.",
                "Valg: PAS",
                "Regel-id: dealer_unknown",
                "Forklaring: Dealer mangler, bruger PAS som fallback.",
            ],
        }

    hand_col = f"{dealer}_hand"
    hand_dot = row.get(hand_col)
    if hand_dot is None or str(hand_dot).strip() in ("", "None"):
        return {
            "dealer": dealer,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "hand_missing",
            "explanation": f"Hånd mangler for {dealer}; bruger PAS.",
            "log_lines": [
                f"Kontekst: dealer={dealer}.",
                f"Valg: PAS",
                "Regel-id: hand_missing",
                f"Forklaring: Hånd mangler for {dealer}; bruger PAS.",
            ],
        }

    ctx = _build_context(str(hand_dot))
    bundle = _load_bundle()
    profile_name, profile_cfg = _pick_profile(dealer, bundle)
    sys_def = _pick_system_def(profile_cfg, bundle)

    log_lines = [
        f"Kontekst: dealer={dealer}, profil={profile_name if profile_name else '(ukendt)'}.",
        f"Hånd: {int(ctx['hcp'])} HCP, shape {_shape_text(ctx)}.",
    ]

    if not profile_cfg or not sys_def:
        return {
            "dealer": dealer,
            "profile": profile_name,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "system_missing",
            "explanation": "System/profil mangler; bruger PAS.",
            "log_lines": log_lines + [
                "Valg: PAS",
                "Regel-id: system_missing",
                "Forklaring: System/profil mangler; bruger PAS.",
            ],
        }

    for flow_step in _opening_decision_flow_steps(sys_def):
        step = str(flow_step).strip().lower()

        if step == "evaluate_opening_threshold":
            threshold_ok, threshold_line = _evaluate_opening_threshold(ctx, profile_cfg, sys_def)
            log_lines.append(threshold_line)
            if not threshold_ok:
                return {
                    "dealer": dealer,
                    "profile": profile_name,
                    "bid": "PASS",
                    "display_bid": "PAS",
                    "rule_id": "threshold_fail",
                    "explanation": "Åbningstærskel ikke opfyldt.",
                    "log_lines": log_lines + [
                        "Valg: PAS",
                        "Regel-id: threshold_fail",
                        "Forklaring: Åbningstærskel ikke opfyldt.",
                    ],
                }
            continue

        if step in ("evaluate_1nt_opening", "evaluate_one_nt_opening"):
            nt_bid, nt_rule, nt_line = _evaluate_one_nt(ctx, profile_cfg, sys_def)
            log_lines.append(nt_line)
            if nt_bid:
                display = _to_display_bid(nt_bid)
                return {
                    "dealer": dealer,
                    "profile": profile_name,
                    "bid": nt_bid,
                    "display_bid": display,
                    "rule_id": nt_rule,
                    "explanation": "1NT opfylder styrke-, form- og profilkrav.",
                    "log_lines": log_lines + [
                        "Major-check: ikke vurderet (1NT valgt).",
                        "Minor-check: ikke vurderet (1NT valgt).",
                        f"Valg: {display}",
                        f"Regel-id: {nt_rule}",
                        "Forklaring: 1NT opfylder styrke-, form- og profilkrav.",
                    ],
                }
            continue

        if step == "evaluate_major_opening":
            major_bid, major_rule, major_line = _evaluate_suit_opening(
                ctx,
                profile_cfg,
                sys_def,
                logic_key="major_opening_logic",
                style_key="major_style",
            )
            log_lines.append(major_line)
            if major_bid:
                display = _to_display_bid(major_bid)
                return {
                    "dealer": dealer,
                    "profile": profile_name,
                    "bid": major_bid,
                    "display_bid": display,
                    "rule_id": major_rule,
                    "explanation": "Naturlig major-åbning valgt fra profilregler.",
                    "log_lines": log_lines + [
                        "Minor-check: ikke vurderet (major valgt).",
                        f"Valg: {display}",
                        f"Regel-id: {major_rule}",
                        "Forklaring: Naturlig major-åbning valgt fra profilregler.",
                    ],
                }
            continue

        if step == "evaluate_minor_opening":
            minor_bid, minor_rule, minor_line = _evaluate_suit_opening(
                ctx,
                profile_cfg,
                sys_def,
                logic_key="minor_opening_logic",
                style_key="minor_style",
            )
            log_lines.append(minor_line)
            if minor_bid:
                display = _to_display_bid(minor_bid)
                return {
                    "dealer": dealer,
                    "profile": profile_name,
                    "bid": minor_bid,
                    "display_bid": display,
                    "rule_id": minor_rule,
                    "explanation": "Naturlig minor-åbning valgt fra profilregler.",
                    "log_lines": log_lines + [
                        f"Valg: {display}",
                        f"Regel-id: {minor_rule}",
                        "Forklaring: Naturlig minor-åbning valgt fra profilregler.",
                    ],
                }
            continue

        if step == "if_no_opening_then_pass":
            return {
                "dealer": dealer,
                "profile": profile_name,
                "bid": "PASS",
                "display_bid": "PAS",
                "rule_id": "no_opening_rule_matched",
                "explanation": "Ingen åbning matchede; bruger PAS.",
                "log_lines": log_lines + [
                    "Valg: PAS",
                    "Regel-id: no_opening_rule_matched",
                    "Forklaring: Ingen åbning matchede; bruger PAS.",
                ],
            }

    return {
        "dealer": dealer,
        "profile": profile_name,
        "bid": "PASS",
        "display_bid": "PAS",
        "rule_id": "no_opening_rule_matched",
        "explanation": "Ingen åbning matchede; bruger PAS.",
        "log_lines": log_lines + [
            "Valg: PAS",
            "Regel-id: no_opening_rule_matched",
            "Forklaring: Ingen åbning matchede; bruger PAS.",
        ],
    }


def _next_seat(seat: str | None) -> str | None:
    if seat == "N":
        return "Ø"
    if seat == "Ø":
        return "S"
    if seat == "S":
        return "V"
    if seat == "V":
        return "N"
    return None


def _partner_of(seat: str | None) -> str | None:
    if seat == "N":
        return "S"
    if seat == "S":
        return "N"
    if seat == "Ø":
        return "V"
    if seat == "V":
        return "Ø"
    return None


def _profile_bool_flag(profile_cfg: Mapping[str, Any], key: str, default: bool) -> bool:
    raw = profile_cfg.get(key)
    if isinstance(raw, bool):
        return raw
    txt = str(raw or "").strip().lower()
    if txt in ("enabled", "true", "1", "yes", "on"):
        return True
    if txt in ("disabled", "false", "0", "no", "off"):
        return False
    return default


def _profile_for_seat(seat: str) -> tuple[str | None, dict[str, Any]]:
    bundle = _load_bundle()
    return _pick_profile(seat, bundle)


def _is_fourth_suit_forcing_enabled_for_seat(seat: str) -> bool:
    _, profile_cfg = _profile_for_seat(seat)
    return _profile_bool_flag(profile_cfg, "fourth_suit_forcing", True)


def _is_two_over_one_gf_enabled_for_seat(seat: str) -> bool:
    _, profile_cfg = _profile_for_seat(seat)
    return _profile_bool_flag(profile_cfg, "two_over_one_game_force", False)


def _competitive_bidding_for_seat(seat: str) -> dict[str, Any]:
    sys_def = _system_def_for_seat(seat)
    raw = (sys_def.get("competitive_bidding", {}) or {}) if isinstance(sys_def, Mapping) else {}
    out = _mapping_dict(raw)
    contexts = _mapping_dict(out.get("contexts"))
    if not contexts:
        return out

    legacy: dict[str, Any] = {}

    doubles = _mapping_dict(contexts.get("doubles"))
    if doubles:
        interpretation_priority = _mapping_dict(doubles.get("interpretation_priority"))
        if interpretation_priority:
            legacy["doubles_interpretation_priority"] = interpretation_priority

        double_nodes = _mapping_dict(doubles.get("nodes"))
        if double_nodes:
            lead_directing = _mapping_dict(double_nodes.get("lead_directing"))
            if lead_directing:
                legacy["lead_directing_double_system"] = lead_directing

            takeout = _mapping_dict(double_nodes.get("takeout"))
            if takeout:
                legacy["takeout_double"] = takeout

            negative = _mapping_dict(double_nodes.get("negative"))
            if negative:
                legacy["negative_double_system"] = negative

            penalty = _mapping_dict(double_nodes.get("penalty"))
            if penalty:
                sacrifice_eval = _mapping_dict(penalty.get("sacrifice_evaluation"))
                if sacrifice_eval:
                    legacy["sacrifice_evaluation"] = sacrifice_eval

    overcalls_ctx = _mapping_dict(contexts.get("overcalls"))
    if overcalls_ctx:
        overcalls: dict[str, Any] = {}
        natural = _mapping_dict(overcalls_ctx.get("natural"))
        if natural:
            one_level = _mapping_dict(natural.get("one_level"))
            if one_level:
                overcalls["one_level_overcall"] = one_level

            two_level = _mapping_dict(natural.get("two_level"))
            if two_level:
                overcalls["two_level_overcall"] = two_level

            jump = _mapping_dict(natural.get("jump"))
            if jump:
                overcalls["jump_overcall"] = jump

            one_notrump = _mapping_dict(natural.get("one_notrump"))
            if one_notrump:
                overcalls["one_nt_overcall"] = one_notrump

        cuebid = _mapping_dict(overcalls_ctx.get("cuebid"))
        if cuebid:
            overcalls["cuebid_overcall"] = cuebid

        if overcalls:
            legacy["overcalls"] = overcalls

    raises = _mapping_dict(contexts.get("raises"))
    cue_raise = _mapping_dict(raises.get("cue_raise_after_overcall"))
    if cue_raise:
        legacy["cue_raise_after_overcall"] = cue_raise

    responses = _mapping_dict(contexts.get("responses"))
    takeout_responses = _mapping_dict(responses.get("takeout_double"))
    if takeout_responses:
        legacy["responses_to_takeout_double"] = takeout_responses

    return legacy


def _takeout_double_min_hcp_for_seat(seat: str) -> int:
    comp = _competitive_bidding_for_seat(seat)
    tko = (comp.get("takeout_double", {}) or {}) if isinstance(comp, Mapping) else {}
    minimum = (tko.get("minimum_strength", {}) or {}) if isinstance(tko, Mapping) else {}
    try:
        return int(minimum.get("hcp_min", 12))
    except Exception:
        return 12


def _responses_to_takeout_double_for_seat(seat: str) -> dict[str, Any]:
    comp = _competitive_bidding_for_seat(seat)
    out = (comp.get("responses_to_takeout_double", {}) or {}) if isinstance(comp, Mapping) else {}
    return out if isinstance(out, Mapping) else {}


def _one_nt_overcall_params_for_seat(seat: str) -> dict[str, Any]:
    comp = _competitive_bidding_for_seat(seat)
    overcalls = (comp.get("overcalls", {}) or {}) if isinstance(comp, Mapping) else {}
    one_nt = (overcalls.get("one_nt_overcall", {}) or {}) if isinstance(overcalls, Mapping) else {}

    strength = (one_nt.get("strength", {}) or {}) if isinstance(one_nt, Mapping) else {}
    hcp_min, hcp_max = _hcp_bounds_from_spec(strength, 15, 18)

    req = (one_nt.get("requirements", {}) or {}) if isinstance(one_nt, Mapping) else {}
    require_stopper = _bool_or_default(
        req.get("stopper_in_opponents_suit") if isinstance(req, Mapping) else None,
        True,
    )

    shape_txt = str(one_nt.get("shape") or "balanced").strip().lower()
    require_balanced = shape_txt in ("", "balanced")

    return {
        "hcp_min": int(hcp_min),
        "hcp_max": int(hcp_max),
        "require_balanced": bool(require_balanced),
        "require_stopper": bool(require_stopper),
    }


def _one_nt_response_style_for_seat(seat: str) -> str:
    _, profile_cfg = _profile_for_seat(seat)
    style = str((profile_cfg or {}).get("one_nt_response_style") or "standard_stayman_jacoby").strip()
    return style or "standard_stayman_jacoby"


def _one_nt_response_style_block_for_seat(seat: str) -> dict[str, Any]:
    sys_def = _system_def_for_seat(seat)
    one_nt_resp = (sys_def.get("one_nt_response_system", {}) or {}) if isinstance(sys_def, Mapping) else {}
    if not isinstance(one_nt_resp, Mapping):
        return {}

    style = _one_nt_response_style_for_seat(seat)
    block = one_nt_resp.get(style, {})
    return block if isinstance(block, Mapping) else {}


def _one_nt_stayman_continuation_block_for_seat(seat: str, section_key: str) -> dict[str, Any]:
    style_block = _one_nt_response_style_block_for_seat(seat)
    section = (style_block.get(section_key, {}) or {}) if isinstance(style_block, Mapping) else {}
    return section if isinstance(section, Mapping) else {}


def _one_nt_stayman_params_for_seat(seat: str) -> dict[str, Any]:
    style = _one_nt_response_style_for_seat(seat)
    style_cfg = _one_nt_response_style_block_for_seat(seat)

    responses = (style_cfg.get("responses", {}) or {}) if isinstance(style_cfg, Mapping) else {}
    if not isinstance(responses, Mapping):
        responses = {}

    two_c = (responses.get("2C", {}) or {}) if isinstance(responses, Mapping) else {}
    if not isinstance(two_c, Mapping):
        two_c = {}

    # Standard fallback for Stayman when style does not specify explicit values.
    hcp_min = max(0, _int_or_default(two_c.get("hcp_min", 8), 8))
    requires_four_card_major = _bool_or_default(two_c.get("promises_four_card_major"), True)

    return {
        "hcp_min": int(hcp_min),
        "requires_four_card_major": bool(requires_four_card_major),
        "style": style,
    }


def _has_opponent_non_pass_after_partner_last_nt(
    prior_calls: list[Mapping[str, Any]],
    seat: str,
) -> bool:
    partner = _partner_of(seat)
    if partner is None:
        return False

    side = _seat_side(seat)
    opp_side = "ØV" if side == "NS" else "NS"

    partner_nt_idx: int | None = None
    for idx in range(len(prior_calls) - 1, -1, -1):
        call = prior_calls[idx]
        c_seat = _normalize_seat(call.get("dealer"))
        if c_seat != partner:
            continue
        parsed = _parse_contract_bid(str(call.get("bid") or "PASS").upper())
        if parsed is None or parsed[1] != "NT":
            continue
        partner_nt_idx = idx
        break

    if partner_nt_idx is None:
        return False

    for call in prior_calls[partner_nt_idx + 1:]:
        c_seat = _normalize_seat(call.get("dealer"))
        if c_seat is None or _seat_side(c_seat) != opp_side:
            continue
        if not _is_pass_bid(call.get("bid")):
            return True

    return False


def _has_opponent_contract_after_partner_last_contract(
    prior_calls: list[Mapping[str, Any]],
    seat: str,
) -> bool:
    partner = _partner_of(seat)
    if partner is None:
        return False

    side = _seat_side(seat)
    opp_side = "ØV" if side == "NS" else "NS"

    partner_contract_idx: int | None = None
    for idx in range(len(prior_calls) - 1, -1, -1):
        call = prior_calls[idx]
        c_seat = _normalize_seat(call.get("dealer"))
        if c_seat != partner:
            continue
        parsed = _parse_contract_bid(str(call.get("bid") or "PASS").upper())
        if parsed is None:
            continue
        partner_contract_idx = idx
        break

    if partner_contract_idx is None:
        return False

    for call in prior_calls[partner_contract_idx + 1:]:
        c_seat = _normalize_seat(call.get("dealer"))
        if c_seat is None or _seat_side(c_seat) != opp_side:
            continue
        if _parse_contract_bid(str(call.get("bid") or "PASS").upper()) is not None:
            return True

    return False


def _negative_double_params_for_seat(seat: str) -> dict[str, Any]:
    comp = _competitive_bidding_for_seat(seat)
    neg = (comp.get("negative_double_system", {}) or {}) if isinstance(comp, Mapping) else {}

    enabled = _bool_or_default(neg.get("enabled"), True)
    minimum = (neg.get("minimum_strength", {}) or {}) if isinstance(neg, Mapping) else {}
    applies = (neg.get("applies_up_to", {}) or {}) if isinstance(neg, Mapping) else {}

    try:
        hcp_min = int(minimum.get("hcp_min", 6))
    except Exception:
        hcp_min = 6

    lvl_txt = str(applies.get("level") or "2S")
    lvl_parsed = _parse_contract_bid(lvl_txt)
    max_level = int(lvl_parsed[0]) if lvl_parsed is not None else 2

    return {
        "enabled": enabled,
        "hcp_min": hcp_min,
        "max_level": max_level,
    }


def _is_lead_directing_double_enabled_for_seat(seat: str) -> bool:
    comp = _competitive_bidding_for_seat(seat)
    ldd = (comp.get("lead_directing_double_system", {}) or {}) if isinstance(comp, Mapping) else {}
    by_profile = _bool_or_default(ldd.get("enabled_by_profile_flag"), True)
    if by_profile:
        _, profile_cfg = _profile_for_seat(seat)
        return _profile_bool_flag(profile_cfg, "lead_directing_doubles", True)
    return _bool_or_default(ldd.get("enabled"), True)


def _system_def_for_seat(seat: str) -> dict[str, Any]:
    bundle = _load_bundle()
    _, profile_cfg = _pick_profile(seat, bundle)
    return _pick_system_def(profile_cfg, bundle)


def _hand_strength_model_for_seat(seat: str) -> dict[str, Any]:
    sys_def = _system_def_for_seat(seat)
    return (sys_def.get("hand_strength_model", {}) or {}) if isinstance(sys_def, Mapping) else {}


def _hcp_bounds_from_spec(spec: Mapping[str, Any] | None, default_low: int, default_high: int) -> tuple[int, int]:
    if not isinstance(spec, Mapping):
        return default_low, default_high
    rng = spec.get("hcp_range")
    if isinstance(rng, list) and len(rng) >= 2:
        try:
            lo = int(rng[0])
            hi = int(rng[1])
            return lo, hi
        except Exception:
            pass
    lo = spec.get("hcp_min", default_low)
    hi = spec.get("hcp_max", default_high)
    try:
        return int(lo), int(hi)
    except Exception:
        return default_low, default_high


def _opener_strength_bucket_for_hcp(seat: str, hcp: int) -> str:
    model = _hand_strength_model_for_seat(seat)
    buckets = (model.get("opener_strength_buckets", {}) or {}) if isinstance(model, Mapping) else {}

    weak_low, weak_high = _hcp_bounds_from_spec(buckets.get("weak"), 12, 14)
    med_low, med_high = _hcp_bounds_from_spec(buckets.get("medium"), 15, 17)
    strong_low, _ = _hcp_bounds_from_spec(buckets.get("strong"), 18, 37)

    if weak_low <= int(hcp) <= weak_high:
        return "weak"
    if med_low <= int(hcp) <= med_high:
        return "medium"
    if int(hcp) >= strong_low:
        return "strong"
    return "weak" if int(hcp) <= weak_high else "medium"


def _int_or_default(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def _bool_or_default(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    txt = str(raw or "").strip().lower()
    if txt in ("enabled", "true", "1", "yes", "on"):
        return True
    if txt in ("disabled", "false", "0", "no", "off"):
        return False
    return bool(default)


def _fit_playing_points_rules_for_seat(seat: str) -> dict[str, Any]:
    model = _hand_strength_model_for_seat(seat)
    if not isinstance(model, Mapping):
        return {}

    fit_raw = model.get("fit_playing_points", {}) or {}
    if not isinstance(fit_raw, Mapping):
        return {}

    seq_raw = fit_raw.get("after_one_major_two_major_raise", fit_raw)
    return seq_raw if isinstance(seq_raw, Mapping) else {}


def _vulnerability_flags(vulnerability: Any) -> tuple[bool, bool]:
    txt = str(vulnerability or "").strip().upper().replace(" ", "")
    if txt in ("", "-", "NONE", "INGEN", "INGENIZONEN"):
        return False, False
    if txt in ("ALLE", "ALL", "BEGGE", "ALLEIZONEN"):
        return True, True
    if txt in ("NS", "NSIZONEN"):
        return True, False
    if txt in ("ØV", "OV", "EW", "ØVIZONEN", "EWIZONEN"):
        return False, True

    # Fallback for longer labels like "NS i zonen" / "ØV i zonen".
    if "INGEN" in txt:
        return False, False
    ns_vul = "NS" in txt
    ov_vul = ("ØV" in txt) or ("OV" in txt) or ("EW" in txt)
    if "ALLE" in txt or "ALL" in txt:
        return True, True
    return ns_vul, ov_vul


def _vulnerability_relation_for_side(vulnerability: Any, side: str) -> str:
    ns_vul, ov_vul = _vulnerability_flags(vulnerability)
    own_vul = ns_vul if side == "NS" else ov_vul
    opp_vul = ov_vul if side == "NS" else ns_vul
    if own_vul == opp_vul:
        return "equal"
    return "favorable" if (not own_vul and opp_vul) else "unfavorable"


def _shortness_points_with_fit(
    suit_lengths: Mapping[str, int],
    trump_strain: str,
    relation: str,
    shortness_bonus_cfg: Mapping[str, Any] | None = None,
) -> int:
    defaults = {
        "favorable": {"void": 5, "singleton": 3, "doubleton": 0},
        "equal": {"void": 4, "singleton": 2, "doubleton": 0},
        "unfavorable": {"void": 3, "singleton": 1, "doubleton": 0},
    }

    raw_cfg = shortness_bonus_cfg if isinstance(shortness_bonus_cfg, Mapping) else {}

    def _relation_weights(key: str, fallback: Mapping[str, int]) -> dict[str, int]:
        rel_raw = raw_cfg.get(key, {})
        if not isinstance(rel_raw, Mapping):
            rel_raw = {}
        return {
            "void": max(0, _int_or_default(rel_raw.get("void"), int(fallback["void"]))),
            "singleton": max(0, _int_or_default(rel_raw.get("singleton"), int(fallback["singleton"]))),
            "doubleton": max(0, _int_or_default(rel_raw.get("doubleton"), int(fallback["doubleton"]))),
        }

    weights = {
        "favorable": _relation_weights("favorable_vulnerability", defaults["favorable"]),
        "equal": _relation_weights("equal_vulnerability", defaults["equal"]),
        "unfavorable": _relation_weights("unfavorable_vulnerability", defaults["unfavorable"]),
    }
    w = weights.get(str(relation), weights["equal"])

    out = 0
    for suit in ("S", "H", "D", "C"):
        if suit == trump_strain:
            continue
        ln = int(suit_lengths.get(suit, 0))
        if ln <= 0:
            out += int(w["void"])
        elif ln == 1:
            out += int(w["singleton"])
        elif ln == 2:
            out += int(w["doubleton"])
    return out


def _playing_points_after_fit(
    ctx: Mapping[str, Any],
    seat: str,
    trump_strain: str,
    vulnerability: Any,
) -> tuple[int, str, int, int, int]:
    rules = _fit_playing_points_rules_for_seat(seat)
    enabled = _bool_or_default(rules.get("enabled"), True)

    shortness_bonus_cfg = rules.get("shortness_bonus", {})
    if not isinstance(shortness_bonus_cfg, Mapping):
        shortness_bonus_cfg = {}

    trump_cfg = rules.get("trump_length_bonus", {})
    if not isinstance(trump_cfg, Mapping):
        trump_cfg = {}
    trump_per_card = max(0, _int_or_default(trump_cfg.get("per_card_above_five"), 1))

    suit_lengths = {
        "S": int(ctx.get("spades", 0)),
        "H": int(ctx.get("hearts", 0)),
        "D": int(ctx.get("diamonds", 0)),
        "C": int(ctx.get("clubs", 0)),
    }
    relation = _vulnerability_relation_for_side(vulnerability, _seat_side(seat))
    trump_len = int(suit_lengths.get(trump_strain, 0))

    if enabled:
        shortness_pts = _shortness_points_with_fit(
            suit_lengths,
            trump_strain,
            relation,
            shortness_bonus_cfg,
        )
        trump_len_bonus = max(0, trump_len - 5) * trump_per_card
    else:
        shortness_pts = 0
        trump_len_bonus = 0

    playing_points = int(ctx.get("hcp", 0)) + shortness_pts + trump_len_bonus
    return playing_points, relation, shortness_pts, trump_len_bonus, trump_len


def _responder_strength_bucket_for_hcp(seat: str, hcp: int) -> str:
    model = _hand_strength_model_for_seat(seat)
    buckets = (model.get("responder_strength_buckets", {}) or {}) if isinstance(model, Mapping) else {}

    weak_low, weak_high = _hcp_bounds_from_spec(buckets.get("weak"), 6, 9)
    inv_low, inv_high = _hcp_bounds_from_spec(buckets.get("invitational"), 10, 12)
    forcing_low, _ = _hcp_bounds_from_spec(buckets.get("forcing_plus"), 13, 37)

    if weak_low <= int(hcp) <= weak_high:
        return "weak"
    if inv_low <= int(hcp) <= inv_high:
        return "invitational"
    if int(hcp) >= forcing_low:
        return "forcing_plus"
    return "weak" if int(hcp) <= weak_high else "invitational"


def _sequence_rules_for_seat(seat: str) -> dict[str, Any]:
    model = _hand_strength_model_for_seat(seat)
    if not isinstance(model, Mapping):
        return {}
    rules = model.get("responder_sequence_rules", {}) or {}
    return rules if isinstance(rules, Mapping) else {}


def _one_nt_over_minor_params_for_seat(seat: str) -> tuple[int, int, str, bool]:
    rules = _sequence_rules_for_seat(seat)
    spec = (rules.get("one_minor_one_nt", {}) or {}) if isinstance(rules, Mapping) else {}
    low, high = _hcp_bounds_from_spec(spec, 6, 10)
    forcing = str(spec.get("forcing") or "non_forcing")
    limited = bool(spec.get("responder_limited", True))

    if _is_two_over_one_gf_enabled_for_seat(seat):
        alt = spec.get("if_two_over_one_game_force", {}) or {}
        alt_low, alt_high = _hcp_bounds_from_spec(alt, low, high)
        low, high = alt_low, alt_high
        if alt.get("forcing"):
            forcing = str(alt.get("forcing"))
    return low, high, forcing, limited


def _one_nt_over_major_params_for_seat(seat: str) -> tuple[int, int, str, bool]:
    rules = _sequence_rules_for_seat(seat)
    spec = (rules.get("one_major_one_nt", {}) or {}) if isinstance(rules, Mapping) else {}
    low, high = _hcp_bounds_from_spec(spec, 6, 9)
    forcing = str(spec.get("forcing") or "non_forcing")
    limited = bool(spec.get("responder_limited", True))

    if _is_two_over_one_gf_enabled_for_seat(seat):
        alt = spec.get("if_two_over_one_game_force", {}) or {}
        alt_low, alt_high = _hcp_bounds_from_spec(alt, low, high)
        low, high = alt_low, alt_high
        if alt.get("forcing"):
            forcing = str(alt.get("forcing"))
    return low, high, forcing, limited


def _one_diamond_one_spade_forcing_rule_for_seat(seat: str) -> tuple[int, str, bool]:
    rules = _sequence_rules_for_seat(seat)
    spec = (rules.get("one_diamond_one_spade", {}) or {}) if isinstance(rules, Mapping) else {}
    try:
        hcp_min = int(spec.get("hcp_min", 6))
    except Exception:
        hcp_min = 6
    forcing = str(spec.get("forcing") or "one_round")
    limited = bool(spec.get("responder_limited", False))
    return hcp_min, forcing, limited


def _one_major_two_level_new_suit_rule_for_seat(seat: str) -> tuple[int, str, bool]:
    rules = _sequence_rules_for_seat(seat)
    spec_raw = (rules.get("one_major_two_level_new_suit", {}) or {}) if isinstance(rules, Mapping) else {}
    spec = spec_raw if isinstance(spec_raw, Mapping) else {}

    hcp_min = _int_or_default(spec.get("default_hcp_min", spec.get("hcp_min", 10)), 10)
    forcing = str(spec.get("forcing") or "one_round")
    opener_may_pass = _bool_or_default(spec.get("opener_may_pass"), False)

    if _is_two_over_one_gf_enabled_for_seat(seat):
        alt_raw = spec.get("if_two_over_one_game_force", {}) or {}
        alt = alt_raw if isinstance(alt_raw, Mapping) else {}
        if "hcp_min" in alt:
            hcp_min = _int_or_default(alt.get("hcp_min"), hcp_min)
        elif "default_hcp_min" in alt:
            hcp_min = _int_or_default(alt.get("default_hcp_min"), hcp_min)
        if alt.get("forcing"):
            forcing = str(alt.get("forcing"))
        if "opener_may_pass" in alt:
            opener_may_pass = _bool_or_default(alt.get("opener_may_pass"), opener_may_pass)

    return max(0, int(hcp_min)), forcing, opener_may_pass


def _one_major_two_level_new_suit_then_major_rebid_params_for_seat(seat: str) -> tuple[int, int, int]:
    rules = _sequence_rules_for_seat(seat)
    spec_raw = (rules.get("one_major_two_level_new_suit_then_major_rebid", {}) or {}) if isinstance(rules, Mapping) else {}
    spec = spec_raw if isinstance(spec_raw, Mapping) else {}

    support_min = max(1, _int_or_default(spec.get("support_min", 3), 3))
    game_hcp_min = max(0, _int_or_default(spec.get("game_hcp_min", 12), 12))
    game_playing_points_min = max(0, _int_or_default(spec.get("game_playing_points_min", 14), 14))

    if _is_two_over_one_gf_enabled_for_seat(seat):
        alt_raw = spec.get("if_two_over_one_game_force", {}) or {}
        alt = alt_raw if isinstance(alt_raw, Mapping) else {}
        support_min = max(1, _int_or_default(alt.get("support_min", support_min), support_min))
        game_hcp_min = max(0, _int_or_default(alt.get("game_hcp_min", game_hcp_min), game_hcp_min))
        game_playing_points_min = max(
            0,
            _int_or_default(alt.get("game_playing_points_min", game_playing_points_min), game_playing_points_min),
        )

    return support_min, game_hcp_min, game_playing_points_min


def _is_two_over_one_new_suit(
    opening_strain: str | None,
    response_strain: str | None,
    response_level: int | None = None,
) -> bool:
    if opening_strain not in ("H", "S"):
        return False
    if response_strain not in ("S", "H", "D", "C"):
        return False
    if response_strain == opening_strain:
        return False
    if _strain_order(response_strain) >= _strain_order(opening_strain):
        return False
    if response_level is not None and int(response_level) != 2:
        return False
    return True


def _latest_side_contract_in_state(state: Any, seat: str) -> tuple[str, int, str] | None:
    for prev in reversed(list(state.calls or [])):
        prev_seat = _normalize_seat(getattr(prev, "seat", None))
        if prev_seat is None or _seat_side(prev_seat) != _seat_side(seat):
            continue
        parsed = _parse_contract_bid(getattr(prev, "bid", None))
        if parsed is None:
            continue
        return prev_seat, parsed[0], parsed[1]
    return None


def _side_contract_history(
    prior_calls: list[Mapping[str, Any]],
    seat: str,
) -> list[tuple[str, int, str]]:
    side = _seat_side(seat)
    out: list[tuple[str, int, str]] = []
    for c in prior_calls:
        c_seat = _normalize_seat(c.get("dealer"))
        if c_seat is None or _seat_side(c_seat) != side:
            continue
        bid = str(c.get("bid") or "PASS").upper()
        parsed = _parse_contract_bid(bid)
        if parsed is None:
            continue
        out.append((c_seat, parsed[0], parsed[1]))
    return out


def _infer_fourth_unbid_suit_from_side_history(
    side_history: list[tuple[str, int, str]],
) -> str | None:
    suits = [strain for _, _, strain in side_history if strain in ("S", "H", "D", "C")]
    unique = set(suits)
    if len(unique) != 3:
        return None
    for s in ("S", "H", "D", "C"):
        if s not in unique:
            return s
    return None


def _side_has_two_over_one_dhs(side_history: list[tuple[str, int, str]]) -> bool:
    if len(side_history) < 2:
        return False
    _, lvl1, strain1 = side_history[0]
    _, lvl2, strain2 = side_history[1]
    if lvl1 != 1 or lvl2 != 2:
        return False
    if strain2 not in ("D", "H", "S"):
        return False
    return strain2 != strain1


def _has_stopper_in_suit(hand_dot: str, strain: str) -> bool:
    parsed = parse_hand(str(hand_dot))
    ranks = parsed.suits.get(strain, "")
    length = int(parsed.lengths.get(strain, 0))

    if "A" in ranks:
        return True
    if "K" in ranks and length >= 2:
        return True
    if "Q" in ranks and "J" in ranks and length >= 3:
        return True
    if "Q" in ranks and "T" in ranks and length >= 4:
        return True
    return False


def _latest_partner_contract_call(
    prior_calls: list[Mapping[str, Any]],
    seat: str,
) -> Mapping[str, Any] | None:
    partner = _partner_of(seat)
    for c in reversed(prior_calls):
        c_seat = _normalize_seat(c.get("dealer"))
        if c_seat != partner:
            continue
        bid = str(c.get("bid") or "PASS").upper()
        if _parse_contract_bid(bid) is None:
            continue
        return c
    return None


def _parse_contract_bid(bid: str | None) -> tuple[int, str] | None:
    if bid is None:
        return None
    txt = str(bid).strip().upper().replace(" ", "")
    if txt in ("PASS", "PAS", "X", "DBL", "DOUBLE"):
        return None
    m = re.match(r"^([1-7])(NT|[SHDC])$", txt)
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def _latest_call_by_side(
    prior_calls: list[Mapping[str, Any]],
    side: str,
) -> Mapping[str, Any] | None:
    for c in reversed(prior_calls):
        c_seat = _normalize_seat(c.get("dealer"))
        if c_seat is None or _seat_side(c_seat) != side:
            continue
        return c
    return None


def _latest_contract_call_by_side(
    prior_calls: list[Mapping[str, Any]],
    side: str,
) -> Mapping[str, Any] | None:
    for c in reversed(prior_calls):
        c_seat = _normalize_seat(c.get("dealer"))
        if c_seat is None or _seat_side(c_seat) != side:
            continue
        bid = str(c.get("bid") or "PASS").upper()
        if _parse_contract_bid(bid) is None:
            continue
        return c
    return None


def _is_artificial_rule_id(rule_id: str) -> bool:
    rid = str(rule_id or "").strip().lower()
    if not rid:
        return False
    markers = (
        "stayman",
        "transfer",
        "relay",
        "michaels",
        "cue_raise",
        "fourth_suit",
        "artificial",
        "jordan",
    )
    return any(tok in rid for tok in markers)


def _is_artificial_call(call: Mapping[str, Any] | None) -> bool:
    if not isinstance(call, Mapping):
        return False
    if _bool_or_default(call.get("artificial"), False):
        return True
    if _is_artificial_rule_id(str(call.get("rule_id") or "")):
        return True
    expl = str(call.get("explanation") or "").lower()
    return ("kunstig" in expl) or ("artificial" in expl)


# ---------------------------------------------------------------------------
# Sacrifice / penalty-double scoring helpers (no DD — all from bid inference)
# ---------------------------------------------------------------------------

def _partner_hcp_mid_from_calls(prior_calls: list[Mapping[str, Any]], partner_seat: str) -> float:
    """Return the mid-point HCP estimate for partner based on their first contract bid.

    No hidden-card knowledge is used — only the bid string and rule_id are consulted.
    """
    for call in prior_calls:
        cseat = _normalize_seat(call.get("dealer"))
        if cseat != partner_seat:
            continue
        bid = str(call.get("bid") or "PASS").upper().strip()
        rid = str(call.get("rule_id") or "").lower()
        if bid in ("PASS", "PAS", "X", "XX"):
            continue
        parsed = _parse_contract_bid(bid)
        if parsed is None:
            continue
        level, strain = parsed
        # 1NT / 2NT range lookups
        if strain == "NT":
            if level == 1:
                return 16.0   # 1NT = 15-17
            if level == 2:
                return 20.5   # 2NT = 20-21
            if level == 3:
                return 26.0   # 3NT natural = strong
        # 2C strong opening
        if level == 2 and strain == "C" and "strong" in rid:
            return 20.0
        # Weak two or preempt
        if level >= 2 and ("weak" in rid or "preempt" in rid):
            return 7.5   # weak 6-10 HCP
        if level == 3:
            return 7.5   # 3-level preempt
        if level == 4:
            return 7.5   # 4-level preempt
        # One-level opening
        if level == 1:
            return 14.0  # 1X = solid ~12-18 → mid ~14-15
    # Partner has only passed
    return 6.0


def _doubled_undertrick_score(undertricks: int, opp_vulnerable: bool) -> int:
    """Standard duplicate bridge doubled undertrick penalties."""
    if undertricks <= 0:
        return 0
    if not opp_vulnerable:
        # -100, -300, -500, -800, -1100, -1400 ...
        if undertricks == 1:
            return 100
        if undertricks == 2:
            return 300
        if undertricks == 3:
            return 500
        return 500 + (undertricks - 3) * 300
    else:
        # -200, -500, -800, -1100, -1400 ...
        if undertricks == 1:
            return 200
        if undertricks == 2:
            return 500
        return 500 + (undertricks - 2) * 300


def _our_likely_game_score(ns_combined_hcp: float, ns_vulnerable: bool) -> int:
    """Rough duplicate score for our expected best game (HCP-based).

    Returns the expected score we would earn if we play and make our game.
    """
    base = 420 if ns_vulnerable else 400   # ~4M / 3NT makeweight
    # Slam bonus: very rough
    if ns_combined_hcp >= 33:
        return 1430 if ns_vulnerable else 980   # small slam
    if ns_combined_hcp >= 26:
        return base
    # Part score territory
    return 110 if ns_vulnerable else 90


def _estimate_opp_tricks_from_bids(
    opp_inferred_hcp: float,
    opp_suit_length: int,
    opp_level: int,
) -> float:
    """Estimate opponent tricks from bid-inferred information only.

    Uses the HCP-to-tricks rule-of-thumb + suit-length bonus.
    """
    hcp_tricks = 6.0 + (opp_inferred_hcp - 20.0) / 3.0   # ~6 tricks at 20 HCP
    hcp_tricks = max(hcp_tricks, float(opp_level + 1))     # they wouldn't bid without some hope

    # Suit-length bonus: a long solid suit adds a trick or two
    suit_bonus = 0.0
    if opp_suit_length >= 8:
        suit_bonus = 2.0
    elif opp_suit_length >= 7:
        suit_bonus = 1.0

    return hcp_tricks + suit_bonus


def _sacrifice_double_is_better(
    ctx: dict[str, Any],
    prior_calls: list[Mapping[str, Any]],
    seat: str,
    opp_level: int,
    opp_strain: str,
    vulnerability: str,
    opp_suit_length: int,
) -> tuple[bool, str]:
    """Decide whether doubling a (likely sacrifice) contract beats bidding on.

    Returns (should_double: bool, reasoning: str).
    All inference is from the auction — no DD data is used.
    """
    ns_vul, ov_vul = _vulnerability_flags(vulnerability)
    our_side = _seat_side(seat)
    we_are_ns = (our_side == "NS")
    our_vul = ns_vul if we_are_ns else ov_vul
    opp_vul = ov_vul if we_are_ns else ns_vul

    own_hcp = float(ctx.get("hcp", 0))
    partner_seat = _partner_of(seat)
    partner_hcp_mid = _partner_hcp_mid_from_calls(prior_calls, partner_seat)
    combined_ns_hcp = own_hcp + partner_hcp_mid

    # Only apply if we're likely in game territory
    if combined_ns_hcp < 24:
        return False, "kombineret HCP under 24 — sandsynligvis ikke offersituation"

    # Infer opponent HCP from balance
    opp_inferred_hcp = max(0.0, 40.0 - combined_ns_hcp)

    # Estimate how many tricks opponents will take
    estimated_opp_tricks = _estimate_opp_tricks_from_bids(
        opp_inferred_hcp, opp_suit_length, opp_level
    )

    needed_tricks = opp_level + 6
    predicted_undertricks = needed_tricks - estimated_opp_tricks

    # Our expected game score
    our_game_score = _our_likely_game_score(combined_ns_hcp, our_vul)

    # Penalty score for doubling them
    penalty_score = _doubled_undertrick_score(int(round(predicted_undertricks)), opp_vul)

    # Vulnerability threshold (the 3/2/1 rule): minimum undertricks for double to profit
    vul_rel = _vulnerability_relation_for_side(vulnerability, our_side)
    if vul_rel == "favorable":
        min_down = 3
    elif vul_rel == "equal":
        min_down = 2
    else:
        min_down = 1

    reason = (
        f"makker HCP ≈{partner_hcp_mid:.0f}, kombineret NS≈{combined_ns_hcp:.0f}, "
        f"modpart HCP≈{opp_inferred_hcp:.0f}, "
        f"estimeret ned={predicted_undertricks:.1f} (grænse={min_down}), "
        f"straf≈{penalty_score} vs. vor udgang≈{our_game_score}"
    )

    if predicted_undertricks >= min_down and penalty_score >= our_game_score:
        return True, reason
    return False, reason


# ---------------------------------------------------------------------------
# End of sacrifice helpers
# ---------------------------------------------------------------------------


def _double_context_for_seat(
    prior_calls: list[Mapping[str, Any]],
    seat: str,
) -> dict[str, Any]:
    side = _seat_side(seat)
    opp_side = "ØV" if side == "NS" else "NS"
    partner = _partner_of(seat)

    latest_opp_call = _latest_call_by_side(prior_calls, opp_side)
    latest_opp_contract = _latest_contract_call_by_side(prior_calls, opp_side)

    partner_calls = []
    for c in prior_calls:
        c_seat = _normalize_seat(c.get("dealer"))
        if c_seat == partner:
            partner_calls.append(c)

    partner_has_contract = False
    for c in partner_calls:
        bid = str(c.get("bid") or "PASS").upper()
        if _parse_contract_bid(bid) is not None:
            partner_has_contract = True
            break

    partner_only_pass_or_unbid = (not partner_calls) or all(
        _is_pass_bid(c.get("bid")) for c in partner_calls
    )

    if latest_opp_contract is None:
        return {
            "double_type": "none",
            "context_note": "Ingen modpartskontrakt at doble.",
            "partner_has_contract": partner_has_contract,
            "partner_only_pass_or_unbid": partner_only_pass_or_unbid,
            "latest_opp_call": latest_opp_call,
            "latest_opp_contract_bid": None,
            "latest_opp_contract_level": None,
            "latest_opp_contract_strain": None,
        }

    latest_bid = str(latest_opp_contract.get("bid") or "PASS").upper()
    latest_parsed = _parse_contract_bid(latest_bid)
    latest_level = latest_parsed[0] if latest_parsed is not None else None
    latest_strain = latest_parsed[1] if latest_parsed is not None else None

    if _is_artificial_call(latest_opp_call) and latest_strain in ("S", "H", "D", "C"):
        return {
            "double_type": "lead_directing",
            "context_note": "Sidste modpartsmelding er kunstig farvemelding; dobling tolkes udspilsdirigerende.",
            "partner_has_contract": partner_has_contract,
            "partner_only_pass_or_unbid": partner_only_pass_or_unbid,
            "latest_opp_call": latest_opp_call,
            "latest_opp_contract_bid": latest_bid,
            "latest_opp_contract_level": latest_level,
            "latest_opp_contract_strain": latest_strain,
        }

    if partner_only_pass_or_unbid:
        return {
            "double_type": "takeout",
            "context_note": "Makker er umeldt/kun PAS; dobling tolkes som oplysningsdobling.",
            "partner_has_contract": partner_has_contract,
            "partner_only_pass_or_unbid": partner_only_pass_or_unbid,
            "latest_opp_call": latest_opp_call,
            "latest_opp_contract_bid": latest_bid,
            "latest_opp_contract_level": latest_level,
            "latest_opp_contract_strain": latest_strain,
        }

    if partner_has_contract:
        return {
            "double_type": "negative",
            "context_note": "Makker har allerede meldt kontrakt; dobling tolkes som negativ dobling.",
            "partner_has_contract": partner_has_contract,
            "partner_only_pass_or_unbid": partner_only_pass_or_unbid,
            "latest_opp_call": latest_opp_call,
            "latest_opp_contract_bid": latest_bid,
            "latest_opp_contract_level": latest_level,
            "latest_opp_contract_strain": latest_strain,
        }

    return {
        "double_type": "penalty",
        "context_note": "Ingen direkte takeout/negative/udspilsdirigerende trigger; dobling tolkes som straf.",
        "partner_has_contract": partner_has_contract,
        "partner_only_pass_or_unbid": partner_only_pass_or_unbid,
        "latest_opp_call": latest_opp_call,
        "latest_opp_contract_bid": latest_bid,
        "latest_opp_contract_level": latest_level,
        "latest_opp_contract_strain": latest_strain,
    }


def _strain_order(strain: str) -> int:
    order = {"C": 1, "D": 2, "H": 3, "S": 4, "NT": 5}
    return order.get(str(strain).upper(), 0)


def _lowest_higher_bid_for_strain(first_bid: str | None, strain: str) -> str | None:
    parsed = _parse_contract_bid(first_bid)
    if parsed is None:
        return f"1{strain}"
    lvl, fst = parsed
    out_lvl = lvl if _strain_order(strain) > _strain_order(fst) else lvl + 1
    if out_lvl < 1 or out_lvl > 7:
        return None
    return f"{out_lvl}{strain}"


def _jump_bid_for_strain(first_bid: str | None, strain: str) -> str | None:
    base = _lowest_higher_bid_for_strain(first_bid, strain)
    parsed = _parse_contract_bid(base)
    if parsed is None:
        return None
    lvl, parsed_strain = parsed
    if lvl >= 7:
        return None
    return f"{lvl + 1}{parsed_strain}"


def _highest_contract_bid_text(*bids: str | None) -> str | None:
    best: tuple[int, str] | None = None
    for b in bids:
        parsed = _parse_contract_bid(b)
        if parsed is None:
            continue
        if best is None:
            best = parsed
            continue
        if parsed[0] > best[0] or (parsed[0] == best[0] and _strain_order(parsed[1]) > _strain_order(best[1])):
            best = parsed
    if best is None:
        return None
    return f"{best[0]}{best[1]}"


def _opening_from_specific_seat(row: Mapping[str, Any], seat: str, note: str) -> dict[str, Any]:
    row2 = dict(row)
    row2["dealer"] = seat
    out = suggest_opening_for_row(row2)
    out["log_lines"] = [note] + list(out.get("log_lines") or [])
    return out


def _suggest_second_hand_competitive(
    row: Mapping[str, Any],
    second_seat: str,
    first_bid: str,
    hand_tag: str = "2H",
    prior_calls: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    hand_col = f"{second_seat}_hand"
    hand_dot = row.get(hand_col)
    if hand_dot is None or str(hand_dot).strip() in ("", "None"):
        return {
            "dealer": second_seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "second_hand_missing",
            "explanation": f"2. hånd ({second_seat}) mangler hånddata; vælger PAS.",
            "log_lines": [
                f"{hand_tag} kontekst: seat={second_seat}, modpart åbnede {_to_display_bid(first_bid)}.",
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: second_hand_missing",
            ],
        }

    ctx = _build_context(str(hand_dot))
    parsed_first = _parse_contract_bid(first_bid)
    log_lines = [
        f"{hand_tag} kontekst: seat={second_seat}, modpart åbnede {_to_display_bid(first_bid)}.",
        f"{hand_tag} hånd: {int(ctx['hcp'])} HCP, shape {_shape_text(ctx)}.",
    ]

    if parsed_first is None:
        # Defensive fallback when first bid is not a normal contract.
        return {
            "dealer": second_seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "first_bid_unusable",
            "explanation": "Kan ikke tolke 1. hånds melding; vælger PAS.",
            "log_lines": log_lines + [
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: first_bid_unusable",
            ],
        }

    first_level, first_strain = parsed_first
    suit_lens = {
        "S": int(ctx["spades"]),
        "H": int(ctx["hearts"]),
        "D": int(ctx["diamonds"]),
        "C": int(ctx["clubs"]),
    }

    double_ctx = _double_context_for_seat(list(prior_calls or []), second_seat)
    double_type = str(double_ctx.get("double_type") or "takeout")
    log_lines.append(f"{hand_tag} dobbeltype: {double_type} ({double_ctx.get('context_note') or 'ingen note'}).")

    double_ok = False
    double_reason = f"{hand_tag} dobling: afvist."
    double_rule_id = "takeout_double_basic"
    double_explanation = "Hånden vælger oplysningsdobling i denne kontekst."

    if double_type == "lead_directing":
        lead_enabled = _is_lead_directing_double_enabled_for_seat(second_seat)
        if lead_enabled and first_strain in ("S", "H", "D", "C") and int(ctx["hcp"]) >= 8:
            double_ok = True
            double_rule_id = "lead_directing_double_basic"
            double_explanation = "Hånden vælger udspilsdirigerende dobling mod kunstig modpartsmelding."
            double_reason = f"{hand_tag} udspilsdirigerende dobling: OK (kunstig modpartsmelding i {_to_display_bid(first_bid)})."
        else:
            double_reason = f"{hand_tag} udspilsdirigerende dobling: afvist (kræver aktiv aftale, farvemelding og tilstrækkelige værdier)."

    elif double_type == "negative":
        neg = _negative_double_params_for_seat(second_seat)
        unbid = [s for s in ("S", "H", "D", "C") if s != first_strain]
        has_four_unbid = any(suit_lens[s] >= 4 for s in unbid)
        majors_over_minor = first_strain in ("C", "D") and suit_lens["S"] >= 4 and suit_lens["H"] >= 4
        shape_ok = majors_over_minor or has_four_unbid
        if (
            bool(neg.get("enabled", True))
            and int(ctx["hcp"]) >= int(neg.get("hcp_min", 6))
            and int(first_level) <= int(neg.get("max_level", 2))
            and shape_ok
        ):
            double_ok = True
            double_rule_id = "negative_double_basic"
            double_explanation = "Hånden vælger negativ dobling efter makkers kontraktmelding."
            double_reason = f"{hand_tag} negativ dobling: OK (HCP {int(ctx['hcp'])}, umeldte farver vises)."
        else:
            double_reason = f"{hand_tag} negativ dobling: afvist (niveau/styrke/fordeling opfylder ikke krav)."

    elif double_type == "penalty":
        opener_len = int(
            ctx["clubs"] if first_strain == "C"
            else ctx["diamonds"] if first_strain == "D"
            else ctx["hearts"] if first_strain == "H"
            else ctx["spades"] if first_strain == "S"
            else 0
        )
        vulnerability = row.get("vul") if isinstance(row, Mapping) else None
        sac_double, sac_reason = _sacrifice_double_is_better(
            ctx, list(prior_calls or []), second_seat,
            first_level, first_strain, vulnerability, opener_len,
        )
        shape_ok = first_strain in ("C", "D", "H", "S") and int(ctx["hcp"]) >= 10 and opener_len >= 4
        if sac_double or shape_ok:
            double_ok = True
            double_rule_id = "penalty_double_basic"
            double_explanation = "Hånden vælger strafdobling i fravær af takeout/negative/udspilsdirigerende trigger."
            if sac_double:
                double_reason = f"{hand_tag} strafdobling (offervurdering): OK — {sac_reason}."
            else:
                double_reason = f"{hand_tag} strafdobling: OK (styrke + længde i modpartens farve)."
        else:
            double_reason = (
                f"{hand_tag} strafdobling: afvist — {sac_reason}."
                if sac_reason
                else f"{hand_tag} strafdobling: afvist (kræver styrke og længde i modpartens farve)."
            )

    else:
        takeout_min_hcp = _takeout_double_min_hcp_for_seat(second_seat)
        hcp_val = int(ctx["hcp"])
        opener_len = int(
            ctx["clubs"] if first_strain == "C"
            else ctx["diamonds"] if first_strain == "D"
            else ctx["hearts"] if first_strain == "H"
            else ctx["spades"]
        )
        if first_strain in ("C", "D", "H", "S") and hcp_val >= int(takeout_min_hcp):
            if hcp_val >= 17:
                double_ok = True
                double_reason = f"{hand_tag} oplysningsdobling: OK (stærk hånd 17+ uden fordelingskrav)."
            elif first_strain in ("C", "D"):
                major_lens = sorted((int(ctx["hearts"]), int(ctx["spades"])), reverse=True)
                majors_ok = major_lens[0] >= 4 and major_lens[1] >= 3
                if opener_len <= 2 and majors_ok:
                    double_ok = True
                    double_reason = f"{hand_tag} oplysningsdobling: OK (kort i minor + 4-3 i majorerne)."
                else:
                    double_reason = f"{hand_tag} oplysningsdobling: afvist (kræver kort minor + 4-3/3-4 i majorerne)."
            else:
                other_major_len = int(ctx["hearts"] if first_strain == "S" else ctx["spades"])
                if opener_len <= 2 and other_major_len >= 4:
                    double_ok = True
                    double_reason = f"{hand_tag} oplysningsdobling: OK (kort i åbners major + 4+ i anden major)."
                else:
                    double_reason = f"{hand_tag} oplysningsdobling: afvist (kræver kort åbners major + 4+ i anden major)."
        else:
            double_reason = f"{hand_tag} oplysningsdobling: afvist (HCP under minimum {takeout_min_hcp})."

    log_lines.append(double_reason)

    nt_params = _one_nt_overcall_params_for_seat(second_seat)
    sys_def = _system_def_for_seat(second_seat)
    shape_defs = (sys_def.get("shape_definitions", {}) or {}) if isinstance(sys_def, Mapping) else {}
    if not isinstance(shape_defs, Mapping):
        shape_defs = {}
    balanced_shapes = shape_defs.get("balanced_shapes")
    if not isinstance(balanced_shapes, list):
        balanced_shapes = [[4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2]]

    is_balanced = _shape_matches(tuple(ctx.get("shape_shdc", (0, 0, 0, 0))), list(balanced_shapes))
    stopper_in_opening = first_strain in ("S", "H", "D", "C") and _has_stopper_in_suit(str(hand_dot), first_strain)

    nt_overcall_bid = None
    nt_overcall_rule = "natural_one_nt_overcall"
    nt_overcall_line = f"{hand_tag} 1NT-indmelding: afvist."
    if _is_higher_contract("1NT", first_bid):
        hcp_min = int(nt_params.get("hcp_min", 15))
        hcp_max = int(nt_params.get("hcp_max", 18))
        hcp_ok = hcp_min <= int(ctx["hcp"]) <= hcp_max
        balanced_ok = (not bool(nt_params.get("require_balanced", True))) or is_balanced
        stopper_ok = (not bool(nt_params.get("require_stopper", True))) or stopper_in_opening

        if hcp_ok and balanced_ok and stopper_ok:
            nt_overcall_bid = "1NT"
            nt_overcall_line = (
                f"{hand_tag} 1NT-indmelding: OK ({hcp_min}-{hcp_max} HCP, jævn hånd"
                + (", hold i modpartens farve" if bool(nt_params.get("require_stopper", True)) else "")
                + ")."
            )
        else:
            missing: list[str] = []
            if not hcp_ok:
                missing.append(f"HCP uden for {hcp_min}-{hcp_max}")
            if not balanced_ok:
                missing.append("ikke jævn hånd")
            if not stopper_ok:
                missing.append("mangler hold i modpartens farve")
            nt_overcall_line = f"{hand_tag} 1NT-indmelding: afvist ({'; '.join(missing)})."
    else:
        nt_overcall_line = f"{hand_tag} 1NT-indmelding: afvist (1NT er ikke over {_to_display_bid(first_bid)})."
    log_lines.append(nt_overcall_line)

    candidate_suits = sorted(
        [s for s in ("S", "H", "D", "C") if s != first_strain],
        key=lambda s: (suit_lens[s], _strain_order(s)),
        reverse=True,
    )

    actor_contracts: list[tuple[int, str]] = []
    partner_contracts: list[tuple[int, str]] = []
    partner_seat = _partner_of(second_seat)
    for prev in list(prior_calls or []):
        prev_seat = _normalize_seat(prev.get("dealer"))
        prev_parsed = _parse_contract_bid(str(prev.get("bid") or "PASS").upper())
        if prev_parsed is None:
            continue
        if prev_seat == second_seat:
            actor_contracts.append((int(prev_parsed[0]), str(prev_parsed[1])))
        elif prev_seat == partner_seat:
            partner_contracts.append((int(prev_parsed[0]), str(prev_parsed[1])))

    def _allow_competitive_self_rebid(cand_bid: str, cand_strain: str) -> tuple[bool, str | None]:
        """Guard against over-aggressive repeated self-rebids without partner support."""
        parsed_cand = _parse_contract_bid(cand_bid)
        if parsed_cand is None or not actor_contracts:
            return True, None

        actor_last_level, actor_last_strain = actor_contracts[-1]
        cand_level, cand_parsed_strain = int(parsed_cand[0]), str(parsed_cand[1])

        # Only constrain pure self-rebids in the same strain above own previous level.
        if cand_parsed_strain != actor_last_strain or cand_level <= int(actor_last_level):
            return True, None

        partner_has_support = any(str(st) == actor_last_strain for _lvl, st in partner_contracts)
        if partner_has_support:
            return True, None

        same_strain_count = sum(1 for _lvl, st in actor_contracts if str(st) == actor_last_strain)
        hcp_val = int(ctx["hcp"])
        suit_len = int(suit_lens.get(actor_last_strain, 0))

        # After already rebidding own suit once, continuing again without support
        # should require very strong shape/values.
        if same_strain_count >= 2 and not (hcp_val >= 17 and suit_len >= 7):
            return False, (
                f"{hand_tag} indmelding: afvist ({_to_display_bid(cand_bid)} uden makkerstøtte efter allerede "
                f"genmeldt egen farve; kræver ca 17+ HCP og 7+ kort)."
            )

        # First unsupported self-rebid to game level is also reserved for strong long-suit hands.
        if cand_level >= 4 and not (hcp_val >= 17 and suit_len >= 7):
            return False, (
                f"{hand_tag} indmelding: afvist ({_to_display_bid(cand_bid)} uden makkerstøtte; 4-trins genmelding "
                f"i egen farve kræver ca 17+ HCP og 7+ kort)."
            )

        return True, None

    overcall_bid = None
    overcall_rule = None
    overcall_line = f"{hand_tag} indmelding: afvist."
    if int(ctx["hcp"]) >= 8:
        for s in candidate_suits:
            if suit_lens[s] < 5:
                continue
            cand = _lowest_higher_bid_for_strain(first_bid, s)
            if cand is None:
                continue

            allow_cand, reject_reason = _allow_competitive_self_rebid(cand, s)
            if not allow_cand:
                if reject_reason:
                    log_lines.append(reject_reason)
                continue

            overcall_bid = cand
            overcall_rule = "natural_overcall_basic"
            overcall_line = (
                f"{hand_tag} indmelding: OK med {_to_display_bid(cand)} "
                f"(5+ farve, HCP {int(ctx['hcp'])}, højere end {_to_display_bid(first_bid)})."
            )
            break
    else:
        overcall_line = f"{hand_tag} indmelding: afvist (HCP {int(ctx['hcp'])} < 8)."
    log_lines.append(overcall_line)

    # Priority: lead-directing doubles are explicit; otherwise allow strong long-suit overcalls to win.
    prefer_overcall = overcall_bid is not None and (
        max(suit_lens.values()) >= 6 and int(ctx["hcp"]) >= 10
    )
    parsed_overcall = _parse_contract_bid(overcall_bid) if overcall_bid is not None else None
    if (
        overcall_bid is not None
        and double_type == "takeout"
        and double_ok
        and int(ctx["hcp"]) <= 16
        and first_strain in ("H", "S")
    ):
        opposite_major = "S" if first_strain == "H" else "H"
        if (
            parsed_overcall is not None
            and parsed_overcall[1] == opposite_major
            and int(suit_lens[opposite_major]) >= 5
        ):
            prefer_overcall = True
            log_lines.append(
                f"{hand_tag} stilvalg: 5+ i modsatte major over majoråbning prioriterer indmelding fremfor oplysningsdobling."
            )

    force_double = double_type == "lead_directing"

    if force_double and double_ok:
        return {
            "dealer": second_seat,
            "profile": None,
            "bid": "X",
            "display_bid": "X",
            "rule_id": double_rule_id,
            "explanation": double_explanation,
            "log_lines": log_lines + [
                f"{hand_tag} valg: X",
                f"{hand_tag} regel-id: {double_rule_id}",
            ],
        }

    if nt_overcall_bid is not None:
        return {
            "dealer": second_seat,
            "profile": None,
            "bid": nt_overcall_bid,
            "display_bid": _to_display_bid(nt_overcall_bid),
            "rule_id": nt_overcall_rule,
            "explanation": "2. hånd vælger naturlig 1NT-indmelding med jævn hånd og hold i modpartens farve.",
            "log_lines": log_lines + [
                f"{hand_tag} valg: {_to_display_bid(nt_overcall_bid)}",
                f"{hand_tag} regel-id: {nt_overcall_rule}",
            ],
        }

    if double_ok and not prefer_overcall:
        return {
            "dealer": second_seat,
            "profile": None,
            "bid": "X",
            "display_bid": "X",
            "rule_id": double_rule_id,
            "explanation": double_explanation,
            "log_lines": log_lines + [
                f"{hand_tag} valg: X",
                f"{hand_tag} regel-id: {double_rule_id}",
            ],
        }

    if overcall_bid is not None:
        return {
            "dealer": second_seat,
            "profile": None,
            "bid": overcall_bid,
            "display_bid": _to_display_bid(overcall_bid),
            "rule_id": overcall_rule,
            "explanation": "2. hånd vælger naturlig indmelding.",
            "log_lines": log_lines + [
                f"{hand_tag} valg: {_to_display_bid(overcall_bid)}",
                f"{hand_tag} regel-id: {overcall_rule}",
            ],
        }

    return {
        "dealer": second_seat,
        "profile": None,
        "bid": "PASS",
        "display_bid": "PAS",
        "rule_id": "competitive_pass",
        "explanation": "2. hånd finder hverken oplysningsdobling eller indmelding.",
        "log_lines": log_lines + [
            f"{hand_tag} valg: PAS",
            f"{hand_tag} regel-id: competitive_pass",
        ],
    }


def _suggest_response_after_partner_takeout_double(
    row: Mapping[str, Any],
    seat: str,
    highest_contract: str,
    hand_tag: str = "4H",
    prior_calls: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    hand_col = f"{seat}_hand"
    hand_dot = row.get(hand_col)
    if hand_dot is None or str(hand_dot).strip() in ("", "None"):
        return {
            "dealer": seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "takeout_double_response_missing",
            "explanation": f"Svarhånd ({seat}) mangler hånddata; vælger PAS.",
            "log_lines": [
                f"{hand_tag} kontekst: svar efter makkers oplysningsdobling.",
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: takeout_double_response_missing",
            ],
        }

    ctx = _build_context(str(hand_dot))
    suit_lens = {
        "S": int(ctx["spades"]),
        "H": int(ctx["hearts"]),
        "D": int(ctx["diamonds"]),
        "C": int(ctx["clubs"]),
    }

    calls = list(prior_calls or [])
    partner = _partner_of(seat)
    side = _seat_side(seat)
    opp_side = "ØV" if side == "NS" else "NS"

    partner_double_idx = None
    for idx in range(len(calls) - 1, -1, -1):
        c = calls[idx]
        c_seat = _normalize_seat(c.get("dealer"))
        if c_seat != partner:
            continue
        bid_txt = str(c.get("bid") or "PASS").upper()
        rid = str(c.get("rule_id") or "")
        if bid_txt in ("X", "DBL", "DOUBLE") and "takeout_double" in rid:
            partner_double_idx = idx
        break

    if partner_double_idx is None:
        return {
            "dealer": seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "takeout_double_response_unusable",
            "explanation": "Ingen aktiv oplysningsdobling fra makker at svare på; vælger PAS.",
            "log_lines": [
                f"{hand_tag} kontekst: makkers seneste melding er ikke en oplysningsdobling.",
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: takeout_double_response_unusable",
            ],
        }

    latest_opp_contract = _latest_contract_call_by_side(calls[:partner_double_idx], opp_side)
    doubled_bid = str((latest_opp_contract or {}).get("bid") or highest_contract or "PASS").upper()
    parsed_doubled = _parse_contract_bid(doubled_bid)
    if parsed_doubled is None:
        return {
            "dealer": seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "takeout_double_response_unusable",
            "explanation": "Kan ikke identificere den kontrakt makker har doblet; vælger PAS.",
            "log_lines": [
                f"{hand_tag} kontekst: kunne ikke udlede åbners kontrakt før dobling.",
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: takeout_double_response_unusable",
            ],
        }
    _, opp_strain = parsed_doubled

    interference = False
    for c in calls[partner_double_idx + 1:]:
        c_seat = _normalize_seat(c.get("dealer"))
        if c_seat is None or _seat_side(c_seat) != opp_side:
            continue
        if _parse_contract_bid(str(c.get("bid") or "PASS").upper()) is not None:
            interference = True
            break

    resp_cfg = _responses_to_takeout_double_for_seat(seat)

    new_suit_cfg = (resp_cfg.get("new_suit_response", {}) or {}) if isinstance(resp_cfg, Mapping) else {}
    if not isinstance(new_suit_cfg, Mapping):
        new_suit_cfg = {}
    new_strength = (new_suit_cfg.get("strength", {}) or {}) if isinstance(new_suit_cfg, Mapping) else {}
    if not isinstance(new_strength, Mapping):
        new_strength = {}

    preferred_len = max(
        3,
        _int_or_default(
            ((new_suit_cfg.get("preferred_length", {}) or {}).get("cards") if isinstance(new_suit_cfg, Mapping) else 4),
            4,
        ),
    )
    minimum_len = max(
        3,
        _int_or_default(
            ((new_suit_cfg.get("minimum_possible", {}) or {}).get("cards") if isinstance(new_suit_cfg, Mapping) else 3),
            3,
        ),
    )
    simple_low, simple_high = _hcp_bounds_from_spec(new_strength, 0, 7)

    jump_cfg = (resp_cfg.get("jump_new_suit", {}) or {}) if isinstance(resp_cfg, Mapping) else {}
    if not isinstance(jump_cfg, Mapping):
        jump_cfg = {}
    jump_low, jump_high = _hcp_bounds_from_spec(jump_cfg, 8, 11)
    jump_len_min = max(3, _int_or_default(jump_cfg.get("suit_length_min", 4), 4))

    cuebid_cfg = (resp_cfg.get("cuebid_of_opponents_suit", {}) or {}) if isinstance(resp_cfg, Mapping) else {}
    if not isinstance(cuebid_cfg, Mapping):
        cuebid_cfg = {}
    cuebid_hcp_min = max(0, _int_or_default(cuebid_cfg.get("hcp_min", 12), 12))

    nt_cfg = (resp_cfg.get("notrump_responses_default", {}) or {}) if isinstance(resp_cfg, Mapping) else {}
    if not isinstance(nt_cfg, Mapping):
        nt_cfg = {}
    nt_ranges = {
        "1NT": _hcp_bounds_from_spec(nt_cfg.get("1NT") if isinstance(nt_cfg, Mapping) else None, 6, 9),
        "2NT": _hcp_bounds_from_spec(nt_cfg.get("2NT") if isinstance(nt_cfg, Mapping) else None, 10, 12),
        "3NT": _hcp_bounds_from_spec(nt_cfg.get("3NT") if isinstance(nt_cfg, Mapping) else None, 13, 15),
    }

    if interference:
        # Standard practical adjustment when opponents bid after the takeout double.
        simple_low, simple_high = 5, 10
        jump_low, jump_high = 11, 12

    sys_def = _system_def_for_seat(seat)
    shape_defs = (sys_def.get("shape_definitions", {}) or {}) if isinstance(sys_def, Mapping) else {}
    if not isinstance(shape_defs, Mapping):
        shape_defs = {}
    balanced_shapes = shape_defs.get("balanced_shapes")
    if not isinstance(balanced_shapes, list):
        balanced_shapes = [[4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2]]

    is_balanced = _shape_matches(tuple(ctx.get("shape_shdc", (0, 0, 0, 0))), list(balanced_shapes))
    stopper_in_opp = _has_stopper_in_suit(str(hand_dot), str(opp_strain))

    def _response_order() -> list[str]:
        majors = [s for s in ("H", "S") if s != opp_strain]
        minors = [s for s in ("C", "D") if s != opp_strain]

        def _sort_key(s: str) -> tuple[int, int, int]:
            cand = _lowest_higher_bid_for_strain(highest_contract, s)
            parsed = _parse_contract_bid(cand)
            lvl = int(parsed[0]) if parsed is not None else 9
            return (-int(suit_lens[s]), lvl, _strain_order(s))

        majors_sorted = sorted(majors, key=_sort_key)
        minors_sorted = sorted(minors, key=_sort_key)
        return majors_sorted + minors_sorted

    order = _response_order()

    def _pick_simple_response() -> tuple[str | None, str | None]:
        for need_len in (preferred_len, minimum_len):
            for s in order:
                if int(suit_lens[s]) < int(need_len):
                    continue
                cand = _lowest_higher_bid_for_strain(highest_contract, s)
                if cand is None:
                    continue
                return s, cand
        return None, None

    def _pick_jump_response() -> tuple[str | None, str | None]:
        for s in order:
            required_len = int(jump_len_min)
            if s in ("H", "S"):
                required_len = min(required_len, 4)
            if int(suit_lens[s]) < required_len:
                continue
            cand = _jump_bid_for_strain(highest_contract, s)
            if cand is None:
                continue
            return s, cand
        return None, None

    hcp_val = int(ctx["hcp"])
    log_lines = [
        f"{hand_tag} kontekst: makker oplysningsdoblede {_to_display_bid(doubled_bid)}.",
        f"{hand_tag} hånd: {hcp_val} HCP, shape {_shape_text(ctx)}.",
    ]
    if interference:
        log_lines.append(
            f"{hand_tag} note: modparten meldte videre efter dobling; responder-interval sænkes (ca 5-10/11-12/12+)."
        )

    if is_balanced and stopper_in_opp:
        for nt_bid in ("1NT", "2NT", "3NT"):
            lo, hi = nt_ranges[nt_bid]
            if lo <= hcp_val <= hi and _is_higher_contract(nt_bid, highest_contract):
                display = _to_display_bid(nt_bid)
                return {
                    "dealer": seat,
                    "profile": None,
                    "bid": nt_bid,
                    "display_bid": display,
                    "rule_id": "takeout_double_response_notrump",
                    "explanation": "Svar i sans med jævn hånd og hold i åbners farve.",
                    "log_lines": log_lines + [
                        f"{hand_tag} sanssvar: jævn hånd + hold i åbners farve -> {display} ({lo}-{hi} HCP).",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: takeout_double_response_notrump",
                    ],
                }

    if hcp_val >= cuebid_hcp_min and opp_strain in ("S", "H", "D", "C"):
        cuebid = _lowest_higher_bid_for_strain(highest_contract, opp_strain)
        if cuebid is not None:
            display = _to_display_bid(cuebid)
            return {
                "dealer": seat,
                "profile": None,
                "bid": cuebid,
                "display_bid": display,
                "rule_id": "takeout_double_response_cuebid",
                "explanation": "Overmelding af åbners farve viser stærk hånd efter oplysningsdobling.",
                "log_lines": log_lines + [
                    f"{hand_tag} cuebid: {hcp_val} HCP >= {cuebid_hcp_min} -> {display}.",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: takeout_double_response_cuebid",
                ],
            }

    if jump_low <= hcp_val <= jump_high:
        jump_suit, jump_bid = _pick_jump_response()
        if jump_bid is not None:
            display = _to_display_bid(jump_bid)
            return {
                "dealer": seat,
                "profile": None,
                "bid": jump_bid,
                "display_bid": display,
                "rule_id": "takeout_double_response_jump_new_suit",
                "explanation": "Springsvar i ny farve efter oplysningsdobling viser konstruktive værdier.",
                "log_lines": log_lines + [
                    f"{hand_tag} springsvar: {jump_low}-{jump_high} HCP og længde i {_to_display_bid(f'1{jump_suit}')[1:]} -> {display}.",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: takeout_double_response_jump_new_suit",
                ],
            }

    if simple_low <= hcp_val <= simple_high:
        simple_suit, simple_bid = _pick_simple_response()
        if simple_bid is not None:
            display = _to_display_bid(simple_bid)
            return {
                "dealer": seat,
                "profile": None,
                "bid": simple_bid,
                "display_bid": display,
                "rule_id": "takeout_double_response_new_suit",
                "explanation": "Svar i billigste passende farve efter oplysningsdobling.",
                "log_lines": log_lines + [
                    f"{hand_tag} ny farve: {simple_low}-{simple_high} HCP med major-prioritet -> {display}.",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: takeout_double_response_new_suit",
                ],
            }

    return {
        "dealer": seat,
        "profile": None,
        "bid": "PASS",
        "display_bid": "PAS",
        "rule_id": "takeout_double_response_pass",
        "explanation": "Svarhånden finder ingen passende melding efter oplysningsdobling.",
        "log_lines": log_lines + [
            f"{hand_tag} svar: ingen passende ny farve/sans/cuebid i interval -> PAS.",
            f"{hand_tag} valg: PAS",
            f"{hand_tag} regel-id: takeout_double_response_pass",
        ],
    }


def _suggest_third_hand_after_partner_open(
    row: Mapping[str, Any],
    third_seat: str,
    partner_opening_bid: str,
    second_call_bid: str | None,
    hand_tag: str = "3H",
    reserved_cuebid_strains: list[str] | None = None,
    prior_calls: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    hand_col = f"{third_seat}_hand"
    hand_dot = row.get(hand_col)
    if hand_dot is None or str(hand_dot).strip() in ("", "None"):
        return {
            "dealer": third_seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "third_hand_missing",
            "explanation": f"3. hånd ({third_seat}) mangler hånddata; vælger PAS.",
            "log_lines": [
                f"{hand_tag} kontekst: makker åbnede {_to_display_bid(partner_opening_bid)}, 2H={_to_display_bid(second_call_bid or 'PASS')}",
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: third_hand_missing",
            ],
        }

    parsed_partner = _parse_contract_bid(partner_opening_bid)
    if parsed_partner is None:
        return {
            "dealer": third_seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "partner_bid_unusable",
            "explanation": "Kan ikke tolke makkers åbning; vælger PAS.",
            "log_lines": [
                f"{hand_tag} kontekst: makkers åbning kunne ikke tolkes.",
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: partner_bid_unusable",
            ],
        }

    ctx = _build_context(str(hand_dot))
    partner_lvl, partner_strain = parsed_partner
    highest_contract = _highest_contract_bid_text(partner_opening_bid, second_call_bid)
    reserved = {
        str(s).upper()
        for s in (reserved_cuebid_strains or [])
        if str(s).upper() in ("S", "H", "D", "C")
    }

    log_lines = [
        f"{hand_tag} kontekst: makker åbnede {_to_display_bid(partner_opening_bid)}, 2H={_to_display_bid(second_call_bid or 'PASS')}.",
        f"{hand_tag} hånd: {int(ctx['hcp'])} HCP, shape {_shape_text(ctx)}.",
    ]
    if reserved:
        reserved_txt = "/".join(_to_display_bid(f"1{s}")[1:] for s in sorted(reserved, key=_strain_order))
        log_lines.append(f"{hand_tag} note: cuebid-farver reserveret ({reserved_txt}).")

    suit_lens = {
        "S": int(ctx["spades"]),
        "H": int(ctx["hearts"]),
        "D": int(ctx["diamonds"]),
        "C": int(ctx["clubs"]),
    }

    side_history = _side_contract_history(list(prior_calls or []), third_seat)
    fourth_unbid = _infer_fourth_unbid_suit_from_side_history(side_history)
    fsf_enabled = _is_fourth_suit_forcing_enabled_for_seat(third_seat)
    two_over_one_enabled = _is_two_over_one_gf_enabled_for_seat(third_seat)
    side_has_2o1_dhs = _side_has_two_over_one_dhs(side_history)
    opp_has_contract = _parse_contract_bid(second_call_bid) is not None
    double_ctx = _double_context_for_seat(list(prior_calls or []), third_seat)
    if opp_has_contract:
        log_lines.append(
            f"{hand_tag} dobbeltype: {double_ctx.get('double_type') or 'none'} "
            f"({double_ctx.get('context_note') or 'ingen note'})."
        )

    side_opening = side_history[0] if side_history else None
    side_response = side_history[1] if len(side_history) >= 2 else None
    open_seat = side_opening[0] if side_opening is not None else None
    open_lvl = side_opening[1] if side_opening is not None else None
    open_strain = side_opening[2] if side_opening is not None else None
    resp_seat = side_response[0] if side_response is not None else None
    resp_lvl = side_response[1] if side_response is not None else None
    resp_strain = side_response[2] if side_response is not None else None

    current_is_responder_first = (
        side_opening is not None
        and len(side_history) == 1
        and open_seat != third_seat
    )
    current_is_opener_rebid = (
        side_opening is not None
        and side_response is not None
        and open_seat == third_seat
        and resp_seat != third_seat
    )

    partner_last_contract = _latest_partner_contract_call(list(prior_calls or []), third_seat)
    partner_last_rule = str((partner_last_contract or {}).get("rule_id") or "")

    # Opener reply to partner's Stayman over 1NT (opening or natural 1NT overcall).
    if (
        current_is_opener_rebid
        and open_lvl == 1
        and open_strain == "NT"
        and resp_lvl == 2
        and resp_strain == "C"
        and partner_last_rule == "stayman_artificial"
    ):
        # If opponents have made a real contract call after Stayman, revert to competitive handling.
        if not _has_opponent_contract_after_partner_last_contract(list(prior_calls or []), third_seat):
            if int(suit_lens["H"]) >= 4:
                stayman_reply = "2H"
                stayman_note = "viser 4+ hjerter"
            elif int(suit_lens["S"]) >= 4:
                stayman_reply = "2S"
                stayman_note = "viser 4+ spar"
            else:
                stayman_reply = "2D"
                stayman_note = "afviser 4-k major"

            if _is_higher_contract(stayman_reply, highest_contract):
                display = _to_display_bid(stayman_reply)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": stayman_reply,
                    "display_bid": display,
                    "rule_id": "stayman_opener_rebid",
                    "explanation": "Åbner svarer på Stayman efter makkers 2♣.",
                    "log_lines": log_lines + [
                        f"{hand_tag} stayman-svar: {stayman_note} -> {display}.",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: stayman_opener_rebid",
                    ],
                }
        else:
            log_lines.append(
                f"{hand_tag} stayman-svar: modparten har meldt kontrakt efter 2♣, skifter til konkurrencelogik."
            )

    # Responder first call: 1m-1NT limited range (non-forcing by default).
    if (
        not opp_has_contract
        and current_is_responder_first
        and open_lvl == 1
        and open_strain in ("C", "D")
    ):
        one_nt_low, one_nt_high, one_nt_forcing, _ = _one_nt_over_minor_params_for_seat(third_seat)
        partner_minor_len = int(ctx["clubs"] if open_strain == "C" else ctx["diamonds"])
        no_four_card_major = suit_lens["S"] < 4 and suit_lens["H"] < 4
        if (
            no_four_card_major
            and partner_minor_len <= 3
            and one_nt_low <= int(ctx["hcp"]) <= one_nt_high
        ):
            cand_nt = _lowest_higher_bid_for_strain(highest_contract, "NT")
            if cand_nt is not None:
                display = _to_display_bid(cand_nt)
                responder_bucket = _responder_strength_bucket_for_hcp(third_seat, int(ctx["hcp"]))
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand_nt,
                    "display_bid": display,
                    "rule_id": "responder_one_nt_over_minor_limited",
                    "explanation": "Svarer 1NT over minor med begrænset styrkeinterval.",
                    "log_lines": log_lines + [
                        f"{hand_tag} styrke: svarhånd bucket={responder_bucket} ({int(ctx['hcp'])} HCP).",
                        f"{hand_tag} regel: 1m-1NT viser cirka {one_nt_low}-{one_nt_high} HCP ({one_nt_forcing}).",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: responder_one_nt_over_minor_limited",
                    ],
                }

    # Responder first call after 1S: weak raise is limited; stronger hands use 2-over-1 new suit.
    if (
        not opp_has_contract
        and current_is_responder_first
        and open_lvl == 1
        and open_strain == "S"
    ):
        responder_hcp = int(ctx["hcp"])
        support_len = int(suit_lens["S"])
        one_nt_low, one_nt_high, one_nt_forcing, _ = _one_nt_over_major_params_for_seat(third_seat)
        two_over_one_min, two_over_one_forcing, _ = _one_major_two_level_new_suit_rule_for_seat(third_seat)

        # Keep direct 2M raises for support hands in the low/constructive zone.
        if support_len >= 3 and 6 <= responder_hcp <= 10:
            cand_raise = _lowest_higher_bid_for_strain(highest_contract, "S")
            if cand_raise is not None:
                display = _to_display_bid(cand_raise)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand_raise,
                    "display_bid": display,
                    "rule_id": "responder_direct_major_raise_weak",
                    "explanation": "Direkte 2M-hævning bruges som svag støtte.",
                    "log_lines": log_lines + [
                        f"{hand_tag} regel: direkte majorhævning bruges i lav/kontruktiv zone (6-10 HCP).",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: responder_direct_major_raise_weak",
                    ],
                }

        has_long_lower_suit = max(int(suit_lens["H"]), int(suit_lens["D"]), int(suit_lens["C"])) >= 5
        if (
            responder_hcp < two_over_one_min
            and one_nt_low <= responder_hcp <= one_nt_high
            and not has_long_lower_suit
        ):
            cand_nt = _lowest_higher_bid_for_strain(highest_contract, "NT")
            if cand_nt is not None:
                display = _to_display_bid(cand_nt)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand_nt,
                    "display_bid": display,
                    "rule_id": "responder_one_nt_over_major_limited",
                    "explanation": "Med for få værdier til 2-over-1 vælges 1NT i aftalt interval.",
                    "log_lines": log_lines + [
                        f"{hand_tag} regel: 1M-2nyfarve kræver {two_over_one_min}+; hånd har {responder_hcp}.",
                        f"{hand_tag} regel: 1M-1NT viser cirka {one_nt_low}-{one_nt_high} HCP ({one_nt_forcing}).",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: responder_one_nt_over_major_limited",
                    ],
                }

        if responder_hcp >= two_over_one_min:
            best_new = None
            for s in sorted(("H", "D", "C"), key=lambda x: (suit_lens[x], _strain_order(x)), reverse=True):
                if s in reserved:
                    continue
                if int(suit_lens[s]) < 4:
                    continue
                cand = _lowest_higher_bid_for_strain(highest_contract, s)
                parsed = _parse_contract_bid(cand)
                if cand is None or parsed is None or parsed[0] != 2:
                    continue
                best_new = cand
                break

            if best_new is not None:
                display = _to_display_bid(best_new)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": best_new,
                    "display_bid": display,
                    "rule_id": "responder_two_over_one_new_suit",
                    "explanation": "Ny farve på 2-trinnet bruges som 2-over-1 svar.",
                    "log_lines": log_lines + [
                        f"{hand_tag} regel: 1M-2nyfarve min {two_over_one_min}+ HCP ({two_over_one_forcing}).",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: responder_two_over_one_new_suit",
                    ],
                }

    # Opener rebid after 1m-1NT with responder limited range.
    if (
        not opp_has_contract
        and current_is_opener_rebid
        and open_lvl == 1
        and open_strain in ("C", "D")
        and resp_lvl == 1
        and resp_strain == "NT"
    ):
        one_nt_low, one_nt_high, one_nt_forcing, _ = _one_nt_over_minor_params_for_seat(third_seat)
        opener_bucket = _opener_strength_bucket_for_hcp(third_seat, int(ctx["hcp"]))

        if opener_bucket == "weak" and one_nt_forcing == "non_forcing":
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": "PASS",
                "display_bid": "PAS",
                "rule_id": "opener_rebid_after_1m_1nt_weak_pass",
                "explanation": "Åbner passer med minimum mod begrænset 1NT-svar.",
                "log_lines": log_lines + [
                    f"{hand_tag} styrke: åbner bucket=weak ({int(ctx['hcp'])} HCP).",
                    f"{hand_tag} note: svarhånd begrænset til cirka {one_nt_low}-{one_nt_high} HCP.",
                    f"{hand_tag} valg: PAS",
                    f"{hand_tag} regel-id: opener_rebid_after_1m_1nt_weak_pass",
                ],
            }

        if opener_bucket == "medium":
            cand_nt = _lowest_higher_bid_for_strain(highest_contract, "NT")
            if cand_nt is not None:
                display = _to_display_bid(cand_nt)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand_nt,
                    "display_bid": display,
                    "rule_id": "opener_rebid_after_1m_1nt_medium_invite",
                    "explanation": "Åbner inviterer videre over begrænset 1NT-svar.",
                    "log_lines": log_lines + [
                        f"{hand_tag} styrke: åbner bucket=medium ({int(ctx['hcp'])} HCP).",
                        f"{hand_tag} note: svarhånd begrænset til cirka {one_nt_low}-{one_nt_high} HCP.",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: opener_rebid_after_1m_1nt_medium_invite",
                    ],
                }

        if opener_bucket == "strong":
            if _is_higher_contract("3NT", highest_contract):
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": "3NT",
                    "display_bid": "3NT",
                    "rule_id": "opener_rebid_after_1m_1nt_strong_game",
                    "explanation": "Åbner går i udgang over begrænset 1NT-svar.",
                    "log_lines": log_lines + [
                        f"{hand_tag} styrke: åbner bucket=strong ({int(ctx['hcp'])} HCP).",
                        f"{hand_tag} note: svarhånd begrænset til cirka {one_nt_low}-{one_nt_high} HCP.",
                        f"{hand_tag} valg: 3NT",
                        f"{hand_tag} regel-id: opener_rebid_after_1m_1nt_strong_game",
                    ],
                }

    # Opener rebid after 1M-2M: weak pass, medium 3M invite, strong 4M.
    if (
        not opp_has_contract
        and current_is_opener_rebid
        and open_lvl == 1
        and open_strain in ("H", "S")
        and resp_lvl == 2
        and resp_strain == open_strain
    ):
        base_hcp = int(ctx["hcp"])
        opener_bucket_hcp = _opener_strength_bucket_for_hcp(third_seat, base_hcp)
        play_pts, relation, shortness_pts, trump_len_bonus, trump_len = _playing_points_after_fit(
            ctx,
            third_seat,
            open_strain,
            row.get("vul") if isinstance(row, Mapping) else None,
        )
        opener_bucket_fit = _opener_strength_bucket_for_hcp(third_seat, play_pts)
        bucket_rank = {"weak": 0, "medium": 1, "strong": 2}
        opener_bucket = (
            opener_bucket_fit
            if bucket_rank.get(opener_bucket_fit, 0) > bucket_rank.get(opener_bucket_hcp, 0)
            else opener_bucket_hcp
        )
        relation_dk = {
            "favorable": "gunstig",
            "equal": "lige",
            "unfavorable": "ugunstig",
        }.get(relation, "lige")
        fit_lines = [
            (
                f"{hand_tag} fit-point: HCP {base_hcp} + shortness {shortness_pts} "
                f"+ trumflængdebonus {trump_len_bonus} = {play_pts} "
                f"({relation_dk} zone, trumf={trump_len})."
            ),
            f"{hand_tag} styrke: bucket {opener_bucket_hcp} -> {opener_bucket} efter fit-justering.",
        ]

        if opener_bucket == "weak":
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": "PASS",
                "display_bid": "PAS",
                "rule_id": "opener_rebid_after_1M_2M_weak_pass",
                "explanation": "Åbner signoff med svag hånd efter enkel højning.",
                "log_lines": log_lines + fit_lines + [
                    f"{hand_tag} styrke: åbner bucket=weak ({int(ctx['hcp'])} HCP).",
                    f"{hand_tag} valg: PAS",
                    f"{hand_tag} regel-id: opener_rebid_after_1M_2M_weak_pass",
                ],
            }

        target = f"3{open_strain}" if opener_bucket == "medium" else f"4{open_strain}"
        if _is_higher_contract(target, highest_contract):
            display = _to_display_bid(target)
            rid = "opener_rebid_after_1M_2M_medium_invite" if opener_bucket == "medium" else "opener_rebid_after_1M_2M_strong_game"
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": target,
                "display_bid": display,
                "rule_id": rid,
                "explanation": "Åbner viser styrkeklasse efter 1M-2M.",
                "log_lines": log_lines + fit_lines + [
                    f"{hand_tag} styrke: åbner bucket={opener_bucket} ({base_hcp} HCP).",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: {rid}",
                ],
            }

    # Opener rebid after 1M-2(new suit): prefer rebid of opening major to show minimum.
    if (
        not opp_has_contract
        and current_is_opener_rebid
        and len(side_history) == 2
        and _is_two_over_one_new_suit(open_strain, resp_strain, resp_lvl)
    ):
        two_over_one_min, two_over_one_forcing, _ = _one_major_two_level_new_suit_rule_for_seat(third_seat)
        opener_bucket = _opener_strength_bucket_for_hcp(third_seat, int(ctx["hcp"]))
        opening_len = int(suit_lens.get(str(open_strain), 0))

        if opening_len >= 6 and opener_bucket == "weak":
            cand_major = _lowest_higher_bid_for_strain(highest_contract, str(open_strain))
            if cand_major is not None:
                display = _to_display_bid(cand_major)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand_major,
                    "display_bid": display,
                    "rule_id": "opener_rebid_after_1M_2new_rebid_major",
                    "explanation": "Åbner genmelder lang major som minimumsbeskrivelse efter 2-over-1.",
                    "log_lines": log_lines + [
                        f"{hand_tag} regel: svar 1M-2nyfarve tolkes som min {two_over_one_min}+ HCP ({two_over_one_forcing}).",
                        f"{hand_tag} styrke/længde: weak-bucket + {opening_len}-kort major -> rebid af major.",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: opener_rebid_after_1M_2new_rebid_major",
                    ],
                }

        for s in sorted(("S", "H", "D", "C"), key=lambda x: (suit_lens[x], _strain_order(x)), reverse=True):
            if s in reserved or s == open_strain or s == resp_strain:
                continue
            if int(suit_lens[s]) < 4:
                continue
            cand = _lowest_higher_bid_for_strain(highest_contract, s)
            if cand is None:
                continue
            display = _to_display_bid(cand)
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": cand,
                "display_bid": display,
                "rule_id": "opener_rebid_after_1M_2new_show_side_suit",
                "explanation": "Åbner viser sidefarve efter 2-over-1.",
                "log_lines": log_lines + [
                    f"{hand_tag} regel: svar 1M-2nyfarve tolkes som min {two_over_one_min}+ HCP ({two_over_one_forcing}).",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: opener_rebid_after_1M_2new_show_side_suit",
                ],
            }

        cand_major = _lowest_higher_bid_for_strain(highest_contract, str(open_strain))
        if cand_major is not None:
            display = _to_display_bid(cand_major)
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": cand_major,
                "display_bid": display,
                "rule_id": "opener_rebid_after_1M_2new_rebid_major",
                "explanation": "Åbner genmelder major som minimumsbeskrivelse efter 2-over-1.",
                "log_lines": log_lines + [
                    f"{hand_tag} regel: svar 1M-2nyfarve tolkes som min {two_over_one_min}+ HCP ({two_over_one_forcing}).",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: opener_rebid_after_1M_2new_rebid_major",
                ],
            }

    # Responder continuation after 1M-2new-2M: with fit + game values, place contract in 4M.
    if (
        not opp_has_contract
        and len(side_history) >= 3
        and side_opening is not None
        and side_response is not None
        and open_seat != third_seat
        and resp_seat == third_seat
        and _is_two_over_one_new_suit(open_strain, resp_strain, resp_lvl)
    ):
        third_seat_side, third_lvl_side, third_strain_side = side_history[2]
        if third_seat_side == open_seat and third_strain_side == open_strain and int(third_lvl_side) >= 2:
            support_min, game_hcp_min, game_pp_min = _one_major_two_level_new_suit_then_major_rebid_params_for_seat(third_seat)
            trump_len = int(suit_lens.get(str(open_strain), 0))
            if trump_len >= support_min:
                play_pts, relation, shortness_pts, trump_len_bonus, _ = _playing_points_after_fit(
                    ctx,
                    third_seat,
                    str(open_strain),
                    row.get("vul") if isinstance(row, Mapping) else None,
                )
                if int(ctx["hcp"]) >= game_hcp_min or int(play_pts) >= game_pp_min:
                    target = f"4{open_strain}"
                    if _is_higher_contract(target, highest_contract):
                        relation_dk = {
                            "favorable": "gunstig",
                            "equal": "lige",
                            "unfavorable": "ugunstig",
                        }.get(relation, "lige")
                        display = _to_display_bid(target)
                        return {
                            "dealer": third_seat,
                            "profile": None,
                            "bid": target,
                            "display_bid": display,
                            "rule_id": "responder_after_1M_2new_2M_game_place",
                            "explanation": "Svarer placerer kontrakten i udgang efter 1M-2ny-2M med fit og game-værdier.",
                            "log_lines": log_lines + [
                                (
                                    f"{hand_tag} fit-point: HCP {int(ctx['hcp'])} + shortness {shortness_pts} "
                                    f"+ trumflængdebonus {trump_len_bonus} = {play_pts} ({relation_dk} zone)."
                                ),
                                f"{hand_tag} regel: 1M-2ny-2M med fit {trump_len} (min {support_min}), game ved HCP>={game_hcp_min} eller fit-point>={game_pp_min}.",
                                f"{hand_tag} valg: {display}",
                                f"{hand_tag} regel-id: responder_after_1M_2new_2M_game_place",
                            ],
                        }

    force_rebid_after_1d_1s = (
        not opp_has_contract
        and current_is_opener_rebid
        and len(side_history) == 2
        and open_lvl == 1
        and open_strain == "D"
        and resp_lvl == 1
        and resp_strain == "S"
        and _one_diamond_one_spade_forcing_rule_for_seat(third_seat)[1] in ("one_round", "game_force")
    )

    two_over_one_forcing, two_over_one_opener_may_pass = "", True
    if current_is_opener_rebid:
        _, two_over_one_forcing, two_over_one_opener_may_pass = _one_major_two_level_new_suit_rule_for_seat(third_seat)

    force_rebid_after_1M_2new = (
        not opp_has_contract
        and current_is_opener_rebid
        and len(side_history) == 2
        and _is_two_over_one_new_suit(open_strain, resp_strain, resp_lvl)
        and two_over_one_forcing in ("one_round", "game_force")
        and (not two_over_one_opener_may_pass)
    )

    # Reply to partner's prior fourth-suit forcing ask.
    partner_last_bid = str((partner_last_contract or {}).get("bid") or "PASS")
    partner_last_parsed = _parse_contract_bid(partner_last_bid)
    if partner_last_rule == "third_hand_fourth_suit_forcing_ask" and partner_last_parsed is not None:
        asked_strain = partner_last_parsed[1]
        asked_txt = _to_display_bid(f"1{asked_strain}")[1:]
        if _has_stopper_in_suit(str(hand_dot), asked_strain):
            cand_nt = _lowest_higher_bid_for_strain(highest_contract, "NT")
            if cand_nt is not None:
                display = _to_display_bid(cand_nt)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand_nt,
                    "display_bid": display,
                    "rule_id": "third_hand_fourth_suit_reply_3nt_with_stopper",
                    "explanation": "Svarer på 4. farve-spørgsmål med 3NT pga. hold i spurgt farve.",
                    "log_lines": log_lines + [
                        f"{hand_tag} 4SF-svar: makker spurgte via { _to_display_bid(partner_last_bid) } om hold i {asked_txt}.",
                        f"{hand_tag} 4SF-svar: hold i {asked_txt} fundet -> vælger {display}.",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: third_hand_fourth_suit_reply_3nt_with_stopper",
                    ],
                }
        log_lines.append(
            f"{hand_tag} 4SF-svar: makker spurgte om hold i {asked_txt}, men intet sikkert hold fundet -> ingen direkte sansmelding."
        )

    stayman_nt_sequence = (
        len(side_history) >= 2
        and side_history[0][1] == 1
        and side_history[0][2] == "NT"
        and side_history[1][1] == 2
        and side_history[1][2] == "C"
    )

    if fourth_unbid is not None and fsf_enabled and (not stayman_nt_sequence):
        fourth_txt = _to_display_bid(f"1{fourth_unbid}")[1:]
        if two_over_one_enabled and side_has_2o1_dhs:
            log_lines.append(
                f"{hand_tag} 4SF: naturlig behandling ({fourth_txt}) fordi 2-over-1 GF er aktiv og allerede vist i D/H/S."
            )
        else:
            stopper = _has_stopper_in_suit(str(hand_dot), fourth_unbid)
            if stopper:
                cand_nt = _lowest_higher_bid_for_strain(highest_contract, "NT")
                if cand_nt is not None:
                    display = _to_display_bid(cand_nt)
                    return {
                        "dealer": third_seat,
                        "profile": None,
                        "bid": cand_nt,
                        "display_bid": display,
                        "rule_id": "third_hand_fourth_suit_3nt_with_stopper",
                        "explanation": "4. farve er kunstig game-force; med hold i 4. farve vælges 3NT.",
                        "log_lines": log_lines + [
                            f"{hand_tag} 4SF: 4. umeldte farve er {fourth_txt}.",
                            f"{hand_tag} 4SF: hold i {fourth_txt} fundet -> vælger {display}.",
                            f"{hand_tag} valg: {display}",
                            f"{hand_tag} regel-id: third_hand_fourth_suit_3nt_with_stopper",
                        ],
                    }

            cand_ask = _lowest_higher_bid_for_strain(highest_contract, fourth_unbid)
            if cand_ask is not None:
                display = _to_display_bid(cand_ask)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand_ask,
                    "display_bid": display,
                    "rule_id": "third_hand_fourth_suit_forcing_ask",
                    "explanation": "4. farve bruges som kunstig game-force spørgemelding om hold.",
                    "log_lines": log_lines + [
                        f"{hand_tag} 4SF: 4. umeldte farve er {fourth_txt}.",
                        f"{hand_tag} 4SF: intet sikkert hold i {fourth_txt} -> kunstig spørgemelding {display}.",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: third_hand_fourth_suit_forcing_ask",
                    ],
                }

    # Responder structure after partner 1NT (opening or natural 1NT overcall): prioritize Stayman 2C.
    if partner_strain == "NT" and partner_lvl == 1 and current_is_responder_first:
        stayman = _one_nt_stayman_params_for_seat(third_seat)
        stayman_hcp_min = int(stayman.get("hcp_min", 8))
        requires_four_major = bool(stayman.get("requires_four_card_major", True))
        has_four_major = suit_lens["S"] >= 4 or suit_lens["H"] >= 4
        interference_after_nt = _has_opponent_non_pass_after_partner_last_nt(list(prior_calls or []), third_seat)

        if interference_after_nt:
            log_lines.append(
                f"{hand_tag} stayman: afvist (interferens efter makkers 1NT)."
            )
        elif int(ctx["hcp"]) >= stayman_hcp_min and ((not requires_four_major) or has_four_major):
            if _is_higher_contract("2C", highest_contract):
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": "2C",
                    "display_bid": _to_display_bid("2C"),
                    "rule_id": "stayman_artificial",
                    "artificial": True,
                    "explanation": "Responder vælger Stayman 2♣ over makkers 1NT.",
                    "log_lines": log_lines + [
                        f"{hand_tag} stayman: style={stayman.get('style')} med min {stayman_hcp_min} HCP.",
                        f"{hand_tag} stayman: majorlængder H{int(ctx['hearts'])}/S{int(ctx['spades'])} -> vælger 2♣.",
                        f"{hand_tag} valg: {_to_display_bid('2C')}",
                        f"{hand_tag} regel-id: stayman_artificial",
                    ],
                }
        else:
            need = []
            if int(ctx["hcp"]) < stayman_hcp_min:
                need.append(f"HCP < {stayman_hcp_min}")
            if requires_four_major and (not has_four_major):
                need.append("ingen 4-k major")
            if need:
                log_lines.append(f"{hand_tag} stayman: afvist ({'; '.join(need)}).")

    # Stayman continuations after 1NT-2C-2D by style config.
    if len(side_history) == 3:
        h0_seat, h0_lvl, h0_strain = side_history[0]
        h1_seat, h1_lvl, h1_strain = side_history[1]
        h2_seat, h2_lvl, h2_strain = side_history[2]

        stayman_2d_cont = _one_nt_stayman_continuation_block_for_seat(
            third_seat,
            "responder_continuations_after_1NT_2C_2D",
        )

        # Responder continuation: 1NT-2C-2D-(?).
        if (
            h0_lvl == 1 and h0_strain == "NT"
            and h1_lvl == 2 and h1_strain == "C"
            and h2_lvl == 2 and h2_strain == "D"
            and h0_seat != third_seat
            and h1_seat == third_seat
            and h2_seat == h0_seat
            and (not _has_opponent_contract_after_partner_last_contract(list(prior_calls or []), third_seat))
            and stayman_2d_cont
        ):
            hcp_val = int(ctx["hcp"])

            if "2H" in stayman_2d_cont and int(suit_lens["S"]) >= 4:
                if _is_higher_contract("2H", highest_contract):
                    return {
                        "dealer": third_seat,
                        "profile": None,
                        "bid": "2H",
                        "display_bid": _to_display_bid("2H"),
                        "rule_id": "stayman_responder_continuation_2h",
                        "explanation": "Stayman-fortsættelse: 2♥ viser 4+ spar (evt. også 4♥).",
                        "log_lines": log_lines + [
                            f"{hand_tag} stayman-fortsættelse: efter 1NT-2♣-2♦ med 4+ spar vælges 2♥.",
                            f"{hand_tag} valg: {_to_display_bid('2H')}",
                            f"{hand_tag} regel-id: stayman_responder_continuation_2h",
                        ],
                    }

            if "2S" in stayman_2d_cont and int(suit_lens["H"]) >= 4 and int(suit_lens["S"]) < 4:
                if _is_higher_contract("2S", highest_contract):
                    return {
                        "dealer": third_seat,
                        "profile": None,
                        "bid": "2S",
                        "display_bid": _to_display_bid("2S"),
                        "rule_id": "stayman_responder_continuation_2s",
                        "explanation": "Stayman-fortsættelse: 2♠ viser 4+ hjerter og benægter 4 spar.",
                        "log_lines": log_lines + [
                            f"{hand_tag} stayman-fortsættelse: efter 1NT-2♣-2♦ med 4+♥ uden 4♠ vælges 2♠.",
                            f"{hand_tag} valg: {_to_display_bid('2S')}",
                            f"{hand_tag} regel-id: stayman_responder_continuation_2s",
                        ],
                    }

            cont_2nt = (stayman_2d_cont.get("2NT", {}) or {}) if isinstance(stayman_2d_cont, Mapping) else {}
            cont_3nt = (stayman_2d_cont.get("3NT", {}) or {}) if isinstance(stayman_2d_cont, Mapping) else {}

            lo_2nt, hi_2nt = _hcp_bounds_from_spec(cont_2nt if isinstance(cont_2nt, Mapping) else None, 8, 9)
            lo_3nt, hi_3nt = _hcp_bounds_from_spec(cont_3nt if isinstance(cont_3nt, Mapping) else None, 10, 15)

            if "2NT" in stayman_2d_cont and lo_2nt <= hcp_val <= hi_2nt and _is_higher_contract("2NT", highest_contract):
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": "2NT",
                    "display_bid": _to_display_bid("2NT"),
                    "rule_id": "stayman_responder_continuation_2nt",
                    "explanation": "Stayman-fortsættelse: invit uden 4-k major.",
                    "log_lines": log_lines + [
                        f"{hand_tag} stayman-fortsættelse: invit uden 4-k major ({lo_2nt}-{hi_2nt} HCP) -> 2NT.",
                        f"{hand_tag} valg: {_to_display_bid('2NT')}",
                        f"{hand_tag} regel-id: stayman_responder_continuation_2nt",
                    ],
                }

            if "3NT" in stayman_2d_cont and lo_3nt <= hcp_val <= hi_3nt and _is_higher_contract("3NT", highest_contract):
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": "3NT",
                    "display_bid": _to_display_bid("3NT"),
                    "rule_id": "stayman_responder_continuation_3nt",
                    "explanation": "Stayman-fortsættelse: 3NT to play.",
                    "log_lines": log_lines + [
                        f"{hand_tag} stayman-fortsættelse: to-play interval ({lo_3nt}-{hi_3nt} HCP) -> 3NT.",
                        f"{hand_tag} valg: {_to_display_bid('3NT')}",
                        f"{hand_tag} regel-id: stayman_responder_continuation_3nt",
                    ],
                }

    # Opener followup: 1NT-2C-2D-2H/2S-(?).
    if len(side_history) == 4 and current_is_opener_rebid:
        h0_seat, h0_lvl, h0_strain = side_history[0]
        h1_seat, h1_lvl, h1_strain = side_history[1]
        h2_seat, h2_lvl, h2_strain = side_history[2]
        h3_seat, h3_lvl, h3_strain = side_history[3]
        stayman_2d_cont = _one_nt_stayman_continuation_block_for_seat(
            third_seat,
            "responder_continuations_after_1NT_2C_2D",
        )

        if (
            h0_lvl == 1 and h0_strain == "NT"
            and h1_lvl == 2 and h1_strain == "C"
            and h2_lvl == 2 and h2_strain == "D"
            and h3_lvl == 2 and h3_strain in ("H", "S")
            and h0_seat == third_seat
            and h1_seat == h3_seat
            and h2_seat == h0_seat
            and (not _has_opponent_contract_after_partner_last_contract(list(prior_calls or []), third_seat))
            and stayman_2d_cont
        ):
            key = "2H" if h3_strain == "H" else "2S"
            move_cfg = (stayman_2d_cont.get(key, {}) or {}) if isinstance(stayman_2d_cont, Mapping) else {}
            followup = (move_cfg.get("opener_followup", {}) or {}) if isinstance(move_cfg, Mapping) else {}
            if isinstance(followup, Mapping):
                if h3_strain == "H":
                    has_fit = int(suit_lens["S"]) >= 3
                    fit_key = "with_spade_fit" if has_fit else "without_spade_fit"
                else:
                    has_fit = int(suit_lens["H"]) >= 3
                    fit_key = "with_heart_fit" if has_fit else "without_heart_fit"

                follow_choice = (followup.get(fit_key, {}) or {}) if isinstance(followup, Mapping) else {}
                target = str((follow_choice.get("bid") if isinstance(follow_choice, Mapping) else "") or "").strip().upper()

                # In this structure opener decides the final strain: after 1NT-2C-2D-2H,
                # opener with no spade fit may still choose hearts directly with 4+ hearts.
                if h3_strain == "H" and (not has_fit) and int(suit_lens["H"]) >= 4:
                    target = "4H"

                if _parse_contract_bid(target) is not None and _is_higher_contract(target, highest_contract):
                    display = _to_display_bid(target)
                    return {
                        "dealer": third_seat,
                        "profile": None,
                        "bid": target,
                        "display_bid": display,
                        "rule_id": "stayman_opener_followup",
                        "explanation": "Åbner følger Stayman-aftalen efter responderens fortsættelse.",
                        "log_lines": log_lines + [
                            f"{hand_tag} stayman-opfølgning: {fit_key} -> {display}.",
                            f"{hand_tag} valg: {display}",
                            f"{hand_tag} regel-id: stayman_opener_followup",
                        ],
                    }

    if opp_has_contract:
        dbl_type = str(double_ctx.get("double_type") or "none")
        opp_level = int(double_ctx.get("latest_opp_contract_level") or 0)
        opp_strain = str(double_ctx.get("latest_opp_contract_strain") or "")

        if dbl_type == "lead_directing":
            if (
                _is_lead_directing_double_enabled_for_seat(third_seat)
                and opp_strain in ("S", "H", "D", "C")
                and int(ctx["hcp"]) >= 8
            ):
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": "X",
                    "display_bid": "X",
                    "rule_id": "lead_directing_double_basic",
                    "explanation": "Dobling af kunstig modpartsmelding er udspilsdirigerende.",
                    "log_lines": log_lines + [
                        f"{hand_tag} udspilsdirigerende dobling: OK mod kunstig {_to_display_bid(double_ctx.get('latest_opp_contract_bid') or '')}.",
                        f"{hand_tag} valg: X",
                        f"{hand_tag} regel-id: lead_directing_double_basic",
                    ],
                }

        elif dbl_type == "negative":
            neg = _negative_double_params_for_seat(third_seat)
            two_majors_over_minor = opp_strain in ("C", "D") and suit_lens["H"] >= 4 and suit_lens["S"] >= 4
            other_major_over_major = (opp_strain == "H" and suit_lens["S"] >= 4) or (opp_strain == "S" and suit_lens["H"] >= 4)
            minors_over_major = opp_strain in ("H", "S") and suit_lens["C"] >= 4 and suit_lens["D"] >= 4
            shape_ok = two_majors_over_minor or other_major_over_major or minors_over_major
            partner_len_now = int(
                ctx["spades"] if partner_strain == "S"
                else ctx["hearts"] if partner_strain == "H"
                else ctx["diamonds"] if partner_strain == "D"
                else ctx["clubs"]
            )
            support_call_available = (
                partner_len_now >= 3
                and _lowest_higher_bid_for_strain(highest_contract, partner_strain) is not None
            )
            natural_new_call_available = False
            for s in ("S", "H", "D", "C"):
                if s == partner_strain or s in reserved:
                    continue
                if suit_lens[s] < 4:
                    continue
                if _lowest_higher_bid_for_strain(highest_contract, s) is None:
                    continue
                natural_new_call_available = True
                break

            prefer_negative = two_majors_over_minor or (
                shape_ok and (not support_call_available) and (not natural_new_call_available)
            )
            if (
                bool(neg.get("enabled", True))
                and opp_level <= int(neg.get("max_level", 2))
                and int(ctx["hcp"]) >= int(neg.get("hcp_min", 6))
                and prefer_negative
            ):
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": "X",
                    "display_bid": "X",
                    "rule_id": "negative_double_basic",
                    "explanation": "Dobling i denne position tolkes som negativ dobling.",
                    "log_lines": log_lines + [
                        f"{hand_tag} negativ dobling: OK (niveau <= {int(neg.get('max_level', 2))}, HCP >= {int(neg.get('hcp_min', 6))}).",
                        f"{hand_tag} valg: X",
                        f"{hand_tag} regel-id: negative_double_basic",
                    ],
                }

        elif dbl_type == "penalty":
            opp_len = int(suit_lens.get(opp_strain, 0))
            vulnerability = row.get("vul") if isinstance(row, Mapping) else None
            sac_double, sac_reason = _sacrifice_double_is_better(
                ctx, list(prior_calls or []), third_seat,
                opp_level, opp_strain, vulnerability, opp_len,
            )
            shape_ok = opp_strain in ("S", "H", "D", "C") and int(ctx["hcp"]) >= 10 and opp_len >= 5
            if sac_double or shape_ok:
                if sac_double:
                    expl_note = f"Offervurdering: {sac_reason}."
                else:
                    expl_note = "Styrke + længde i modpartens farve."
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": "X",
                    "display_bid": "X",
                    "rule_id": "penalty_double_basic",
                    "explanation": "Dobling bruges som strafdobling i denne kontekst.",
                    "log_lines": log_lines + [
                        f"{hand_tag} strafdobling: OK — {expl_note}",
                        f"{hand_tag} valg: X",
                        f"{hand_tag} regel-id: penalty_double_basic",
                    ],
                }

    # 3H when partner opened NT: simple invite/game or pass.
    if partner_strain == "NT":
        if int(ctx["hcp"]) >= 10:
            cand = _lowest_higher_bid_for_strain(highest_contract, "NT")
            if cand is not None:
                display = _to_display_bid(cand)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": cand,
                    "display_bid": display,
                    "rule_id": "third_hand_nt_raise",
                    "explanation": "3. hånd inviterer/går i sans efter makkers sansåbning.",
                    "log_lines": log_lines + [
                        f"{hand_tag} sanssvar: OK med {display}.",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: third_hand_nt_raise",
                    ],
                }
        log_lines.append(f"{hand_tag} sanssvar: afvist (for få værdier til invitation/udgang).")
        return {
            "dealer": third_seat,
            "profile": None,
            "bid": "PASS",
            "display_bid": "PAS",
            "rule_id": "third_hand_nt_pass",
            "explanation": "3. hånd passer efter makkers sansåbning.",
            "log_lines": log_lines + [
                f"{hand_tag} valg: PAS",
                f"{hand_tag} regel-id: third_hand_nt_pass",
            ],
        }

    # After our takeout double and partner's constructive major response,
    # jump to game with clear fit strength.
    actor_has_takeout_double = any(
        _normalize_seat(c.get("dealer")) == third_seat
        and str(c.get("bid") or "").upper() in ("X", "DBL", "DOUBLE")
        and "takeout_double" in str(c.get("rule_id") or "")
        for c in (prior_calls or [])
    )
    if (
        actor_has_takeout_double
        and str(partner_last_rule) == "takeout_double_response_jump_new_suit"
        and partner_strain in ("H", "S")
    ):
        fit_len = int(ctx["hearts"] if partner_strain == "H" else ctx["spades"])
        play_pts, relation, shortness_pts, trump_len_bonus, trump_len = _playing_points_after_fit(
            ctx,
            third_seat,
            partner_strain,
            row.get("vul") if isinstance(row, Mapping) else None,
        )
        if fit_len >= 3 and (int(ctx["hcp"]) >= 16 or int(play_pts) >= 18):
            target = f"4{partner_strain}"
            if _is_higher_contract(target, highest_contract):
                relation_dk = {
                    "favorable": "gunstig",
                    "equal": "lige",
                    "unfavorable": "ugunstig",
                }.get(relation, "lige")
                display = _to_display_bid(target)
                return {
                    "dealer": third_seat,
                    "profile": None,
                    "bid": target,
                    "display_bid": display,
                    "rule_id": "third_hand_takeout_game_raise_with_fit",
                    "explanation": "Efter oplysningsdobling hæves til udgang med fit og stærke værdier.",
                    "log_lines": log_lines + [
                        (
                            f"{hand_tag} fit-point: HCP {int(ctx['hcp'])} + shortness {shortness_pts} "
                            f"+ trumflængdebonus {trump_len_bonus} = {play_pts} ({relation_dk} zone, trumf={trump_len})."
                        ),
                        f"{hand_tag} regel: efter takeout + konstruktivt majorsvar hæves til 4M ved HCP>=16 eller fit-point>=18.",
                        f"{hand_tag} valg: {display}",
                        f"{hand_tag} regel-id: third_hand_takeout_game_raise_with_fit",
                    ],
                }

    # After partner's level-2 minor support, probe 4-card majors before further minor raises.
    if partner_strain in ("C", "D") and partner_lvl >= 2 and int(ctx["hcp"]) >= 10:
        for major in ("H", "S"):
            if suit_lens[major] < 4:
                continue
            if major in reserved:
                continue
            cand = _lowest_higher_bid_for_strain(highest_contract, major)
            if cand is None:
                continue
            display = _to_display_bid(cand)
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": cand,
                "display_bid": display,
                "rule_id": "third_hand_minor_support_major_probe",
                "explanation": "Viser 4-k major efter minor-støtte før yderligere minorhævning.",
                "log_lines": log_lines + [
                    f"{hand_tag} major-probe: OK med {display} efter minor-støtte.",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: third_hand_minor_support_major_probe",
                ],
            }

    # Suit opening by partner: simple raise > new suit > pass.
    # Guard: if opener (third_seat) has already concluded the Stayman sequence with
    # stayman_opener_followup (e.g. 3NT), do not raise into a suit contract here —
    # the final strain was already determined; just pass.
    opener_already_placed_contract = any(
        str(c.get("rule_id") or "") == "stayman_opener_followup"
        and _normalize_seat(c.get("dealer")) == third_seat
        for c in (prior_calls or [])
    )
    if opener_already_placed_contract:
        log_lines.append(
            f"{hand_tag} simple-raise/ny-farve: springes over (åbner har allerede placeret kontrakten via stayman_opener_followup)."
        )

    partner_len = int(ctx["spades"] if partner_strain == "S" else ctx["hearts"] if partner_strain == "H" else ctx["diamonds"] if partner_strain == "D" else ctx["clubs"])

    if partner_len >= 3 and int(ctx["hcp"]) >= 6 and (not opener_already_placed_contract):
        cand = _lowest_higher_bid_for_strain(highest_contract, partner_strain)
        if cand is not None:
            display = _to_display_bid(cand)
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": cand,
                "display_bid": display,
                "rule_id": "third_hand_simple_raise",
                "explanation": "3. hånd støtter makkers åbningsfarve.",
                "log_lines": log_lines + [
                    f"{hand_tag} støtte: OK ({partner_len} trumf, {int(ctx['hcp'])} HCP).",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: third_hand_simple_raise",
                ],
            }

    best_new = None
    if not opener_already_placed_contract:
        for s in sorted(("S", "H", "D", "C"), key=lambda x: (suit_lens[x], _strain_order(x)), reverse=True):
            if s == partner_strain:
                continue
            if s in reserved:
                continue
            if suit_lens[s] < 4 or int(ctx["hcp"]) < 6:
                continue
            cand = _lowest_higher_bid_for_strain(highest_contract, s)
            if cand is None:
                continue
            best_new = cand
            break

    if best_new is not None:
        display = _to_display_bid(best_new)
        return {
            "dealer": third_seat,
            "profile": None,
            "bid": best_new,
            "display_bid": display,
            "rule_id": "third_hand_new_suit_basic",
            "explanation": "3. hånd melder ny farve som simpelt svar.",
            "log_lines": log_lines + [
                f"{hand_tag} ny-farve: OK med {display}.",
                f"{hand_tag} valg: {display}",
                f"{hand_tag} regel-id: third_hand_new_suit_basic",
            ],
        }

    force_rebid_rule_id = None
    force_rebid_note = ""
    if force_rebid_after_1d_1s:
        force_rebid_rule_id = "opener_rebid_after_1d_1s_forced_rebid"
        force_rebid_note = "1♦-1♠ er forcerende én runde; PAS ikke tilladt."
    elif force_rebid_after_1M_2new:
        force_rebid_rule_id = "opener_rebid_after_1M_2new_forced_rebid"
        force_rebid_note = "1M-ny farve på 2-trinnet er forcerende; PAS ikke tilladt."

    if force_rebid_rule_id is not None:
        cand_nt = _lowest_higher_bid_for_strain(highest_contract, "NT")
        if cand_nt is not None:
            display = _to_display_bid(cand_nt)
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": cand_nt,
                "display_bid": display,
                "rule_id": force_rebid_rule_id,
                "explanation": "Forcerende sekvens: åbner skal byde igen.",
                "log_lines": log_lines + [
                    f"{hand_tag} regel: {force_rebid_note}",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: {force_rebid_rule_id}",
                ],
            }

        for suit in ("C", "D", "H", "S"):
            cand = _lowest_higher_bid_for_strain(highest_contract, suit)
            if cand is None:
                continue
            display = _to_display_bid(cand)
            return {
                "dealer": third_seat,
                "profile": None,
                "bid": cand,
                "display_bid": display,
                "rule_id": force_rebid_rule_id,
                "explanation": "Forcerende sekvens: åbner skal byde igen.",
                "log_lines": log_lines + [
                    f"{hand_tag} regel: {force_rebid_note}",
                    f"{hand_tag} valg: {display}",
                    f"{hand_tag} regel-id: {force_rebid_rule_id}",
                ],
            }

    return {
        "dealer": third_seat,
        "profile": None,
        "bid": "PASS",
        "display_bid": "PAS",
        "rule_id": "third_hand_pass",
        "explanation": "3. hånd finder ikke et egnet svar og passer.",
        "log_lines": log_lines + [
            f"{hand_tag} svar: afvist (ingen støtte/ny farve med tilstrækkelige værdier).",
            f"{hand_tag} valg: PAS",
            f"{hand_tag} regel-id: third_hand_pass",
        ],
    }


def _is_higher_contract(candidate_bid: str | None, reference_bid: str | None) -> bool:
    cand = _parse_contract_bid(candidate_bid)
    ref = _parse_contract_bid(reference_bid)
    if cand is None:
        return False
    if ref is None:
        return True
    if cand[0] > ref[0]:
        return True
    if cand[0] == ref[0] and _strain_order(cand[1]) > _strain_order(ref[1]):
        return True
    return False


def _is_legal_double_call(prior_calls: list[dict[str, Any]] | None, seat: str | None) -> bool:
    seat_norm = _normalize_seat(seat)
    if seat_norm is None:
        return False

    side = _seat_side(seat_norm)
    opp_side = "ØV" if side == "NS" else "NS"

    for prev in reversed(list(prior_calls or [])):
        prev_bid = str(prev.get("bid") or "PASS").upper()
        if _is_pass_bid(prev_bid):
            continue

        # Double is only legal over the latest non-pass opponent contract call.
        if _parse_contract_bid(prev_bid) is None:
            return False

        prev_seat = _normalize_seat(prev.get("dealer"))
        if prev_seat is None:
            return False
        return _seat_side(prev_seat) == opp_side

    return False


def _legalize_competitive_contract(
    call: dict[str, Any],
    reference_bid: str | None,
    hand_tag: str,
    prior_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bid = str(call.get("bid") or "PASS").upper()
    if bid in ("PASS", "PAS"):
        return call

    if bid in ("X", "DBL", "DOUBLE"):
        if _is_legal_double_call(prior_calls, str(call.get("dealer") or "")):
            return call

        call["bid"] = "PASS"
        call["display_bid"] = "PAS"
        call["rule_id"] = "illegal_competitive_double_pass"
        call["log_lines"] = list(call.get("log_lines") or []) + [
            f"{hand_tag} justering: dobling ikke lovlig i denne position, skifter til PAS.",
        ]
        return call

    if _is_higher_contract(bid, reference_bid):
        return call

    parsed = _parse_contract_bid(bid)
    if parsed is None:
        return call

    fixed = _lowest_higher_bid_for_strain(reference_bid, parsed[1])
    if fixed is not None:
        call["bid"] = fixed
        call["display_bid"] = _to_display_bid(fixed)
        call["rule_id"] = f"{call.get('rule_id', 'rule')}_legalized"
        call["log_lines"] = list(call.get("log_lines") or []) + [
            f"{hand_tag} justering: melding hævet til {call['display_bid']} for at være over seneste kontrakt.",
        ]
        return call

    call["bid"] = "PASS"
    call["display_bid"] = "PAS"
    call["rule_id"] = "illegal_competitive_bid_pass"
    call["log_lines"] = list(call.get("log_lines") or []) + [
        f"{hand_tag} justering: ingen lovlig højere kontrakt, skifter til PAS.",
    ]
    return call


def _infer_public_bid_evidence(state: Any, seat: str, bid: str) -> BidEvidence:
    """Infer public range evidence from one call.

    The model is intentionally conservative and only uses public auction info.
    """
    btxt = str(bid or "PASS").strip().upper().replace(" ", "")
    evidence = BidEvidence(source=f"offentlig melding {seat}:{_to_display_bid(btxt)}")
    parsed = _parse_contract_bid(btxt)
    latest_side_contract = _latest_side_contract_in_state(state, seat)

    if btxt in ("PASS", "PAS"):
        if state.highest_contract is None:
            evidence.hcp_range = ValueRange(0.0, 11.0)
            evidence.notes.append("Tidligt PAS giver normalt begrænset styrke.")
        else:
            evidence.hcp_range = ValueRange(0.0, 15.0)
            evidence.notes.append("PAS i konkurrence begrænser typisk offensiv styrke.")
        return evidence

    if btxt in ("X", "DBL", "DOUBLE"):
        if latest_side_contract is not None:
            evidence.hcp_range = ValueRange(6.0, 15.0)
            evidence.notes.append("Dobling efter makkers kontrakt tolkes som negativ dobling.")
        else:
            high = _parse_contract_bid(state.highest_contract)
            if high is not None and high[1] in ("S", "H", "D", "C"):
                evidence.hcp_range = ValueRange(11.0, 19.0)
                evidence.notes.append("Dobling uden makkerkontrakt tolkes som takeout/konkurrencestyrke.")
            else:
                evidence.hcp_range = ValueRange(10.0, 18.0)
                evidence.notes.append("Dobling tolkes som konkurrencestyrke i denne MVP-model.")
        return evidence

    if parsed is None:
        evidence.notes.append("Melding kunne ikke tolkes som kontrakt; ingen stramning.")
        return evidence

    level, strain = parsed

    if (
        strain == "NT"
        and level == 1
        and latest_side_contract is not None
        and latest_side_contract[0] != seat
        and latest_side_contract[1] == 1
        and latest_side_contract[2] in ("C", "D")
    ):
        low, high, forcing, limited = _one_nt_over_minor_params_for_seat(seat)
        evidence.hcp_range = ValueRange(float(low), float(high))
        evidence.notes.append(f"1NT over minor: {low}-{high} HCP ({forcing}).")
        if limited:
            evidence.notes.append("Responder is limited by agreement in this sequence.")
        return evidence

    if (
        strain == "NT"
        and level == 1
        and latest_side_contract is not None
        and latest_side_contract[0] != seat
        and latest_side_contract[1] == 1
        and latest_side_contract[2] in ("H", "S")
    ):
        low, high, forcing, limited = _one_nt_over_major_params_for_seat(seat)
        evidence.hcp_range = ValueRange(float(low), float(high))
        evidence.notes.append(f"1NT over major: {low}-{high} HCP ({forcing}).")
        if limited:
            evidence.notes.append("Responder is limited by agreement in this sequence.")
        return evidence

    if (
        level == 1
        and strain == "S"
        and latest_side_contract is not None
        and latest_side_contract[0] != seat
        and latest_side_contract[1] == 1
        and latest_side_contract[2] == "D"
    ):
        hcp_min, forcing, limited = _one_diamond_one_spade_forcing_rule_for_seat(seat)
        evidence.natural_strain = "S"
        evidence.suit_min["S"] = 4
        evidence.hcp_range = ValueRange(float(hcp_min), 37.0)
        evidence.notes.append(f"1D-1S: min {hcp_min} HCP, {forcing}, limited={limited}.")
        return evidence

    if (
        level == 2
        and strain in ("S", "H", "D", "C")
        and latest_side_contract is not None
        and latest_side_contract[0] != seat
        and latest_side_contract[1] == 1
        and _is_two_over_one_new_suit(latest_side_contract[2], strain, level)
    ):
        hcp_min, forcing, opener_may_pass = _one_major_two_level_new_suit_rule_for_seat(seat)
        evidence.natural_strain = strain
        evidence.suit_min[strain] = 4
        evidence.hcp_range = ValueRange(float(hcp_min), 37.0)
        evidence.notes.append(
            f"1{latest_side_contract[2]}-2{strain}: min {hcp_min} HCP, {forcing}, opener_may_pass={opener_may_pass}."
        )
        return evidence

    if strain == "NT":
        if level == 1:
            evidence.hcp_range = ValueRange(14.0, 18.0)
        elif level == 2:
            evidence.hcp_range = ValueRange(19.0, 22.0)
        else:
            evidence.hcp_range = ValueRange(16.0, 30.0)
        evidence.notes.append("Sansmelding giver styrkeindikation uden kendt trumffit.")
        return evidence

    evidence.natural_strain = strain
    if level == 1:
        evidence.hcp_range = ValueRange(11.0, 21.0)
        evidence.suit_min[strain] = 4
    elif level == 2:
        evidence.hcp_range = ValueRange(8.0, 18.0)
        evidence.suit_min[strain] = 5
    elif level == 3:
        evidence.hcp_range = ValueRange(6.0, 16.0)
        evidence.suit_min[strain] = 5
    else:
        evidence.hcp_range = ValueRange(5.0, 14.0)
        evidence.suit_min[strain] = 6

    prev_side_contract = None
    for prev in reversed(state.calls):
        if _seat_side(prev.seat) != _seat_side(seat):
            continue
        p = _parse_contract_bid(prev.bid)
        if p is None:
            continue
        prev_side_contract = p
        break
    if prev_side_contract is not None and prev_side_contract[1] == strain and level >= prev_side_contract[0]:
        evidence.fit_with_partner_strain = strain
        evidence.notes.append("Hævning af sidefarve tolkes som fit-visning.")

    return evidence


def _build_actor_state_for_decision(
    row: Mapping[str, Any],
    actor_seat: str,
    prior_calls: list[dict[str, Any]],
) -> Any:
    dealer = _normalize_seat(row.get("dealer"))
    if dealer is None and prior_calls:
        dealer = _normalize_seat(prior_calls[0].get("dealer"))
    if dealer is None:
        dealer = actor_seat

    own_hand = row.get(f"{actor_seat}_hand")
    own_hand_dot = None
    if own_hand is not None and str(own_hand).strip() not in ("", "None"):
        own_hand_dot = str(own_hand)

    state = create_auction_state(
        perspective_seat=actor_seat,
        dealer=dealer,
        vulnerability=str(row.get("vul") or row.get("zone") or ""),
        own_hand_dot=own_hand_dot,
    )

    for prev in prior_calls:
        p_seat = _normalize_seat(prev.get("dealer"))
        if p_seat is None:
            continue
        p_bid = str(prev.get("bid") or "PASS").upper()
        evidence = _infer_public_bid_evidence(state, p_seat, p_bid)
        apply_bid_evidence(state, p_seat, p_bid, evidence)

    return state


def _display_strain(strain: str) -> str:
    if strain == "NT":
        return "NT"
    return _to_display_bid(f"1{strain}")[1:]


def _apply_state_ceiling_to_call(
    row: Mapping[str, Any],
    prior_calls: list[dict[str, Any]],
    seat: str,
    call: dict[str, Any],
    hand_tag: str,
) -> dict[str, Any]:
    """Attach range-based explanation and enforce a stop ceiling for contracts."""
    out = dict(call)
    bid_txt = str(out.get("bid") or "PASS").strip().upper()
    parsed_bid = _parse_contract_bid(bid_txt)

    try:
        state = _build_actor_state_for_decision(row, seat, prior_calls)

        eval_strain = None
        if parsed_bid is not None:
            eval_strain = parsed_bid[1]
        elif state.highest_contract is not None:
            high = _parse_contract_bid(state.highest_contract)
            if high is not None:
                eval_strain = high[1]
        if eval_strain is None:
            eval_strain = "NT"

        estimate = estimate_side_potential(state, seat, eval_strain)
        partner_lines = explain_partner_knowledge(state, seat)

        lines = list(out.get("log_lines") or [])
        if partner_lines:
            lines.append(f"{hand_tag} state: {partner_lines[0]}")
        if len(partner_lines) > 1:
            lines.append(f"{hand_tag} state: {partner_lines[1]}")
        lines.append(
            f"{hand_tag} state: side {_seat_side(seat)} {_display_strain(eval_strain)} stikestimat "
            f"{estimate.tricks_range.pretty()} (conf {estimate.confidence:.2f})."
        )

        if parsed_bid is not None:
            required = 6 + parsed_bid[0]
            rule_id_txt = str(out.get("rule_id") or "")
            keep_constructive_3nt = "fourth_suit_reply_3nt_with_stopper" in rule_id_txt
            keep_game_place_major = "responder_after_1M_2new_2M_game_place" in rule_id_txt
            keep_competitive_one_nt = (
                "natural_one_nt_overcall" in rule_id_txt and str(out.get("bid") or "").upper() == "1NT"
            )
            keep_stayman_artificial = "stayman_artificial" in rule_id_txt
            keep_stayman_opener_rebid = "stayman_opener_rebid" in rule_id_txt
            keep_stayman_followup = (
                "stayman_opener_followup" in rule_id_txt
                or "stayman_responder_continuation_" in rule_id_txt
                or "stayman_responder_correction" in rule_id_txt
            )
            hard_reject = (
                (not keep_competitive_one_nt)
                and (not keep_stayman_artificial)
                and (not keep_stayman_opener_rebid)
                and (not keep_stayman_followup)
                and required > (estimate.tricks_range.high + 0.01)
            )
            soft_reject = (
                (not keep_constructive_3nt)
                and (not keep_game_place_major)
                and (not keep_competitive_one_nt)
                and (not keep_stayman_artificial)
                and (not keep_stayman_opener_rebid)
                and (not keep_stayman_followup)
                and estimate.confidence >= 0.35
                and required > (estimate.tricks_range.midpoint + 0.50)
            )
            if hard_reject or soft_reject:
                out["bid"] = "PASS"
                out["display_bid"] = "PAS"
                out["rule_id"] = f"{out.get('rule_id', 'rule')}_range_ceiling_pass"
                lines.append(
                    f"{hand_tag} stop: {_to_display_bid(bid_txt)} kræver {required} stik, "
                    f"estimeret range {estimate.tricks_range.pretty()} -> PAS."
                )
            else:
                lines.append(
                    f"{hand_tag} state: {_to_display_bid(bid_txt)} kræver {required} stik og er indenfor range-estimat."
                )

        out["log_lines"] = lines
        return out
    except Exception as exc:
        out["log_lines"] = list(out.get("log_lines") or []) + [
            f"{hand_tag} state: range-estimat utilgængeligt ({exc}).",
        ]
        return out


def _prefixed_call_log_lines(call: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(call, Mapping):
        return []
    seat = _normalize_seat(call.get("dealer"))
    seat_display_map = {
        "N": "N",
        "Ø": "Ø",
        "S": "S",
        "V": "Vest",
    }
    seat_display = seat_display_map.get(seat, "?")
    display = str(call.get("display_bid") or "PAS")
    seat_call_no = int(call.get("seat_call_no") or 1)

    def _clean_line(line: object) -> str:
        txt = str(line)
        # Remove technical hand-tag prefixes like "4H " from log payload.
        return re.sub(r"^\s*\d+H\s+", "", txt)

    prefix = f"{seat_display}, {seat_call_no}. melding: {display}: "
    return [prefix + _clean_line(line) for line in list(call.get("log_lines") or [])]


def _is_pass_bid(bid: object) -> bool:
    return str(bid or "").strip().upper() in ("PASS", "PAS")


def suggest_first_round_for_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Suggest auction calls until 3 consecutive passes or 5 rounds (20 calls)."""
    first = suggest_opening_for_row(row)
    first_seat = _normalize_seat(first.get("dealer"))

    if first_seat is None:
        order = ["N", "Ø", "S", "V"]
        first["dealer"] = order[0]
    else:
        order = [first_seat]
        while len(order) < 4:
            nxt = _next_seat(order[-1])
            if nxt is None:
                break
            order.append(nxt)
        if len(order) < 4:
            order = ["N", "Ø", "S", "V"]

    first_actor = _normalize_seat(first.get("dealer")) or order[0]
    first = _apply_state_ceiling_to_call(row, [], first_actor, first, "1H")

    call_sequence: list[dict[str, Any]] = [first]
    max_calls = 20

    for call_no in range(2, max_calls + 1):
        # Stop condition: three consecutive passes AFTER a real bid (normal end of auction),
        # OR four consecutive passes with no real bid at all (passed-out deal).
        # The "3 passes" rule only kicks in once at least one contract bid has been made;
        # in the first round every hand must get a chance to open before the deal is abandoned.
        if len(call_sequence) >= 3 and all(_is_pass_bid(c.get("bid")) for c in call_sequence[-3:]):
            has_real_bid = any(
                _parse_contract_bid(str(c.get("bid") or "PASS").upper()) is not None
                for c in call_sequence
            )
            if has_real_bid or len(call_sequence) >= 4:
                break

        seat = order[(call_no - 1) % 4]
        hand_tag = f"{call_no}H"

        partner_seat = _partner_of(seat)
        partner_contract = None
        partner_last_call = None
        own_contracts: list[str] = []
        opp_contracts: list[str] = []

        for prev in call_sequence:
            prev_seat = _normalize_seat(prev.get("dealer"))
            prev_bid = str(prev.get("bid") or "PASS").upper()
            if prev_seat is None or _parse_contract_bid(prev_bid) is None:
                if prev_seat == partner_seat:
                    partner_last_call = prev
                continue
            if prev_seat == partner_seat:
                partner_last_call = prev
                partner_contract = prev_bid
            if _seat_side(prev_seat) == _seat_side(seat):
                own_contracts.append(prev_bid)
            else:
                opp_contracts.append(prev_bid)

        highest_contract = _highest_contract_bid_text(*(own_contracts + opp_contracts))

        if highest_contract is None:
            call = _opening_from_specific_seat(
                row,
                seat,
                f"{hand_tag} situation: ingen kontrakt endnu -> åbningssituation.",
            )
            call = _apply_state_ceiling_to_call(row, call_sequence, seat, call, hand_tag)
            call_sequence.append(call)
            continue

        if partner_contract is not None:
            opp_highest = _highest_contract_bid_text(*opp_contracts)
            reserved = []
            for b in opp_contracts:
                p = _parse_contract_bid(b)
                if p is not None:
                    reserved.append(p[1])
            call = _suggest_third_hand_after_partner_open(
                row,
                seat,
                partner_contract,
                opp_highest,
                hand_tag=hand_tag,
                reserved_cuebid_strains=reserved,
                prior_calls=call_sequence,
            )
            call = _legalize_competitive_contract(call, highest_contract, hand_tag, prior_calls=call_sequence)
            call = _apply_state_ceiling_to_call(row, call_sequence, seat, call, hand_tag)
            call_sequence.append(call)
            continue

        partner_last_bid = str((partner_last_call or {}).get("bid") or "PASS").upper()
        partner_last_rule = str((partner_last_call or {}).get("rule_id") or "")
        if (
            partner_contract is None
            and partner_last_bid in ("X", "DBL", "DOUBLE")
            and "takeout_double" in partner_last_rule
        ):
            call = _suggest_response_after_partner_takeout_double(
                row,
                seat,
                highest_contract,
                hand_tag=hand_tag,
                prior_calls=call_sequence,
            )
            call = _legalize_competitive_contract(call, highest_contract, hand_tag, prior_calls=call_sequence)
            call = _apply_state_ceiling_to_call(row, call_sequence, seat, call, hand_tag)
            call_sequence.append(call)
            continue

        call = _suggest_second_hand_competitive(
            row,
            seat,
            highest_contract,
            hand_tag=hand_tag,
            prior_calls=call_sequence,
        )
        call = _legalize_competitive_contract(call, highest_contract, hand_tag, prior_calls=call_sequence)
        call = _apply_state_ceiling_to_call(row, call_sequence, seat, call, hand_tag)
        call_sequence.append(call)

    # Attach per-seat call number to each call for requested log format.
    seat_counter: dict[str, int] = {"N": 0, "Ø": 0, "S": 0, "V": 0}
    for call in call_sequence:
        seat = _normalize_seat(call.get("dealer"))
        if seat is None:
            call["seat_call_no"] = 1
            continue
        seat_counter[seat] = seat_counter.get(seat, 0) + 1
        call["seat_call_no"] = seat_counter[seat]

    combined_log: list[str] = []
    for c in call_sequence:
        combined_log.extend(_prefixed_call_log_lines(c))

    result: dict[str, Any] = {
        "call_sequence": call_sequence,
        "log_lines": combined_log,
    }

    # Backward-compatible named keys for earlier calls.
    key_names = [
        "first_call",
        "second_call",
        "third_call",
        "fourth_call",
        "fifth_call",
        "sixth_call",
        "seventh_call",
        "eighth_call",
    ]
    for i, key in enumerate(key_names):
        result[key] = call_sequence[i] if i < len(call_sequence) else None

    return result
