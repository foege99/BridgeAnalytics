from bridge.crawler import parse_date_from_title


def _iso_date(title: str) -> str:
    dt = parse_date_from_title(title)
    assert dt is not None
    return dt.date().isoformat()


def test_parse_date_from_title_compact_ddmmyy_variants():
    # Regression: previously parsed as illegal year like 0226-04-02.
    assert _iso_date("240226aften") == "2026-02-24"
    assert _iso_date("Aften140323") == "2023-03-14"


def test_parse_date_from_title_compact_ddmmyyyy():
    assert _iso_date("03032026") == "2026-03-03"
    assert _iso_date("21102025") == "2025-10-21"


def test_parse_date_from_title_separated_formats():
    assert _iso_date("20.01.26 Aften") == "2026-01-20"
    assert _iso_date("2.12.25aften") == "2025-12-02"
    assert _iso_date("03-03-2026") == "2026-03-03"


def test_parse_date_from_title_rejects_invalid_dates():
    assert parse_date_from_title("32139999") is None
    assert parse_date_from_title("99.99.99") is None
