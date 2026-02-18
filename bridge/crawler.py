import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
import re

BASE = "https://resultater.bridge.dk/template/"
OVERVIEW = BASE + "overview_club.php?mainclubno=2183&clubno=2"

def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

def get_soup(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    return BeautifulSoup(r.text, "lxml")

def parse_date_from_title(title):
    t = clean(title)
    m = re.search(r"(\d{1,2})[.\-]?(\d{1,2})[.\-]?(\d{2})", t)
    if not m:
        return None
    day = int(m.group(1))
    month = int(m.group(2))
    year = int(m.group(3)) + 2000
    try:
        return datetime(year, month, day)
    except:
        return None

def get_recent_tournaments(cutoff_date):

    soup = get_soup(OVERVIEW)

    tournament_pages = [
        urljoin(BASE, a["href"])
        for a in soup.find_all("a", href=True)
        if "turnering.php?" in a["href"]
    ]

    resultater = {}

    for turl in tournament_pages:
        tsoup = get_soup(turl)
        h1 = tsoup.find("h1")
        if not h1:
            continue

        date = parse_date_from_title(h1.get_text())
        if not date or date < cutoff_date:
            continue

        for a in tsoup.find_all("a", href=True):
            if "resultater.php?filename=2183/" in a["href"]:
                res_url = urljoin(BASE, a["href"])
                resultater[res_url] = date

    return resultater
