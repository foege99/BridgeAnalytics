"""
Tests for parse_dealer_vul(), parse_dd_table(), and parse_par() in bridge/scraper.py.
"""

from bs4 import BeautifulSoup
import pytest

from bridge.scraper import parse_dealer_vul, parse_dd_table, parse_par


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

def _game_div(inner_html: str) -> BeautifulSoup:
    html = f'<div class="game"><div class="boardNo">8</div>{inner_html}</div>'
    return BeautifulSoup(html, "lxml").select_one("div.game")


def _dealer_vul_html(dealer: str, vul: str) -> str:
    return f'<span class="dealer">{dealer}</span>/<span class="vulnerability">{vul}</span>'


def _dd_grid_html(rows) -> str:
    """Build a uk-grid DD table.

    rows: list of 5 lists, first is header, then 4 direction rows.
    Each list has 7 items.
    """
    cells = ""
    for row in rows:
        for cell in row:
            cells += f'<div class="uk-width-1-7">{cell}</div>\n'
    return f'<div class="uk-grid" style="text-align:right">\n{cells}</div>'


HEADER_ROW = ["", "NT", "♠", "♥", "♦", "♣", "HP"]
N_ROW  = ["N", "7", "8", "7", "7", "6", "16"]
S_ROW  = ["S", "6", "5", "6", "6", "7", "16"]
O_ROW  = ["Ø", "5", "5", "5", "5", "5", "7"]
V_ROW  = ["V", "7", "7", "7", "8", "6", "17"]

FULL_DD_HTML = _dd_grid_html([HEADER_ROW, N_ROW, S_ROW, O_ROW, V_ROW])
PAR_HTML = "<div>Datum: -308 / Par: -980 6♠ ØV</div>"


# ===========================================================================
# A) dealer / vul parsing
# ===========================================================================

class TestDealerVul:
    def test_vest_maps_to_v(self):
        game = _game_div(_dealer_vul_html("Vest", "-"))
        result = parse_dealer_vul(game)
        assert result["dealer"] == "V"

    def test_nord_maps_to_n(self):
        game = _game_div(_dealer_vul_html("Nord", "NS"))
        result = parse_dealer_vul(game)
        assert result["dealer"] == "N"

    def test_syd_maps_to_s(self):
        game = _game_div(_dealer_vul_html("Syd", "ØV"))
        result = parse_dealer_vul(game)
        assert result["dealer"] == "S"

    def test_oest_maps_to_o(self):
        game = _game_div(_dealer_vul_html("Øst", "Alle"))
        result = parse_dealer_vul(game)
        assert result["dealer"] == "Ø"

    def test_vul_ingen(self):
        game = _game_div(_dealer_vul_html("Nord", "-"))
        assert parse_dealer_vul(game)["vul"] == "-"

    def test_vul_ns(self):
        game = _game_div(_dealer_vul_html("Syd", "NS"))
        assert parse_dealer_vul(game)["vul"] == "NS"

    def test_vul_ov(self):
        game = _game_div(_dealer_vul_html("Øst", "ØV"))
        assert parse_dealer_vul(game)["vul"] == "ØV"

    def test_vul_alle(self):
        game = _game_div(_dealer_vul_html("Vest", "Alle"))
        assert parse_dealer_vul(game)["vul"] == "Alle"

    def test_missing_dealer_returns_none(self):
        game = _game_div('<span class="vulnerability">NS</span>')
        assert parse_dealer_vul(game)["dealer"] is None

    def test_missing_vul_returns_none(self):
        game = _game_div('<span class="dealer">Nord</span>')
        assert parse_dealer_vul(game)["vul"] is None


# ===========================================================================
# B) DD table parsing
# ===========================================================================

