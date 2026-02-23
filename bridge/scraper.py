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

# ----------------------------
# Dealer / vulnerability
# ----------------------------

DEALER_MAP = {"Nord": "N", "Syd": "S", "Øst": "Ø", "Vest": "V"}

# ----------------------------
# Double Dummy constants
# ----------------------------

_DD_DIRS = ["N", "S", "Ø", "V"]
_DD_STRAINS = ["NT", "S", "H", "D", "C"]  # NT, ♠, ♥, ♦, ♣
_DD_FIELDS = (
    [f"dd_{d}_{s}" for d in _DD_DIRS for s in _DD_STRAINS]
    + [f"dd_{d}_HCP" for d in _DD_DIRS]
)

# ----------------------------
# Par regex
# ----------------------------

PAR_RE = re.compile(r'Par:\s*(-?\d+)\s+([1-7](?:NT|[♠♥♦♣]))\s+(\S+)', re.UNICODE)

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
    """
    Parse N/S/Ø/V hands from a game div.

    Scans for elements containing suit symbols (♠♥♦♣) with card text
    in Danish notation (E=Ace, K=King, D=Queen, B=Jack, T=Ten).
    Maps up to 4 found hand blocks to N, V, Ø, S positions in order.
    """
    SUIT_LINE_PAT = re.compile(r'([♠♥♦♣])\s*([EKDBT98765432\-—]*)', re.UNICODE)

    # Find smallest elements each containing exactly one complete hand (all 4 suits)
    hand_blocks = []
    seen_elem_ids = set()

    for elem in game_div.find_all(True):
        eid = id(elem)
        if eid in seen_elem_ids:
            continue
        text = elem.get_text(" ", strip=True)
        matches = SUIT_LINE_PAT.findall(text)
        suit_syms = [m[0] for m in matches]
        # Exactly 4 entries covering all 4 distinct suits → one complete hand
        if len(matches) == 4 and set(suit_syms) == {'♠', '♥', '♦', '♣'}:
            hand_blocks.append(matches)
            # Mark descendants as seen to avoid double-counting via parent elements
            for child in elem.find_all(True):
                seen_elem_ids.add(id(child))

    # Map to positions N, V, Ø, S in the order found
    positions = ["N", "V", "Ø", "S"]
    hands = {}
    for i, block in enumerate(hand_blocks[:4]):
        pos = positions[i]
        suit_cards = dict(block)
        sp = suit_cards.get("♠", "")
        he = suit_cards.get("♥", "")
        di = suit_cards.get("♦", "")
        cl = suit_cards.get("♣", "")
        result = hand_from_4_suits(sp, he, di, cl)
        if result:
            hands[f"{pos}_hand"] = result

    return hands

def _debug_print_handcheck(board: int, hands: dict):
    print(f"    Board {board} hands: {hands}")

# ----------------------------
# Dealer / vul parsing
# ----------------------------

def parse_dealer_vul(game_div) -> dict:
    """Parse dealer and vulnerability from a game div.

    Returns a dict with keys 'dealer' and 'vul'.
    dealer is normalized to compass letter (N/S/Ø/V) via DEALER_MAP.
    vul is stored raw as seen in the HTML ('-', 'NS', 'ØV', 'Alle', …).
    """
    result = {"dealer": None, "vul": None}

    dealer_span = game_div.select_one("span.dealer")
    if dealer_span:
        raw = clean(dealer_span.get_text())
        result["dealer"] = DEALER_MAP.get(raw, raw)

    vul_span = game_div.select_one("span.vulnerability")
    if vul_span:
        result["vul"] = clean(vul_span.get_text())

    return result

# ----------------------------
# Double Dummy table parsing
# ----------------------------

