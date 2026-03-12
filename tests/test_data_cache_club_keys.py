from datetime import date, datetime

from bridge.data_cache import DataCache


def _sample_sections() -> list[dict]:
    return [{"name": "A"}]


def _sample_data(marker: str) -> dict:
    return {
        "sections": {
            "A": [{"marker": marker, "board_no": 1}],
        }
    }


def test_cache_uses_club_aware_keys_and_files(tmp_path):
    cache = DataCache(data_dir=str(tmp_path / "data"))

    tournament_date = datetime(2026, 3, 11)

    cache.save_tournament_data(
        tournament_id=999,
        tournament_date=tournament_date,
        sections=_sample_sections(),
        data=_sample_data("club1"),
        clubno=1,
        mainclubno=2183,
    )
    cache.save_tournament_data(
        tournament_id=999,
        tournament_date=tournament_date,
        sections=_sample_sections(),
        data=_sample_data("club2"),
        clubno=2,
        mainclubno=2183,
    )

    assert "1:999" in cache.manifest["tournaments"]
    assert "2:999" in cache.manifest["tournaments"]

    tournaments_dir = tmp_path / "data" / "tournaments"
    assert (tournaments_dir / "tournament_1_999.json").exists()
    assert (tournaments_dir / "tournament_2_999.json").exists()

    c1 = cache.get_cached_tournament(999, clubno=1)
    c2 = cache.get_cached_tournament(999, clubno=2)
    c_missing = cache.get_cached_tournament(999, clubno=3)

    assert c1 is not None
    assert c2 is not None
    assert c_missing is None
    assert c1["sections"]["A"][0]["marker"] == "club1"
    assert c2["sections"]["A"][0]["marker"] == "club2"


def test_legacy_cache_lookup_still_works_when_club_requested(tmp_path):
    cache = DataCache(data_dir=str(tmp_path / "data"))

    tournament_date = datetime(2026, 3, 4)

    cache.save_tournament_data(
        tournament_id=888,
        tournament_date=tournament_date,
        sections=_sample_sections(),
        data=_sample_data("legacy"),
    )

    loaded = cache.get_cached_tournament(888, clubno=2)
    assert loaded is not None
    assert loaded["sections"]["A"][0]["marker"] == "legacy"

    entries = cache.get_cached_tournaments_in_range(date(2026, 3, 1), date(2026, 3, 20))
    assert any(e["tournament_id"] == 888 for e in entries)