class TestDDTable:
    def test_dd_valid_true_when_grid_present(self):
        game = _game_div(FULL_DD_HTML)
        result = parse_dd_table(game)
        assert result["dd_valid"] is True

    def test_dd_valid_false_when_grid_absent(self):
        game = _game_div("<div>No DD here</div>")
        result = parse_dd_table(game)
        assert result["dd_valid"] is False

    def test_dd_n_nt(self):
        game = _game_div(FULL_DD_HTML)
        assert parse_dd_table(game)["dd_N_NT"] == 7

    def test_dd_n_spades(self):
        game = _game_div(FULL_DD_HTML)
        assert parse_dd_table(game)["dd_N_S"] == 8

    def test_dd_n_hcp(self):
        game = _game_div(FULL_DD_HTML)
        assert parse_dd_table(game)["dd_N_HCP"] == 16

    def test_dd_s_row(self):
        game = _game_div(FULL_DD_HTML)
        result = parse_dd_table(game)
        assert result["dd_S_NT"] == 6
        assert result["dd_S_S"] == 5
        assert result["dd_S_H"] == 6
        assert result["dd_S_D"] == 6
        assert result["dd_S_C"] == 7
        assert result["dd_S_HCP"] == 16

    def test_dd_o_direction(self):
        """Ø (East) direction is parsed correctly."""
        game = _game_div(FULL_DD_HTML)
        result = parse_dd_table(game)
        assert result["dd_Ø_NT"] == 5
        assert result["dd_Ø_S"] == 5
        assert result["dd_Ø_HCP"] == 7

    def test_dd_v_row(self):
        game = _game_div(FULL_DD_HTML)
        result = parse_dd_table(game)
        assert result["dd_V_NT"] == 7
        assert result["dd_V_D"] == 8
        assert result["dd_V_HCP"] == 17

    def test_all_dd_fields_present(self):
        game = _game_div(FULL_DD_HTML)
        result = parse_dd_table(game)
        for d in ["N", "S", "Ø", "V"]:
            for s in ["NT", "S", "H", "D", "C"]:
                assert f"dd_{d}_{s}" in result
            assert f"dd_{d}_HCP" in result

    def test_dd_grid_without_hp_not_matched(self):
        """A uk-grid without HP cell should not be treated as a DD grid."""
        no_hp_grid = (
            '<div class="uk-grid">'
            '<div>NT</div><div>1</div><div>2</div>'
            '</div>'
        )
        game = _game_div(no_hp_grid)
        assert parse_dd_table(game)["dd_valid"] is False


# ===========================================================================
# C) Par parsing
# ===========================================================================

class TestPar:
    def test_par_score(self):
        game = _game_div(PAR_HTML)
        assert parse_par(game)["par_score"] == -980

    def test_par_contract(self):
        game = _game_div(PAR_HTML)
        assert parse_par(game)["par_contract"] == "6♠"

    def test_par_side(self):
        game = _game_div(PAR_HTML)
        assert parse_par(game)["par_side"] == "ØV"

    def test_par_positive_score(self):
        game = _game_div("<div>Par: 430 4♥ NS</div>")
        result = parse_par(game)
        assert result["par_score"] == 430
        assert result["par_contract"] == "4♥"
        assert result["par_side"] == "NS"

    def test_par_nt_contract(self):
        game = _game_div("<div>Par: -100 3NT NS</div>")
        result = parse_par(game)
        assert result["par_score"] == -100
        assert result["par_contract"] == "3NT"

    def test_par_missing_returns_none(self):
        game = _game_div("<div>Ingen par her</div>")
        result = parse_par(game)
        assert result["par_score"] is None
        assert result["par_contract"] is None
        assert result["par_side"] is None

    def test_par_combined_with_datum(self):
        """Par line embedded with Datum prefix is still found."""
        game = _game_div("<div>Datum: -308 / Par: -980 6♠ ØV</div>")
        result = parse_par(game)
        assert result["par_score"] == -980
        assert result["par_contract"] == "6♠"


# ===========================================================================
# D) Full board snippet integrating all three parsers
# ===========================================================================

class TestFullBoardSnippet:
    def _board_game_div(self):
        inner = (
            _dealer_vul_html("Vest", "-")
            + FULL_DD_HTML
            + PAR_HTML
        )
        return _game_div(inner)

    def test_dealer_parsed(self):
        game = self._board_game_div()
        assert parse_dealer_vul(game)["dealer"] == "V"

    def test_vul_parsed(self):
        game = self._board_game_div()
        assert parse_dealer_vul(game)["vul"] == "-"

    def test_dd_and_par_coexist(self):
        game = self._board_game_div()
        dd = parse_dd_table(game)
        par = parse_par(game)
        assert dd["dd_valid"] is True
        assert par["par_score"] == -980
