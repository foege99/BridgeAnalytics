import requests
from bs4 import BeautifulSoup
import re

# ----------------------------
# Helpers / normalisering
# ----------------------------

SUIT_MAP = {
    "S": "♠", "H": "♥", "D": "♦", "C": "♣",
    "♠": "♠", "♥": "♥", "♦": "♦", "♣": "♣",
}

# DBf ranks: E=Es(A), K=K, D=Dame(Q), B=Bon(J), T=T-10
RANK_TRANSLATE = {"E": "A", "K": "K", "D": "Q", "B": "J", "T": "T"}

# Tilladte tegn i "kort-tekst" fra DBf (før oversættelse)
RANK_CHARS_DK = set("EKDBT98765432")
SUIT_CHARS = set(["♠", "♥", "♦", "♣"])

def clean(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()

def get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    return BeautifulSoup(r.text, "lxml")

def to_spilresultater_url(resultater_url: str) -> str:
    url = resultater_url.replace("resultater.php", "spilresultater.php")
    if "round=" not in url:
        url += "&round=1"
    if "half=" not in url:
        url += "&half=1"
    return url

def safe_pct(val: str):
    if not val:
        return None
    v = clean(val).replace("*", "").strip().replace(",", ".")
    try:
        return float(v)
    except:
        return None

def extract_row_from_page(soup) -> str:
    """
    Parse row letter (A/B/C) fra siden indholdet.
    
    Søger efter tekst som: "Resultater efter X sektion YYYYMMDDAFTEN, A-rækken"
    
    Returns: 'A', 'B', 'C', eller default 'A' hvis ikke found
    """
    # Få hele sidelinnhold
    page_text = soup.get_text()
    
    # Søg efter "A-rækken", "B-rækken", "C-rækken"
    if 'A-rækken' in page_text:
        return 'A'
    elif 'B-rækken' in page_text:
        return 'B'
    elif 'C-rækken' in page_text:
        return 'C'
    
    # Default til A hvis ikke found
    return 'A'

# ----------------------------
# Kontrakt parsing
# ----------------------------

def parse_contract(contract_raw: str):
    txt = clean(contract_raw)
    if not txt:
        return ("", None, "", "")

    txt = txt.replace("UT", "NT")

    # VIGTIGT: én linje
    m = re.search(r"\b([NSØV])\b\s*([1-7])\s*(NT|[SHDC♠♥♦♣])", txt)
    if not m:
        return ("", None, "", "")

    decl = m.group(1)
    level = int(m.group(2))
    strain_raw = m.group(3)

    if strain_raw in ["S", "H", "D", "C", "♠", "♥", "♦", "♣"]:
        strain = SUIT_MAP.get(strain_raw, strain_raw)
    else:
        strain = "NT"

    contract_clean = f"{level}{strain}" if strain != "NT" else f"{level}NT"
    return (decl, level, strain, contract_clean)

# ----------------------------
# Hænder (robust token parsing)
# ----------------------------

def normalize_ranks(txt: str) -> str:
    if not txt:
        return ""
    t = clean(txt).replace(" ", "")
    return "".join(RANK_TRANSLATE.get(ch, ch) for ch in t)

def hand_from_4_suits(sp: str, he: str, di: str, cl: str) -> str:
    """Convert 4-suit hands to dot notation S.H.D.C"""
    sp = normalize_ranks(sp)
    he = normalize_ranks(he)
    di = normalize_ranks(di)
    cl = normalize_ranks(cl)
    return f"{sp}.{he}.{di}.{cl}" if any([sp, he, di, cl]) else None

def parse_hands_from_game_div(game_div) -> dict:
    """Parse N/S/Ø/V hands from a game div"""
    hands = {}
    for pos in ["N", "S", "Ø", "V"]:
        div = game_div.select_one(f"div.hand.{pos}")
        if div:
            suits = div.select("div.suit")
            if len(suits) == 4:
                sp = clean(suits[0].get_text(" ", strip=True))
                he = clean(suits[1].get_text(" ", strip=True))
                di = clean(suits[2].get_text(" ", strip=True))
                cl = clean(suits[3].get_text(" ", strip=True))
                hands[f"{pos}_hand"] = hand_from_4_suits(sp, he, di, cl)
    return hands

def _debug_print_handcheck(board: int, hands: dict):
    print(f"    Board {board} hands: {hands}")

# ----------------------------
# Hovedscrape
# ----------------------------

def scrape_spilresultater(
    spil_url: str,
    tournament_date,
    include_hands: bool = True,
    debug_hands: bool = False
):
    """
    Scrape spilresultater from URL.
    
    Adds 'row' column based on page content (A/B/C).
    """
    soup = get_soup(spil_url)
    rows = []
    hands_by_board = {}
    
    # Extract row letter from page content
    row_letter = extract_row_from_page(soup)
    print(f"    → Detekteret row: {row_letter}")

    for game in soup.select("div.game"):
        board_div = game.select_one("div.boardNo")
        if not board_div:
            continue

        board_txt = clean(board_div.get_text())
        if not board_txt.isdigit():
            continue
        board = int(board_txt)

        if include_hands and board not in hands_by_board:
            hands_by_board[board] = parse_hands_from_game_div(game)
            if debug_hands and hands_by_board[board]:
                _debug_print_handcheck(board, hands_by_board[board])

        for li in game.select("ul.bridge li.table"):
            teams = li.select("div.team-name.uk-hidden-small")
            if len(teams) < 2:
                continue

            ns = clean(teams[0].get_text(" ", strip=True))
            ew = clean(teams[1].get_text(" ", strip=True))

            ns_parts = [p.strip() for p in ns.split(" - ")]
            ew_parts = [p.strip() for p in ew.split(" - ")]
            if len(ns_parts) < 2 or len(ew_parts) < 2:
                continue

            contract_div = li.select_one("div.info.contract")
            contract_raw = clean(contract_div.get_text(" ", strip=True)) if contract_div else ""
            decl, level, strain, contract_clean = parse_contract(contract_raw)

            lead = ""
            tricks = None
            tricks_divs = li.select("div.info.tricks")
            if len(tricks_divs) >= 1:
                lead = clean(tricks_divs[0].get_text(" ", strip=True))
            if len(tricks_divs) >= 2:
                t = clean(tricks_divs[1].get_text(" ", strip=True))
                if t.isdigit():
                    tricks = int(t)

            imp_vals = [clean(d.get_text(" ", strip=True)) for d in li.select("div.info.imp")]
            pct_ns = safe_pct(imp_vals[2]) if len(imp_vals) > 2 else None
            pct_ew = safe_pct(imp_vals[3]) if len(imp_vals) > 3 else None

            hb = hands_by_board.get(board, {}) if include_hands else {}

            rows.append({
                "tournament_date": tournament_date.date() if tournament_date else None,
                "board": board,
                "row": row_letter,  # ✅ NY: row letter (A/B/C) fra side-indhold

                "ns1": ns_parts[0],
                "ns2": ns_parts[1],
                "ew1": ew_parts[0],
                "ew2": ew_parts[1],

                "decl": decl,
                "level": level,
                "strain": strain,
                "contract": contract_clean,
                "contract_raw": contract_raw,

                "lead": lead,
                "tricks": tricks,

                "pct_NS": pct_ns,
                "pct_ØV": pct_ew,

                "spil_url": spil_url,

                "N_hand": hb.get("N_hand"),
                "Ø_hand": hb.get("Ø_hand"),
                "S_hand": hb.get("S_hand"),
                "V_hand": hb.get("V_hand"),
            })

    if debug_hands and include_hands and not any(hands_by_board.values()):
        print(f"  (ingen hænder parsed)")

    return rows