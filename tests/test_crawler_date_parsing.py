from datetime import date

from bs4 import BeautifulSoup

from bridge import crawler
from bridge.crawler import parse_date_from_overview_text, parse_date_from_title


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


def test_parse_date_from_overview_text_danish_month_name():
    dt = parse_date_from_overview_text("Tirsdag d. 10. marts 2026 kl. 18:30")
    assert dt is not None
    assert dt.date().isoformat() == "2026-03-10"


def test_parse_date_from_overview_text_rejects_unknown_month():
    assert parse_date_from_overview_text("Tirsdag d. 10. mars 2026 kl. 18:30") is None


def test_get_recent_tournaments_skips_parsing_old_overview_entries(monkeypatch):
    overview_url = crawler.build_overview_url(mainclubno=2183, clubno=2)
    t685_url = crawler.BASE + "turnering.php?mainclubno=2183&clubno=2&tournament=685"
    t677_url = crawler.BASE + "turnering.php?mainclubno=2183&clubno=2&tournament=677"

    overview_html = """
    <html><body>
      <a href="turnering.php?mainclubno=2183&amp;clubno=2&amp;tournament=685">Tirsdag d. 10. marts 2026 kl. 18:30</a>
      <a href="turnering.php?mainclubno=2183&amp;clubno=2&amp;tournament=677">Tirsdag d. 3. marts 2026 kl. 18:30</a>
      <a href="turnering.php?mainclubno=2183&amp;clubno=2&amp;tournament=669">Tirsdag d. 17. februar 2026 kl. 18:30</a>
      <a href="turnering.php?mainclubno=2183&amp;clubno=2&amp;tournament=665">Tirsdag d. 3. februar 2026 kl. 18:30</a>
      <a href="turnering.php?mainclubno=2183&amp;clubno=2&amp;tournament=661">Tirsdag d. 27. januar 2026 kl. 18:30</a>
    </body></html>
    """

    t685_html = """
    <html><body>
      <h1>Tirsdag d. 10.03.2026 kl. 18:30</h1>
      <a href="resultater.php?filename=2183/MT685GT1543.XML">Resultat A</a>
    </body></html>
    """

    t677_html = """
    <html><body>
      <h1>Tirsdag d. 03.03.2026 kl. 18:30</h1>
      <a href="resultater.php?filename=2183/MT677GT1543.XML">Resultat A</a>
    </body></html>
    """

    parsed_urls = []

    def fake_get_soup(url):
        if url == overview_url:
            return BeautifulSoup(overview_html, "lxml")
        parsed_urls.append(url)
        if url == t685_url:
            return BeautifulSoup(t685_html, "lxml")
        if url == t677_url:
            return BeautifulSoup(t677_html, "lxml")
        raise AssertionError(f"Uventet URL parsed: {url}")

    monkeypatch.setattr(crawler, "get_soup", fake_get_soup)

    tournaments = crawler.get_recent_tournaments(
        cutoff_date=date(2026, 3, 1),
        mainclubno=2183,
        clubno=2,
    )

    assert [t["tournament_id"] for t in tournaments] == [685, 677]
    assert parsed_urls == [t685_url, t677_url]


def test_get_recent_tournaments_without_overview_date_uses_page_date(monkeypatch):
    overview_url = crawler.build_overview_url(mainclubno=2183, clubno=2)
    t700_url = crawler.BASE + "turnering.php?mainclubno=2183&clubno=2&tournament=700"

    overview_html = """
    <html><body>
      <a href="turnering.php?mainclubno=2183&amp;clubno=2&amp;tournament=700">Aften-turnering uden parsebar dato</a>
    </body></html>
    """

    t700_html = """
    <html><body>
      <h1>Tirsdag d. 10.03.2026 kl. 18:30</h1>
      <a href="resultater.php?filename=2183/MT700GT1543.XML">Resultat A</a>
    </body></html>
    """

    def fake_get_soup(url):
        if url == overview_url:
            return BeautifulSoup(overview_html, "lxml")
        if url == t700_url:
            return BeautifulSoup(t700_html, "lxml")
        raise AssertionError(f"Uventet URL parsed: {url}")

    monkeypatch.setattr(crawler, "get_soup", fake_get_soup)

    tournaments = crawler.get_recent_tournaments(
        cutoff_date=date(2026, 3, 1),
        mainclubno=2183,
        clubno=2,
    )

    assert len(tournaments) == 1
    assert tournaments[0]["tournament_id"] == 700
