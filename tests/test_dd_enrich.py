"""Tests for bridge.dd_enrich — DataFrame enrichment with lead quality metrics.

Uses a small synthetic DataFrame built from the known board in test_dd_compute.
"""
import pandas as pd
import pytest


# Board: same deal, contract 4\u2665 by North, leader = East (Ø), lead = \u25034.
# East holds KJ54.K.QJ942.A64 \u2192 has \u25034 \u2192 lead is valid.
# Best defence leads a club (dd_N_H=4 declarer tricks).  \u25034 costs 1 trick (5 vs 4).
_ROW = {
    "N_hand": "7.AT86.876.KQ972",
    "\u00d8_hand": "KJ54.K.QJ942.A64",
    "S_hand": "A962.932.KT5.853",
    "V_hand": "QT83.QJ754.A3.JT",
    "strain": "\u2665",          # \u2665 (hearts)
    "decl": "N",               # North
    "lead": "\u2663 4",         # \u25034 (in East's hand)
    "vul": "-",
    "dealer": "N",
    "dd_valid": True,
    # scraped DD values (same deal, all 20 columns)
    "dd_N_NT": 5, "dd_N_S": 2, "dd_N_H": 4, "dd_N_D": 4, "dd_N_C": 7,
    "dd_S_NT": 5, "dd_S_S": 3, "dd_S_H": 4, "dd_S_D": 4, "dd_S_C": 7,
    "dd_\u00d8_NT": 7, "dd_\u00d8_S": 10, "dd_\u00d8_H": 8, "dd_\u00d8_D": 7, "dd_\u00d8_C": 6,
    "dd_V_NT": 7, "dd_V_S": 10, "dd_V_H": 8, "dd_V_D": 7, "dd_V_C": 6,
    "par_score": -420,
    "par_contract": "4\u2660",
    "par_side": "\u00d8V",
}


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Redirect cache DB for test isolation."""
    import bridge.dd_cache as cache_module

    monkeypatch.setattr(cache_module, "_DB_PATH", tmp_path / "enrich_test.db")
    yield


class TestEnrichLeadTables:
    def _df(self, rows=None):
        return pd.DataFrame([rows or _ROW])

    def test_adds_new_columns(self):
        from bridge.dd_enrich import enrich_lead_tables

        result = enrich_lead_tables(self._df())
        for col in ["lead_dd_tricks", "dd_best_lead", "dd_best_lead_tricks", "lead_cost"]:
            assert col in result.columns, f"Column {col!r} missing"

    def test_lead_cost_nonneg(self):
        from bridge.dd_enrich import enrich_lead_tables

        result = enrich_lead_tables(self._df())
        lc = result["lead_cost"].iloc[0]
        assert lc is not None
        assert lc >= 0, f"lead_cost should be >= 0, got {lc}"

    def test_best_lead_tricks_equals_dd_table(self):
        """dd_best_lead_tricks must match dd_N_H = 4 (North declares hearts)."""
        from bridge.dd_enrich import enrich_lead_tables

        result = enrich_lead_tables(self._df())
        # dd_N_H = 4: North in hearts gets 4 tricks with best defence (best lead from East)
        assert result["dd_best_lead_tricks"].iloc[0] == 4

    def test_actual_lead_club4_nonzero_cost(self):
        """\u25034 lead by East costs the defence: North makes 5 tricks instead of 4."""
        from bridge.dd_enrich import enrich_lead_tables

        result = enrich_lead_tables(self._df())
        assert result["lead_cost"].iloc[0] > 0

    def test_best_lead_is_valid_card_key(self):
        from bridge.dd_enrich import enrich_lead_tables

        result = enrich_lead_tables(self._df())
        best = result["dd_best_lead"].iloc[0]
        assert isinstance(best, str) and len(best) >= 2
        assert best[0] in "SHDC"

    def test_caching_second_call_consistent(self):
        """Second call must return same results (from cache)."""
        from bridge.dd_enrich import enrich_lead_tables

        df = self._df()
        r1 = enrich_lead_tables(df)
        r2 = enrich_lead_tables(df)
        assert r1["lead_cost"].iloc[0] == r2["lead_cost"].iloc[0]
        assert r1["dd_best_lead"].iloc[0] == r2["dd_best_lead"].iloc[0]

    def test_missing_hands_skipped_gracefully(self):
        from bridge.dd_enrich import enrich_lead_tables

        row_no_hands = {k: v for k, v in _ROW.items() if not k.endswith("_hand")}
        result = enrich_lead_tables(pd.DataFrame([row_no_hands]))
        assert result["lead_cost"].iloc[0] is None or pd.isna(result["lead_cost"].iloc[0])

    def test_empty_df_returns_empty(self):
        from bridge.dd_enrich import enrich_lead_tables

        result = enrich_lead_tables(pd.DataFrame())
        assert result.empty


class TestEnrichDDFallback:
    def test_fills_missing_dd_data(self):
        from bridge.dd_enrich import enrich_dd_fallback

        row_no_dd = {
            k: (False if k == "dd_valid" else (None if k.startswith("dd_") else v))
            for k, v in _ROW.items()
        }
        df = pd.DataFrame([row_no_dd])
        result = enrich_dd_fallback(df)
        assert result["dd_valid"].iloc[0] == True
        assert result["dd_N_NT"].iloc[0] == 5
