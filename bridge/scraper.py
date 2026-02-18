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
    return f"{normalize_ranks(sp)}.{normalize_ranks(he)}.{normalize_ranks(di)}.{normalize_ranks(cl)}"

def _looks_like_cards(token: str) -> bool:
    """
    True hvis token ligner en kortstreng, fx 'AKT72' i DK-form: 'EKDTB...' eller tal.
    Tillader tom streng (void) og '-' som void.
    """
    if token is None:
        return False
    t = clean(token).replace(" ", "")
    if t == "" or t == "-" or t == "—":
        return True
    # må kun bestå af rank-tegn (DK)
    return all(ch in RANK_CHARS_DK for ch in t)

def _tokenize_suit_lines(game_div) -> list:
    """
    Bygger en liste af suit-linjer i standard form:
      '♠ AKT7', '♥ E73', ...

    Den håndterer både:
      - '♠ AKT7' som én tekst
      - '♠' som token efterfulgt af 'AKT7' som næste token
    """
    tokens = [clean(t) for t in game_div.stripped_strings]
    lines = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue

        # Case 1: token starter med suit, fx "♠ AKT7" eller bare "♠"
        if tok[0] in SUIT_CHARS:
            suit = tok[0]
            rest = clean(tok[1:])

            # Hvis rest allerede indeholder kort, brug den
            if rest and _looks_like_cards(rest):
                lines.append(suit + " " + rest)
                i += 1
                continue

            # Hvis token er bare suit (eller rest ikke ligner kort), kig på næste token
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if _looks_like_cards(nxt):
                # nxt kan være '' / '-' (void) eller faktiske kort
                payload = "" if nxt in ["", "-", "—"] else nxt
                lines.append(suit + (" " + payload if payload else ""))
                i += 2
                continue

            # Ellers: det var nok en overskrift/pynt -> ignorer
            i += 1
            continue

        i += 1

    return lines

def _suit_payload(line: str) -> str:
    # "♠ AKT7" -> "AKT7", "♣" -> ""
    l = clean(line)
    if not l:
        return ""
    if l[0] in SUIT_CHARS:
        return clean(l[1:])
    return ""

def _count_cards(dot: str) -> int:
    return len((dot or "").replace(".", ""))

def _expand_cards(dot: str) -> set:
    if not dot:
        return set()
    suits = dot.split(".")
    out = set()
    for suit_letter, cards in zip(["S", "H", "D", "C"], suits):
        for r in cards:
            out.add(f"{suit_letter}{r}")
    return out

def _score_hands(hands4: list) -> tuple:
    all_cards = set()
    total = 0
    for h in hands4:
        total += _count_cards(h)
        all_cards |= _expand_cards(h)
    return (len(all_cards), total)

def parse_hands_from_game_div(game_div) -> dict:
    """
    Finder bedste 16-linjers sekvens af suit-linjer og bygger 4 hænder.

    Returnerer {} hvis det ikke ser plausibelt ud.
    """
    suit_lines_all = _tokenize_suit_lines(game_div)
    if len(suit_lines_all) < 16:
        return {}

    best_hands = None
    best_score = (-1, -1)

    for start in range(0, len(suit_lines_all) - 15):
        win = suit_lines_all[start:start + 16]

        hands_4 = []
        for j in range(0, 16, 4):
            sp = _suit_payload(win[j + 0])
            he = _suit_payload(win[j + 1])
            di = _suit_payload(win[j + 2])
            cl = _suit_payload(win[j + 3])
            hands_4.append(hand_from_4_suits(sp, he, di, cl))

        uniq, total = _score_hands(hands_4)

        if (uniq, total) > best_score:
            best_score = (uniq, total)
            best_hands = hands_4

        if uniq == 52 and total == 52:
            break

    if not best_hands:
        return {}

    # Standard layout antagelse: N, V, Ø, S (DBf diagram-layout)
    n_hand, v_hand, o_hand, s_hand = best_hands[0], best_hands[1], best_hands[2], best_hands[3]

    # Plausibilitet: vi vil se mindst en del kort, ellers var det stadig "pynt"
    uniq, total = _score_hands([n_hand, o_hand, s_hand, v_hand])
    if uniq < 30 or total < 30:
        return {}

    return {"N_hand": n_hand, "Ø_hand": o_hand, "S_hand": s_hand, "V_hand": v_hand}

def _debug_print_handcheck(board: int, h: dict):
    print(f"\n[DEBUG] Board {board} hænder fundet:")
    print("  N:", h.get("N_hand"))
    print("  Ø:", h.get("Ø_hand"))
    print("  S:", h.get("S_hand"))
    print("  V:", h.get("V_hand"))

    print("  [DEBUG] 13-kort:",
          _count_cards(h.get("N_hand")),
          _count_cards(h.get("Ø_hand")),
          _count_cards(h.get("S_hand")),
          _count_cards(h.get("V_hand")))

    all_cards = set()
    for seat in ["N_hand", "Ø_hand", "S_hand", "V_hand"]:
        all_cards |= _expand_cards(h.get(seat))
    print("  [DEBUG] unikke kort:", len(all_cards))

# ----------------------------
# Hovedscrape
# ----------------------------

def scrape_spilresultater(
    spil_url: str,
    tournament_date,
    include_hands: bool = True,
    debug_hands: bool = False
):
    soup = get_soup(spil_url)
    rows = []
    hands_by_board = {}

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
        print("\n[DEBUG] Fandt ingen hænder på denne spilresultater-side (sandsynligvis ingen kort i HTML).")

    return rows
