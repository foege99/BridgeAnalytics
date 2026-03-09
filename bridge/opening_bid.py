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

    # --- Takeout double (basic MVP) ---
    double_ok = False
    double_reason = f"{hand_tag} oplysningsdobling: afvist."
    if first_strain in ("C", "D", "H", "S") and int(ctx["hcp"]) >= 12:
        opener_len = int(ctx["clubs"] if first_strain == "C" else ctx["diamonds"] if first_strain == "D" else ctx["hearts"] if first_strain == "H" else ctx["spades"])
        if first_strain in ("C", "D"):
            majors_ok = int(ctx["hearts"]) >= 3 and int(ctx["spades"]) >= 3
            if opener_len <= 2 and majors_ok:
                double_ok = True
                double_reason = f"{hand_tag} oplysningsdobling: OK (kort i minor + begge majorer)."
            else:
                double_reason = f"{hand_tag} oplysningsdobling: afvist (kræver kort minor + majorstøtte)."
        else:
            other_major_len = int(ctx["hearts"] if first_strain == "S" else ctx["spades"])
            if opener_len <= 2 and other_major_len >= 4:
                double_ok = True
                double_reason = f"{hand_tag} oplysningsdobling: OK (kort i åbners major + 4+ i anden major)."
            else:
                double_reason = f"{hand_tag} oplysningsdobling: afvist (kræver kort åbners major + 4+ i anden major)."
    log_lines.append(double_reason)

    # --- Natural overcall (basic MVP) ---
    suit_lens = {
        "S": int(ctx["spades"]),
        "H": int(ctx["hearts"]),
        "D": int(ctx["diamonds"]),
        "C": int(ctx["clubs"]),
    }
    candidate_suits = sorted(
        [s for s in ("S", "H", "D", "C") if s != first_strain],
        key=lambda s: (suit_lens[s], _strain_order(s)),
        reverse=True,
    )

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
            overcall_bid = cand
            overcall_rule = "natural_overcall_basic"
            overcall_line = (
                f"{hand_tag} indmelding: OK med {_to_display_bid(cand)} "
                f"(5+ farve, HCP {int(ctx['hcp'])}, højere end 1H)."
            )
            break
    else:
        overcall_line = f"{hand_tag} indmelding: afvist (HCP {int(ctx['hcp'])} < 8)."
    log_lines.append(overcall_line)

    # Priority: double with classic shape, otherwise natural overcall, else pass.
    prefer_overcall = overcall_bid is not None and (
        max(suit_lens.values()) >= 6 and int(ctx["hcp"]) >= 10
    )

    if double_ok and not prefer_overcall:
        return {
            "dealer": second_seat,
            "profile": None,
            "bid": "X",
            "display_bid": "X",
            "rule_id": "takeout_double_basic",
            "explanation": "2. hånd vælger oplysningsdobling.",
            "log_lines": log_lines + [
                f"{hand_tag} valg: X",
                f"{hand_tag} regel-id: takeout_double_basic",
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

    side_history = _side_contract_history(list(prior_calls or []), third_seat)
    fourth_unbid = _infer_fourth_unbid_suit_from_side_history(side_history)
    fsf_enabled = _is_fourth_suit_forcing_enabled_for_seat(third_seat)
    two_over_one_enabled = _is_two_over_one_gf_enabled_for_seat(third_seat)
    side_has_2o1_dhs = _side_has_two_over_one_dhs(side_history)

    # Reply to partner's prior fourth-suit forcing ask.
    partner_last = _latest_partner_contract_call(list(prior_calls or []), third_seat)
    partner_last_rule = str((partner_last or {}).get("rule_id") or "")
    partner_last_bid = str((partner_last or {}).get("bid") or "PASS")
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

    if fourth_unbid is not None and fsf_enabled:
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

    suit_lens = {
        "S": int(ctx["spades"]),
        "H": int(ctx["hearts"]),
        "D": int(ctx["diamonds"]),
        "C": int(ctx["clubs"]),
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
    partner_len = int(ctx["spades"] if partner_strain == "S" else ctx["hearts"] if partner_strain == "H" else ctx["diamonds"] if partner_strain == "D" else ctx["clubs"])

    if partner_len >= 3 and int(ctx["hcp"]) >= 6:
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


def _legalize_competitive_contract(call: dict[str, Any], reference_bid: str | None, hand_tag: str) -> dict[str, Any]:
    bid = str(call.get("bid") or "PASS").upper()
    if bid in ("PASS", "PAS", "X", "DBL", "DOUBLE"):
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

    if btxt in ("PASS", "PAS"):
        if state.highest_contract is None:
            evidence.hcp_range = ValueRange(0.0, 11.0)
            evidence.notes.append("Tidligt PAS giver normalt begrænset styrke.")
        else:
            evidence.hcp_range = ValueRange(0.0, 15.0)
            evidence.notes.append("PAS i konkurrence begrænser typisk offensiv styrke.")
        return evidence

    if btxt in ("X", "DBL", "DOUBLE"):
        evidence.hcp_range = ValueRange(10.0, 18.0)
        evidence.notes.append("Dobling tolkes som konkurrencestyrke i denne MVP-model.")
        return evidence

    if parsed is None:
        evidence.notes.append("Melding kunne ikke tolkes som kontrakt; ingen stramning.")
        return evidence

    level, strain = parsed

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
            hard_reject = required > (estimate.tricks_range.high + 0.01)
            soft_reject = (
                (not keep_constructive_3nt)
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
        # Stop condition: three passes in a row.
        if len(call_sequence) >= 3 and all(_is_pass_bid(c.get("bid")) for c in call_sequence[-3:]):
            break

        seat = order[(call_no - 1) % 4]
        hand_tag = f"{call_no}H"

        partner_seat = _partner_of(seat)
        partner_contract = None
        own_contracts: list[str] = []
        opp_contracts: list[str] = []

        for prev in call_sequence:
            prev_seat = _normalize_seat(prev.get("dealer"))
            prev_bid = str(prev.get("bid") or "PASS").upper()
            if prev_seat is None or _parse_contract_bid(prev_bid) is None:
                continue
            if prev_seat == partner_seat:
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
            call = _legalize_competitive_contract(call, highest_contract, hand_tag)
            call = _apply_state_ceiling_to_call(row, call_sequence, seat, call, hand_tag)
            call_sequence.append(call)
            continue

        call = _suggest_second_hand_competitive(
            row,
            seat,
            highest_contract,
            hand_tag=hand_tag,
        )
        call = _legalize_competitive_contract(call, highest_contract, hand_tag)
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