def parse_dd_table(game_div) -> dict:
    """Parse Double Dummy tricks table and HP from a game div.

    Looks for a div.uk-grid whose direct child elements include cells
    with text 'NT' and 'HP', then reads a 5×7 grid (header + 4 direction
    rows, each with 7 columns: label, NT, ♠, ♥, ♦, ♣, HP).

    Returns a dict with 'dd_valid' (bool) and, when True, all dd_* fields.
    """
    null_result = {"dd_valid": False}

    dd_grid = None
    for grid in game_div.find_all("div", class_="uk-grid"):
        child_texts = [clean(ch.get_text()) for ch in grid.children if ch.name]
        if "NT" in child_texts and "HP" in child_texts:
            dd_grid = grid
            break

    if dd_grid is None:
        return null_result

    cells = [clean(ch.get_text()) for ch in dd_grid.children if ch.name]

    # Locate header row: "NT" should be at column index 1 (second cell)
    try:
        nt_pos = cells.index("NT")
    except ValueError:
        return null_result

    n_cols = 7  # label + NT + ♠ + ♥ + ♦ + ♣ + HP
    header_start = nt_pos - 1

    if header_start < 0:
        return null_result
    if header_start + n_cols > len(cells):
        return null_result
    if cells[header_start + 6] != "HP":
        return null_result

    # Need at least 4 data rows after the header
    if header_start + n_cols * 5 > len(cells):
        return null_result

    result = {"dd_valid": True}

    for row_idx, dir_code in enumerate(_DD_DIRS):
        row_start = header_start + n_cols * (row_idx + 1)
        row = cells[row_start:row_start + n_cols]
        # row[1..5] → NT/♠/♥/♦/♣ tricks, row[6] → HP
        for col_idx, strain_key in enumerate(_DD_STRAINS):
            val_str = row[col_idx + 1] if col_idx + 1 < len(row) else ""
            try:
                result[f"dd_{dir_code}_{strain_key}"] = int(val_str)
            except (ValueError, TypeError):
                result[f"dd_{dir_code}_{strain_key}"] = None
        try:
            result[f"dd_{dir_code}_HCP"] = int(row[6]) if len(row) > 6 else None
        except (ValueError, TypeError):
            result[f"dd_{dir_code}_HCP"] = None

    return result

# ----------------------------
# Par parsing
# ----------------------------

