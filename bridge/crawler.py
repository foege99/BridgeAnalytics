import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
import re

BASE = "https://resultater.bridge.dk/template/"
DEFAULT_MAINCLUBNO = 2183
DEFAULT_CLUBNO = 2
OVERVIEW_OLD_STREAK_FOR_EARLY_STOP = 3

DANISH_MONTHS = {
    "januar": 1,
    "februar": 2,
    "marts": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}


def build_overview_url(mainclubno: int = DEFAULT_MAINCLUBNO, clubno: int = DEFAULT_CLUBNO) -> str:
    """Build overview URL for a specific main-club/club stream."""
    return BASE + f"overview_club.php?mainclubno={int(mainclubno)}&clubno={int(clubno)}"

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
    """
    Parse dato fra turnerings-titel.
    
    Håndler flere formater:
    - DD.MM.YY (fx 03.03.26 → 2026)
    - DD.MM.YYYY (fx 03.03.2026 → 2026)
    - DD-MM-YY
    - DD-MM-YYYY
    osv.
    """
    t = clean(title)

    def _safe_date(day: int, month: int, year: int):
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    # 1) Separeret format: DD.MM.YY(YY), DD-MM-YY(YY), DD/MM/YY(YY)
    # Separator er bevidst påkrævet her for at undgå fejlmatch som:
    # 240226 -> 2|4|0226 (ulovligt år)
    m = re.search(r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2}|\d{4})(?!\d)", t)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year_raw = m.group(3)
        year = int(year_raw) if len(year_raw) == 4 else int(year_raw) + 2000
        parsed = _safe_date(day, month, year)
        if parsed is not None:
            return parsed

    # 2) Kompakt format: DDMMYYYY (fx 03032026)
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{4})(?!\d)", t)
    if m:
        parsed = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if parsed is not None:
            return parsed

    # 3) Kompakt format: DDMMYY (fx 240226, Aften140323)
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", t)
    if m:
        parsed = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)) + 2000)
        if parsed is not None:
            return parsed
    
    return None


def parse_date_from_overview_text(text):
    """
    Parse dato fra overview-linktekst.

    Eksempel:
    "Tirsdag d. 10. marts 2026 kl. 18:30"
    """
    t = clean(text).lower()
    m = re.search(r"(\d{1,2})\.\s*([a-zæøå]+)\s+(\d{4})", t)
    if not m:
        return None

    day = int(m.group(1))
    month_name = m.group(2)
    year = int(m.group(3))
    month = DANISH_MONTHS.get(month_name)
    if month is None:
        return None

    try:
        return datetime(year, month, day)
    except ValueError:
        return None
    
def extract_gt_number(filename):
    """
    Extrahér GT-nummeret fra filnavn.
    Eksempel: MT669GT1543.XML → 1543
    """
    m = re.search(r'GT(\d+)', filename)
    if m:
        return int(m.group(1))
    return None

def extract_tournament_id(filename):
    """
    Extrahér turnerings-ID fra filnavn.
    Eksempel: MT669GT1543.XML → 669
    """
    m = re.search(r'MT(\d+)GT', filename)
    if m:
        return int(m.group(1))
    return None

def get_section_name(section_number):
    """
    Konverter section-nummer til bogstav (1 -> A, 2 -> B osv.)
    """
    if section_number < 1:
        return None
    return chr(64 + section_number)  # chr(65) = 'A'

def build_spilresultater_url(section_url):
    """
    Konverter resultater.php URL til spilresultater.php med round/half parametre.
    
    For parturneringer på en aften: round=1&half=1
    (Multi-day turneringer skal håndtere flere rounds/halves senere)
    """
    url = section_url.replace('resultater.php', 'spilresultater.php')
    if 'round=' not in url:
        url += '&round=1&half=1'
    return url

