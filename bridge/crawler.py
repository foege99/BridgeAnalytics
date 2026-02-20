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

def get_recent_tournaments(cutoff_date):
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
                'sections': [
                    {
                        'name': 'A', 
                        'filename': 'MT669GT1543.XML', 
                        'gt_number': 1543, 
                        'url': '...resultater.php...',
                        'spilresultater_url': '...spilresultater.php...&round=1&half=1'
                    },
                    ...
                ]
            },
            ...
        ]
    """
    
    soup = get_soup(OVERVIEW)

    tournament_pages = [
        urljoin(BASE, a["href"])
        for a in soup.find_all("a", href=True)
        if "turnering.php?" in a["href"]
    ]

    tournaments = {}  # Key: tournament_id, Value: {'date': ..., 'urls': []}
    reached_cutoff = False  # ✅ Flag for early stopping

    for turl in tournament_pages:
        print(f"  Parsing: {turl}")
        tsoup = get_soup(turl)
        h1 = tsoup.find("h1")
        if not h1:
            continue

        date = parse_date_from_title(h1.get_text())
        
        # ✅ CUTOFF-CHECK: Hvis for gammel, mark og stop loop
        if not date or date < cutoff_date:
            print(f"    → Skipped (older than {cutoff_date.date()})")
            reached_cutoff = True
            break  # ✅ STOP HER – ingen grund til at parse mere
        
        print(f"    → {date.date()}")

        # Find alle XML-links på turnerings-siden
        for a in tsoup.find_all("a", href=True):
            if "resultater.php?filename=2183/" in a["href"]:
                res_url = urljoin(BASE, a["href"])
                
                # Extrahér filnavn
                m = re.search(r'filename=2183/([^&]+)', res_url)
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
    
    # Konverter til liste med sections sorted efter GT-nummer
    result = []
    for tournament_id in sorted(tournaments.keys(), reverse=True):
        tdata = tournaments[tournament_id]
        date = tdata['date']
        
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
            'sections': sections
        })
    
    if reached_cutoff:
        print(f"✅ Early stop: Nåede cutoff-dato ({cutoff_date.date()})")
    
    return result


# Backwards compatibility: hvis gammel kode kalder get_recent_tournaments
# og forventer dict med {url: date}
def get_recent_tournaments_legacy(cutoff_date):
    """
    LEGACY funktion: returner gamle format {url: date}
    """
    tournaments = get_recent_tournaments(cutoff_date)
    result = {}
    for t in tournaments:
        for section in t['sections']:
            result[section['url']] = t['date']
    return result