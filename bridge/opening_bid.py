"""Opening-bid suggestion engine driven by YAML system configuration.

MVP scope:
- Suggest only the dealer's first call from a fresh auction.
- Return one bid (e.g., PASS, 1NT, 1S, 1H, 1D, 1C).
- Keep YAML declarative; Python evaluates and selects.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

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


@lru_cache(maxsize=1)
def _load_bundle() -> dict[str, Any]:
    base = Path(__file__).resolve().parent
    return {
        "systemdefinition": _load_yaml_file(base / "systemdefinition.yaml"),
        "system_profiles": _load_yaml_file(base / "system_profiles.yaml"),
        "match_config": _load_yaml_file(base / "match_config.yaml"),
        "pair_registry": _load_yaml_file(base / "pair_registry.yaml"),
    }


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
    sys_lib = (bundle.get("systemdefinition", {}) or {}).get("system_library", {}) or {}
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