def get_recent_tournaments(cutoff_date, mainclubno: int = DEFAULT_MAINCLUBNO, clubno: int = DEFAULT_CLUBNO):
    """
    Hent turneringer fra overview-siden.

    For hver turnering, find ALLE sections (A, B, C...)

    ✅ EARLY STOP: Stopper når vi når turneringer ældre end cutoff_date

    Returns:
    --------
    list of dict:
        [
            {
                'tournament_id': 669,
                'date': datetime(...),
                'sections': [...]
            },
            ...
        ]
    """

    # ✅ Konverter cutoff_date til date hvis det er datetime
    if isinstance(cutoff_date, datetime):
        cutoff_date = cutoff_date.date()

    overview_url = build_overview_url(mainclubno=mainclubno, clubno=clubno)
    soup = get_soup(overview_url)

    tournament_entries = [
        {
            "url": urljoin(BASE, a["href"]),
            "overview_date": parse_date_from_overview_text(a.get_text(" ", strip=True)),
        }
        for a in soup.find_all("a", href=True)
        if "turnering.php?" in a["href"]
    ]

    # ✅ STEP 1: Brug overview-dato til at undgå parsing af gamle turneringer
    tournaments = {}  # Key: tournament_id, Value: {'date': ..., 'urls': []}
    old_streak = 0
    reached_cutoff_during_discovery = False

    for entry in tournament_entries:
        turl = entry["url"]
        overview_date = entry["overview_date"]

        if overview_date is not None:
            if overview_date.date() < cutoff_date:
                old_streak += 1
                if old_streak >= OVERVIEW_OLD_STREAK_FOR_EARLY_STOP:
                    print(
                        f"✅ Early stop fra overview: {old_streak} gamle turneringer i træk "
                        f"(< {cutoff_date})"
                    )
                    reached_cutoff_during_discovery = True
                    break
                continue

            # Vi har fundet en turnering i range, så old streak nulstilles.
            old_streak = 0

        print(f"  Parsing: {turl}")
        try:
            tsoup = get_soup(turl)
            h1 = tsoup.find("h1")
            if not h1 and overview_date is None:
                continue

            date = parse_date_from_title(h1.get_text()) if h1 else None
            if date is None:
                date = overview_date
            if not date:
                continue

            print(f"    → {date.date()}")

            if date.date() < cutoff_date:
                old_streak += 1
                if old_streak >= OVERVIEW_OLD_STREAK_FOR_EARLY_STOP:
                    print(f"✅ Early stop: Nåede cutoff-dato ({cutoff_date})")
                    reached_cutoff_during_discovery = True
                    break
                continue

            old_streak = 0

            # Find alle XML-links på turnerings-siden
            for a in tsoup.find_all("a", href=True):
                if f"resultater.php?filename={int(mainclubno)}/" in a["href"]:
                    res_url = urljoin(BASE, a["href"])

                    # Extrahér filnavn
                    m = re.search(rf'filename={int(mainclubno)}/([^&]+)', res_url)
                    if not m:
                        continue

                    filename = m.group(1)
                    tournament_id = extract_tournament_id(filename)
                    gt_number = extract_gt_number(filename)

                    if not tournament_id or not gt_number:
                        continue

                    # Initialiser turnering hvis ikke eksisterer
                    if tournament_id not in tournaments:
                        tournaments[tournament_id] = {
                            'date': date,
                            'urls': []
                        }

                    tournaments[tournament_id]['urls'].append({
                        'filename': filename,
                        'gt_number': gt_number,
                        'url': res_url
                    })
        except Exception as e:
            print(f"    ⚠️ Fejl parsing turnering: {e}")
            continue

    # ✅ STEP 2: Sorter efter dato (NYESTE FØRST)
    sorted_tournament_ids = sorted(
        tournaments.keys(),
        key=lambda tid: tournaments[tid]['date'],
        reverse=True  # Nyeste først
    )

    # ✅ STEP 3: Filtrer efter cutoff (nu kan vi bruge early stop sikkert)
    result = []
    reached_cutoff = reached_cutoff_during_discovery

    for tournament_id in sorted_tournament_ids:
        tdata = tournaments[tournament_id]
        date = tdata['date']

        # ✅ Check cutoff: hvis for gammel, stop
        if date.date() < cutoff_date:
            print(f"✅ Early stop: Nåede cutoff-dato ({cutoff_date})")
            reached_cutoff = True
            break

        # Sort URLs efter GT-nummer (A=1543, B=1544, C=1545...)
        urls_sorted = sorted(tdata['urls'], key=lambda x: x['gt_number'])

        # Assign section names (A, B, C...)
        sections = []
        for section_num, url_data in enumerate(urls_sorted, start=1):
            section_name = get_section_name(section_num)
            resultater_url = url_data['url']
            spilresultater_url = build_spilresultater_url(resultater_url)

            sections.append({
                'name': section_name,
                'filename': url_data['filename'],
                'gt_number': url_data['gt_number'],
                'url': resultater_url,
                'spilresultater_url': spilresultater_url
            })

        result.append({
            'tournament_id': tournament_id,
            'date': date,
            'sections': sections,
            'clubno': int(clubno),
            'mainclubno': int(mainclubno),
        })

    if not reached_cutoff and tournaments:
        print(f"✅ Processerede alle turneringer til {cutoff_date}")

    return result