def parse_par(game_div) -> dict:
    """Parse par contract/score from a game div.

    Looks for text like 'Par: -980 6♠ ØV' anywhere in the div.

    Returns a dict with 'par_score' (int or None), 'par_contract' (str or None),
    'par_side' (str or None).
    """
    null_result = {"par_score": None, "par_contract": None, "par_side": None}
    text = clean(game_div.get_text(" "))
    m = PAR_RE.search(text)
    if not m:
        return null_result
    try:
        score = int(m.group(1))
    except (ValueError, TypeError):
        score = None
    return {
        "par_score": score,
        "par_contract": m.group(2),
        "par_side": m.group(3),
    }

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
    
    Parameters:
    -----------
    debug_hands: bool
        If True, print HTML debugging info for first game
    """
    soup = get_soup(spil_url)
    rows = []
    hands_by_board = {}
    board_meta = {}
    
    # Extract row letter from page content
    row_letter = extract_row_from_page(soup)
    print(f"    → Detekteret row: {row_letter}")

    games = soup.select("div.game")
    print(f"    → Fundet {len(games)} games")
    
    for game_idx, game in enumerate(games):
        board_div = game.select_one("div.boardNo")
        if not board_div:
            continue

        board_txt = clean(board_div.get_text())
        if not board_txt.isdigit():
            continue
        board = int(board_txt)

        if include_hands and board not in hands_by_board:
            #hands_by_board[board] = parse_hands_from_game_div(game, debug=(debug_hands and game_idx == 0))
            hands_by_board[board] = parse_hands_from_game_div(game)
            if debug_hands and hands_by_board[board]:
                _debug_print_handcheck(board, hands_by_board[board])

        if board not in board_meta:
            meta = {}
            meta.update(parse_dealer_vul(game))
            meta.update(parse_dd_table(game))
            meta.update(parse_par(game))
            board_meta[board] = meta

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
            decl = decl or ""

            lead = ""
            tricks = None
            tricks_divs = li.select("div.info.tricks")
            if len(tricks_divs) >= 1:
                lead = clean(tricks_divs[0].get_text(" ", strip=True))
            if len(tricks_divs) >= 2:
                t = clean(tricks_divs[1].get_text(" ", strip=True))
                if t.isdigit():
                    tricks = int(t)

            # ----------------------------------------------------------
            # Score (bridge.dk style: only one side filled; do NOT mirror)
            # ----------------------------------------------------------
            score_divs = li.select("div.info.tableScore")
            score_texts = [clean(d.get_text(" ", strip=True)) for d in score_divs]

            def _parse_int_or_none(s: str):
                if not s:
                    return None
                s2 = s.replace("\xa0", "").replace(" ", "")
                try:
                    return int(s2)
                except Exception:
                    return None

            score_ns = _parse_int_or_none(score_texts[0]) if len(score_texts) > 0 else None
            score_ew = _parse_int_or_none(score_texts[1]) if len(score_texts) > 1 else None

            # ----------------------------------------------------------
            # Points (MP/IMP) and Pct parsing
            # ----------------------------------------------------------
            imp_divs = li.select("div.info.imp")

            point_texts = []
            pct_texts = []
            for d in imp_divs:
                classes = set(d.get("class", []))
                txt = clean(d.get_text(" ", strip=True))
                if not txt:
                    continue
                is_pct = ("uk-hidden-medium" in classes) and ("uk-hidden-small" in classes)
                if is_pct:
                    pct_texts.append(txt)
                else:
                    point_texts.append(txt)

            point_ns = safe_pct(point_texts[0]) if len(point_texts) > 0 else None
            point_ew = safe_pct(point_texts[1]) if len(point_texts) > 1 else None
            pct_ns = safe_pct(pct_texts[0]) if len(pct_texts) > 0 else None
            pct_ew = safe_pct(pct_texts[1]) if len(pct_texts) > 1 else None

            hb = hands_by_board.get(board, {}) if include_hands else {}
            bm = board_meta.get(board, {})

            row_dict = {
                "tournament_date": tournament_date.date() if tournament_date else None,
                "board": board,
                "board_no": board,
                "row": row_letter,

                "ns1": ns_parts[0],
                "ns2": ns_parts[1],
                "ew1": ew_parts[0],
                "ew2": ew_parts[1],

                "ns_pair": f"{ns_parts[0]} - {ns_parts[1]}",
                "ew_pair": f"{ew_parts[0]} - {ew_parts[1]}",

                "decl": decl,
                "level": level,
                "strain": strain,
                "contract": contract_clean,
                "contract_raw": contract_raw,

                "lead": lead,
                "tricks": tricks,

                "score_NS": score_ns,
                "score_ØV": score_ew,
                "point_NS": point_ns,
                "point_ØV": point_ew,
                "pct_NS": pct_ns,
                "pct_ØV": pct_ew,

                "spil_url": spil_url,

                "N_hand": hb.get("N_hand"),
                "Ø_hand": hb.get("Ø_hand"),
                "S_hand": hb.get("S_hand"),
                "V_hand": hb.get("V_hand"),

                "dealer": bm.get("dealer"),
                "vul": bm.get("vul"),

                "dd_valid": bm.get("dd_valid", False),

                "par_score": bm.get("par_score"),
                "par_contract": bm.get("par_contract"),
                "par_side": bm.get("par_side"),
            }
            for key in _DD_FIELDS:
                row_dict[key] = bm.get(key)
            rows.append(row_dict)
    if debug_hands and include_hands and not any(hands_by_board.values()):
        print(f"  ⚠️ ADVARSEL: ingen hænder parsed! Check HTML struktur ovenfor")

    return rows