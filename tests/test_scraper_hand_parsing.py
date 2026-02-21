"""
Tests for parse_hands_from_game_div() in bridge/scraper.py.

Validates the regex-based hand parsing that replaces the old div.hand.N CSS
selector approach, which did not match the actual spilresultater.bridge.dk HTML.
"""

from bs4 import BeautifulSoup
import pytest

from bridge.scraper import parse_hands_from_game_div


def make_game_div(hand_htmls: list) -> BeautifulSoup:
    """Build a BeautifulSoup game div containing one hand-div per item."""
    inner = "\n".join(f'<div class="hand-block">{h}</div>' for h in hand_htmls)
    html = f'<div class="game"><div class="boardNo">1</div>{inner}</div>'
    return BeautifulSoup(html, "lxml").select_one("div.game")


# --- Four hands in separate divs (typical sidebar layout) ---

HAND_N_HTML = "♠ 64 ♥ ET9752 ♦ K3 ♣ K72"
HAND_V_HTML = "♠ KD83 ♥ D6 ♦ ET96 ♣ E96"
HAND_O_HTML = "♠ ET7 ♥ K4 ♦ D854 ♣ DT53"
HAND_S_HTML = "♠ E952 ♥ E83 ♦ E72 ♣ E84"


def test_four_hands_parsed_and_mapped_to_positions():
    game_div = make_game_div([HAND_N_HTML, HAND_V_HTML, HAND_O_HTML, HAND_S_HTML])
    result = parse_hands_from_game_div(game_div)

    assert set(result.keys()) == {"N_hand", "V_hand", "Ø_hand", "S_hand"}


def test_n_hand_danish_notation_translated_correctly():
    """E→A, K→K, D→Q, B→J, T→T (ten) in Danish notation."""
    game_div = make_game_div([HAND_N_HTML, HAND_V_HTML, HAND_O_HTML, HAND_S_HTML])
    result = parse_hands_from_game_div(game_div)

    # ♠64 ♥ET9752 ♦K3 ♣K72 → E(A) T(T) → "64.AT9752.K3.K72"
    assert result["N_hand"] == "64.AT9752.K3.K72"


def test_v_hand_translated_correctly():
    game_div = make_game_div([HAND_N_HTML, HAND_V_HTML, HAND_O_HTML, HAND_S_HTML])
    result = parse_hands_from_game_div(game_div)

    # ♠KD83 ♥D6 ♦ET96 ♣E96 → D(Q) E(A) → "KQ83.Q6.AT96.A96"
    assert result["V_hand"] == "KQ83.Q6.AT96.A96"


def test_o_hand_mapped_to_o_position():
    game_div = make_game_div([HAND_N_HTML, HAND_V_HTML, HAND_O_HTML, HAND_S_HTML])
    result = parse_hands_from_game_div(game_div)

    # ♠ET7 ♥K4 ♦D854 ♣DT53 → E(A)T7, K4, Q854, QT53
    assert result["Ø_hand"] == "AT7.K4.Q854.QT53"


def test_s_hand_mapped_to_s_position():
    game_div = make_game_div([HAND_N_HTML, HAND_V_HTML, HAND_O_HTML, HAND_S_HTML])
    result = parse_hands_from_game_div(game_div)

    # ♠E952 ♥E83 ♦E72 ♣E84 → A952.A83.A72.A84
    assert result["S_hand"] == "A952.A83.A72.A84"


def test_no_hand_divs_returns_empty():
    html = '<div class="game"><div class="boardNo">1</div></div>'
    game_div = BeautifulSoup(html, "lxml").select_one("div.game")
    result = parse_hands_from_game_div(game_div)
    assert result == {}


def test_fewer_than_four_hands_parsed_partially():
    """Only 2 hands present → only N and V are populated."""
    game_div = make_game_div([HAND_N_HTML, HAND_V_HTML])
    result = parse_hands_from_game_div(game_div)

    assert "N_hand" in result
    assert "V_hand" in result
    assert "Ø_hand" not in result
    assert "S_hand" not in result


def test_void_suit_represented_as_dash():
    """A void suit shown as '-' should result in empty string for that suit."""
    hand_with_void = "♠ EKDB ♥ ET9752 ♦ - ♣ K72"
    game_div = make_game_div([hand_with_void, HAND_V_HTML, HAND_O_HTML, HAND_S_HTML])
    result = parse_hands_from_game_div(game_div)

    # ♦ "-" → normalize_ranks("-") returns "-" → hand_eval treats it as void
    n_hand = result.get("N_hand", "")
    parts = n_hand.split(".")
    assert len(parts) == 4
    # Diamonds part should contain only the dash (passed through as-is before hand_eval strips it)
    assert parts[2] == "-"


def test_no_double_counting_when_parent_contains_all_hands():
    """
    If a parent element contains all 4 hands (16 suit symbols total),
    it should not be counted as a hand – only the individual hand elements should.
    """
    game_div = make_game_div([HAND_N_HTML, HAND_V_HTML, HAND_O_HTML, HAND_S_HTML])
    result = parse_hands_from_game_div(game_div)

    # Should be exactly 4 hands, not more
    assert len(result) == 4
