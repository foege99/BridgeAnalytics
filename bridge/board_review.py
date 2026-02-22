import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Direction helpers shared by board-layout functions
# ---------------------------------------------------------------------------

# Maps player-column name to compass direction code
_PLAYER_COL_TO_DIR = {'ns1': 'N', 'ns2': 'S', 'ew1': 'Ø', 'ew2': 'V'}

# Rotation tables: Per's original direction → display positions
# display positions: bottom (Per), top (partner), left (opponent), right (opponent)
_ROTATIONS = {
    'S': {'bottom': 'S', 'top': 'N', 'left': 'V', 'right': 'Ø'},
    'N': {'bottom': 'N', 'top': 'S', 'left': 'Ø', 'right': 'V'},
    'Ø': {'bottom': 'Ø', 'top': 'V', 'left': 'S', 'right': 'N'},
    'V': {'bottom': 'V', 'top': 'Ø', 'left': 'N', 'right': 'S'},
}


def _hand_suit_lines(hand_str) -> list:
    """Convert dot-format hand string (S.H.D.C) to 4 suit lines with symbols."""
    if hand_str is None or (isinstance(hand_str, float) and pd.isna(hand_str)):
        parts = ['-', '-', '-', '-']
    else:
        parts = str(hand_str).split('.')
        while len(parts) < 4:
            parts.append('-')
    suits = ['♠', '♥', '♦', '♣']
    return [f"{s} {p}" for s, p in zip(suits, parts)]


def write_board1_layout_sheet(writer, df: pd.DataFrame, per_name: str) -> None:
    """
    Write sheet 'Board1_LastTournament' to *writer* (an open pd.ExcelWriter).

    Shows board 1 from the latest tournament date present in *df* in a classic
    bridge table layout, rotated so that *per_name* is always at the bottom.

    If the required data is not available the sheet is still created with a
    descriptive message instead of raising an exception.
    """
    try:
        from openpyxl.styles import Font
    except ImportError:
        Font = None  # graceful degradation – no bold formatting

    try:
        from openpyxl.cell.rich_text import CellRichText, TextBlock
        from openpyxl.cell.text import InlineFont
        _RED_FONT = InlineFont(color='FF0000')
        _rich_text_available = True
    except ImportError:
        _rich_text_available = False

    wb = writer.book
    ws = wb.create_sheet("Board1_LastTournament")

    def _write_msg(msg: str) -> None:
        ws.cell(row=1, column=1, value=msg)

    def _bold(cell):
        if Font is not None:
            cell.font = Font(bold=True)
        return cell

    def _write_suit_line(cell, line: str) -> None:
        """Write a suit line; colour ♥ and ♦ symbols red when rich text is available."""
        if _rich_text_available and line and line[0] in ('♥', '♦'):
            cell.value = CellRichText([TextBlock(_RED_FONT, line[0]), line[1:]])
        else:
            cell.value = line

    # ------------------------------------------------------------------
    # 1. Validate input
    # ------------------------------------------------------------------
    if df is None or df.empty:
        _write_msg("Ingen data tilgængelig.")
        return

    if 'board_no' not in df.columns:
        _write_msg("Kolonnen 'board_no' mangler i datasættet.")
        return

    if 'tournament_date' not in df.columns:
        _write_msg("Kolonnen 'tournament_date' mangler i datasættet.")
        return

    # ------------------------------------------------------------------
    # 2. Latest tournament date → board 1
    # ------------------------------------------------------------------
    latest_date = df['tournament_date'].max()
    df_latest = df[df['tournament_date'] == latest_date]
    df_b1 = df_latest[df_latest['board_no'] == 1]

    if df_b1.empty:
        _write_msg(f"Spil 1 ikke fundet for seneste turnering ({latest_date}).")
        return

    # ------------------------------------------------------------------
    # 3. Find the row where Per appears
    # ------------------------------------------------------------------
    per_row = None
    per_dir = None

    for _, row in df_b1.iterrows():
        for col, dir_code in _PLAYER_COL_TO_DIR.items():
            if row.get(col) == per_name:
                per_row = row
                per_dir = dir_code
                break
        if per_row is not None:
            break

    if per_row is None:
        _write_msg(
            f"{per_name} ikke fundet i Spil 1 for seneste turnering ({latest_date})."
        )
        return

    # ------------------------------------------------------------------
    # 4. Build display data
    # ------------------------------------------------------------------
    rot = _ROTATIONS[per_dir]

    dir_to_player = {
        'N': per_row.get('ns1', ''),
        'S': per_row.get('ns2', ''),
        'Ø': per_row.get('ew1', ''),
        'V': per_row.get('ew2', ''),
    }
    dir_to_hand = {
        'N': per_row.get('N_hand'),
        'S': per_row.get('S_hand'),
        'Ø': per_row.get('Ø_hand'),
        'V': per_row.get('V_hand'),
    }

    # HCP lookup per direction
    _hcp_col_map = {'N': 'N_HCP', 'S': 'S_HCP', 'Ø': 'Ø_HCP', 'V': 'V_HCP'}

    def _get_hcp(dir_code: str):
        """Return HCP for *dir_code* as int, or '?' if unavailable.

        Looks up the per-direction HCP column (e.g. 'N_HCP') first;
        falls back to computing from the dot-format hand string.
        """
        col = _hcp_col_map.get(dir_code, '')
        if col and col in per_row.index:
            val = per_row.get(col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                return int(val)
        # Fallback: compute from hand string
        hand = dir_to_hand.get(dir_code)
        if hand is not None and not (isinstance(hand, float) and pd.isna(hand)):
            try:
                from bridge.hand_eval import parse_hand, hcp as _calc_hcp
                return _calc_hcp(parse_hand(str(hand)))
            except Exception:
                pass
        return '?'

    def _player_label(dir_code: str) -> str:
        name = dir_to_player.get(dir_code, '')
        return f"{dir_code}: {name}  {_get_hcp(dir_code)} HCP"

    # Graceful field lookup (tries multiple candidate column names)
    def _get_field(row, *candidates):
        """Return the first non-null value found in *row* for any of *candidates*.

        Parameters
        ----------
        row : pandas Series
            The data row to inspect.
        *candidates : str
            Column names to try in order.

        Returns
        -------
        The first non-null field value, or None if all candidates are missing/null.
        """
        for c in candidates:
            if c in row.index:
                val = row.get(c)
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    return val
        return None

    top_dir = rot['top']
    left_dir = rot['left']
    right_dir = rot['right']
    bottom_dir = rot['bottom']  # always Per

    # ------------------------------------------------------------------
    # 5. Write to sheet
    #
    # Layout (columns A=1, B=2, C=3, E=5):
    #   Row 1 : title (B)  |  Turnering (E)
    #   Row 2 : top player name (B)  |  Board (E)
    #   Rows 3-6 : top hand suits (B)
    #   Row 3, E : Dealer
    #   Row 4, E : Zone
    #   Row 8 : left name (A)  |  right name (C)  |  Kontrakt (E)
    #   Rows 9-12 : left suits (A)  |  right suits (C)
    #   Row 9, E : Declarer
    #   Row 10, E : Udspil
    #   Row 11, E : Resultat
    #   Row 12, E : NS HCP
    #   Row 13, E : ØV HCP
    #   Row 14 : bottom player name (col B)
    #   Rows 15-18 : bottom hand suits (col B)
    # ------------------------------------------------------------------
    section_val = per_row.get('section', '')
    ws.cell(row=1, column=2,
            value=f"Spil 1 – {latest_date} (sektion {section_val})")
    _bold(ws.cell(row=1, column=2))

    # --- Header block (col E) ---
    dealer_val = _get_field(per_row, 'dealer', 'Dealer')
    zone_val = _get_field(per_row, 'vul', 'vulnerability', 'zone', 'Zone')
    ws.cell(row=1, column=5, value=f"Turnering: {latest_date}")
    ws.cell(row=2, column=5, value="Board: 1")
    ws.cell(row=3, column=5,
            value=f"Dealer: {dealer_val if dealer_val is not None else '(ukendt)'}")
    ws.cell(row=4, column=5,
            value=f"Zone: {zone_val if zone_val is not None else '(ukendt)'}")

    # --- Top hand ---
    _bold(ws.cell(row=2, column=2, value=_player_label(top_dir)))
    for i, line in enumerate(_hand_suit_lines(dir_to_hand.get(top_dir))):
        _write_suit_line(ws.cell(row=3 + i, column=2), line)

    # --- Left hand ---
    _bold(ws.cell(row=8, column=1, value=_player_label(left_dir)))
    for i, line in enumerate(_hand_suit_lines(dir_to_hand.get(left_dir))):
        _write_suit_line(ws.cell(row=9 + i, column=1), line)

    # --- Right hand ---
    _bold(ws.cell(row=8, column=3, value=_player_label(right_dir)))
    for i, line in enumerate(_hand_suit_lines(dir_to_hand.get(right_dir))):
        _write_suit_line(ws.cell(row=9 + i, column=3), line)

    # --- Bottom hand (Per) ---
    _bold(ws.cell(row=14, column=2, value=_player_label(bottom_dir)))
    for i, line in enumerate(_hand_suit_lines(dir_to_hand.get(bottom_dir))):
        _write_suit_line(ws.cell(row=15 + i, column=2), line)

    # --- Right-side info block (col E, rows 8-13) ---
    contract_val = _get_field(per_row, 'contract')
    decl_val = _get_field(per_row, 'decl')
    lead_val = _get_field(per_row, 'lead')
    tricks_val = _get_field(per_row, 'tricks')

    def _side_hcp_total(col_name: str, dir1: str, dir2: str):
        """Return combined HCP for a side from a column, or by summing per-direction HCP."""
        val = _get_field(per_row, col_name)
        if val is not None:
            return val
        h1, h2 = _get_hcp(dir1), _get_hcp(dir2)
        if h1 != '?' and h2 != '?':
            return int(h1) + int(h2)
        return None

    # NS/ØV HCP totals: prefer combined columns, else sum per-hand
    ns_hcp = _side_hcp_total('NS_HCP', 'N', 'S')
    ov_hcp = _side_hcp_total('ØV_HCP', 'Ø', 'V')

    ws.cell(row=8,  column=5, value=f"Kontrakt: {contract_val if contract_val is not None else '(ukendt)'}")
    ws.cell(row=9,  column=5, value=f"Declarer: {decl_val if decl_val is not None else '(ukendt)'}")
    ws.cell(row=10, column=5, value=f"Udspil: {lead_val if lead_val is not None else '(ukendt)'}")
    ws.cell(row=11, column=5, value=f"Resultat: {tricks_val if tricks_val is not None else '(ukendt)'}")
    ws.cell(row=12, column=5, value=f"NS HCP: {ns_hcp if ns_hcp is not None else '(ukendt)'}")
    ws.cell(row=13, column=5, value=f"ØV HCP: {ov_hcp if ov_hcp is not None else '(ukendt)'}")

    # --- Column widths ---
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 22
    ws.column_dimensions['C'].width = 22
    ws.column_dimensions['E'].width = 25


def make_board_review_all_hands(df: pd.DataFrame) -> pd.DataFrame:
    """
    Board Review rapport: ÉN RÆKKE PER HÅND
    
    Viser hver enkelt hånd med Phase 2.1 reference-data OG hånd-features.
    Sorteret efter tournament_date → board_no → row → performance-forskel.
    
    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame med Phase 2.1 kolonner og hånd-features
    
    Returns:
    --------
    pd.DataFrame
        Board review med alle hænder, sorteret efter dato, board og row
    """
    
    if df.empty:
        return df
        
    # === Define performance_cols FIRST ===
    performance_cols = [
        'tournament_date',
        'board_no',
        'row',
        'contract',
        'expected_pct',
        'pct_NS',
        'pct_vs_expected',
        'pct_vs_expected_abs',
        'Board_Type',
        'competitive_flag',
    ]


    # Vælg relevante kolonner
    cols_to_keep = [
        'tournament_date',
        'board_no',
        'row',
        'contract',
        'expected_pct',
        'pct_NS',
        'pct_vs_expected',
        'pct_vs_expected_abs',
        'Board_Type',
        'competitive_flag',
    ]

    hand_cols = [
        'N_hand', 'S_hand', 'Ø_hand', 'V_hand',
        'N_HCP', 'S_HCP', 'Ø_HCP', 'V_HCP', 'NS_HCP', 'ØV_HCP',
        'N_shape', 'S_shape', 'Ø_shape', 'V_shape',
        'N_shape_SHDC', 'S_shape_SHDC', 'Ø_shape_SHDC', 'V_shape_SHDC',
        'N_balanced', 'S_balanced', 'Ø_balanced', 'V_balanced',
        'N_dist_pts_shortage', 'S_dist_pts_shortage', 'Ø_dist_pts_shortage', 'V_dist_pts_shortage',
        'N_LTC_adj', 'S_LTC_adj', 'Ø_LTC_adj', 'V_LTC_adj', 'NS_LTC_adj', 'ØV_LTC_adj',
        'N_controls', 'S_controls', 'Ø_controls', 'V_controls', 'NS_controls', 'ØV_controls',
        'N_aces', 'S_aces', 'Ø_aces', 'V_aces', 'NS_aces', 'ØV_aces',
        'N_kings', 'S_kings', 'Ø_kings', 'V_kings', 'NS_kings', 'ØV_kings',
        'Declarer_Side', 'Declarer_HCP', 'Defense_HCP', 'HCP_diff',
        'Declarer_LTC_adj', 'Defense_LTC_adj', 'LTC_diff',
        'Suit_Index', 'NT_Index',
    ]

    reference_cols = [
        'contract_norm',
        'double_state',
        'decl',
        'level',
        'strain',
        'lead',
        'tricks',
        
        # ✅ RÅDATA HÆNDER
        'N_hand',
        'S_hand',
        'Ø_hand',
        'V_hand',
        
        # ✅ HCP (Høje kort point)
        'N_HCP',
        'S_HCP',
        'Ø_HCP',
        'V_HCP',
        'NS_HCP',
        'ØV_HCP',
        
        # ✅ KORTFORDELING (shape)
        'N_shape',
        'S_shape',
        'Ø_shape',
        'V_shape',
        'N_shape_SHDC',
        'S_shape_SHDC',
        'Ø_shape_SHDC',
        'V_shape_SHDC',
        
        # ✅ BALANCED
        'N_balanced',
        'S_balanced',
        'Ø_balanced',
        'V_balanced',
        
        # ✅ DISTRIBUTION POINTS
        'N_dist_pts_shortage',
        'S_dist_pts_shortage',
        'Ø_dist_pts_shortage',
        'V_dist_pts_shortage',
        
        # ✅ LTC (Losing Trick Count)
        'N_LTC_adj',
        'S_LTC_adj',
        'Ø_LTC_adj',
        'V_LTC_adj',
        'NS_LTC_adj',
        'ØV_LTC_adj',
        
        # ✅ CONTROLS (Aces + Kings)
        'N_controls',
        'S_controls',
        'Ø_controls',
        'V_controls',
        'NS_controls',
        'ØV_controls',
        
        # ✅ ACES & KINGS
        'N_aces',
        'S_aces',
        'Ø_aces',
        'V_aces',
        'N_kings',
        'S_kings',
        'Ø_kings',
        'V_kings',
        
        # ✅ CONTRACT-SIDE METRICS
        'Declarer_Side',
        'Declarer_HCP',
        'Defense_HCP',
        'HCP_diff',
        'Declarer_LTC_adj',
        'Defense_LTC_adj',
        'LTC_diff',
        'Suit_Index',
        'NT_Index',
        
        # ✅ PHASE 2.1 REFERENCE-DATA
        'field_mode_contract',
        'field_mode_count',
        'field_mode_freq',
        'top2_contract_1',
        'top2_contract_2',
        'top2_count_1',
        'top2_count_2',
        'reference_scope',
        'N_section_played',
    ]

    # Filtrer til kolonner som eksisterer (computed cols tilføjes efter copy)
    source_cols = hand_cols + reference_cols + [
        c for c in performance_cols if c not in ('pct_vs_expected', 'pct_vs_expected_abs')
    ]
    cols_available = [col for col in source_cols if col in df.columns]

    report = df[cols_available].copy()

    # Beregn forskel fra expected_pct
    report['pct_vs_expected'] = report['pct_NS'] - report['expected_pct']
    report['pct_vs_expected_abs'] = abs(report['pct_vs_expected'])
    
    # Sorter efter absolutt forskel (største først)
    report = report.sort_values('pct_vs_expected_abs', ascending=False, na_position='last')
    
    # Omarranger kolonner så performance-data er først
    performance_cols = [
        'tournament_date',
        'board_no',
        'row',  # ✅ NY: row letter
        'contract',
        'expected_pct',
        'pct_NS',
        'pct_vs_expected',
        'pct_vs_expected_abs',
        'Board_Type',
        'competitive_flag',
    ]
    
    other_cols = [col for col in cols_available if col not in performance_cols]
    
    report = report[performance_cols + other_cols]
    
    print(f"✓ Board Review (All Hands): {len(report)} rækker")
    
    return report


def make_board_review_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Board Review rapport: ÉN RÆKKE PER BOARD (aggregeret)
    
    Hver board vises med:
    - Antal hænder
    - Gennemsnit pct_NS
    - Expected pct
    - Gennemsnit forskel
    - Board klassifikation
    - Row (A/B/C)
    - Gennemsnit HCP per side
    - Gennemsnit LTC per side
    
    Sorteret efter Board_Type (Split først), så efter forskel.
    
    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame med Phase 2.1 kolonner og hånd-features
    
    Returns:
    --------
    pd.DataFrame
        Én række per board med aggregeret data
    """
    
    if df.empty:
        return df
    
    # Grupper per board
    grouped = df.groupby(['tournament_date', 'board_no']).agg({
    'row': 'first',
    'contract': 'first',
    'contract_norm': 'first',
    'decl': 'first',
    'level': 'first',
    'strain': 'first',
    'field_mode_contract': 'first',
    'field_mode_count': 'first',
    'field_mode_freq': 'first',
    'top2_contract_1': 'first',
    'top2_contract_2': 'first',
    'expected_pct': 'first',
    'pct_NS': 'mean',
    'reference_scope': 'first',
    'N_section_played': 'first',
    'Board_Type': 'first',
    'competitive_flag': 'first',
    # ✅ LEGG TIL DISSE:
    'NS_HCP': 'mean',
    'ØV_HCP': 'mean',
    'NS_LTC_adj': 'mean',
    'ØV_LTC_adj': 'mean',
    'NS_controls': 'mean',
    'ØV_controls': 'mean',
}).reset_index()

    
    # Rename for klarhed
    grouped = grouped.rename(columns={
        'pct_NS': 'avg_pct_NS',
        'contract': 'contract_actual',
        'NS_HCP': 'avg_NS_HCP',
        'ØV_HCP': 'avg_ØV_HCP',
        'NS_LTC_adj': 'avg_NS_LTC_adj',
        'ØV_LTC_adj': 'avg_ØV_LTC_adj',
        'NS_controls': 'avg_NS_controls',
        'ØV_controls': 'avg_ØV_controls',
    })
    
    # Antal hænder per board
    hand_counts = df.groupby(['tournament_date', 'board_no']).size().reset_index(name='num_hands')
    grouped = grouped.merge(hand_counts, on=['tournament_date', 'board_no'])
    
    # Beregn forskel
    grouped['avg_pct_vs_expected'] = grouped['avg_pct_NS'] - grouped['expected_pct']
    grouped['avg_pct_vs_expected_abs'] = abs(grouped['avg_pct_vs_expected'])
    
    # Sortering: Split først, så efter forskel
    sort_priority = {
        'Split': 0,
        'Dominant': 1,
        'Wild': 2,
        'LOW_SAMPLE': 3
    }
    grouped['sort_priority'] = grouped['Board_Type'].map(sort_priority)
    
    grouped = grouped.sort_values(
        ['sort_priority', 'avg_pct_vs_expected_abs'],
        ascending=[True, False],
        na_position='last'
    ).drop('sort_priority', axis=1)
    
    # Omarranger kolonner: performance → hånd-data → reference
    performance_cols = [
        'tournament_date',
        'board_no',
        'row',
        'num_hands',
        'contract_actual',
        'decl',
        'level',
        'strain',
        'expected_pct',
        'avg_pct_NS',
        'avg_pct_vs_expected',
        'avg_pct_vs_expected_abs',
        'Board_Type',
        'competitive_flag',
        'avg_NS_HCP',
        'avg_ØV_HCP',
        'avg_NS_LTC_adj',
        'avg_ØV_LTC_adj',
        'avg_NS_controls',
        'avg_ØV_controls',
    ]
    
    other_cols = [col for col in grouped.columns if col not in performance_cols]
    
    grouped = grouped[performance_cols + other_cols]
    
    print(f"✓ Board Review (Summary): {len(grouped)} boards")
    print(f"  Split boards: {(grouped['Board_Type'] == 'Split').sum()}")
    print(f"  Dominant boards: {(grouped['Board_Type'] == 'Dominant').sum()}")
    print(f"  Wild boards: {(grouped['Board_Type'] == 'Wild').sum()}")
    
    return grouped


def board_review_statistics(df_all_hands: pd.DataFrame, df_summary: pd.DataFrame) -> dict:
    """
    Beregn deskriptiv statistik for Board Review.
    
    Parameters:
    -----------
    df_all_hands : pd.DataFrame
        Output fra make_board_review_all_hands()
    
    df_summary : pd.DataFrame
        Output fra make_board_review_summary()
    
    Returns:
    --------
    dict
        Statistik som kan bruges til print eller rapport
    """
    
    stats = {
        'total_boards': len(df_summary),
        'total_hands': len(df_all_hands),
        
        'split_boards': (df_summary['Board_Type'] == 'Split').sum(),
        'dominant_boards': (df_summary['Board_Type'] == 'Dominant').sum(),
        'wild_boards': (df_summary['Board_Type'] == 'Wild').sum(),
        
        'avg_pct_overall': df_all_hands['pct_NS'].mean(),
        'avg_expected_pct': df_all_hands['expected_pct'].mean(),
        'avg_performance_vs_expected': df_all_hands['pct_vs_expected'].mean(),
        
        'best_board': df_summary.loc[df_summary['avg_pct_vs_expected'].idxmax()] if len(df_summary) > 0 else None,
        'worst_board': df_summary.loc[df_summary['avg_pct_vs_expected'].idxmin()] if len(df_summary) > 0 else None,
        
        'split_boards_avg_vs_expected': df_summary[df_summary['Board_Type'] == 'Split']['avg_pct_vs_expected'].mean(),
        'dominant_boards_avg_vs_expected': df_summary[df_summary['Board_Type'] == 'Dominant']['avg_pct_vs_expected'].mean(),
        'wild_boards_avg_vs_expected': df_summary[df_summary['Board_Type'] == 'Wild']['avg_pct_vs_expected'].mean(),
    }
    
    return stats


def print_board_review_stats(stats: dict) -> None:
    """
    Print Board Review statistik i læselig format.
    
    Parameters:
    -----------
    stats : dict
        Output fra board_review_statistics()
    """
    
    print("\n" + "="*70)
    print("BOARD REVIEW STATISTIK")
    print("="*70)
    
    print(f"\nOVERALL:")
    print(f"  Total boards: {stats['total_boards']}")
    print(f"  Total hands: {stats['total_hands']}")
    print(f"  Avg hands per board: {stats['total_hands'] / max(stats['total_boards'], 1):.1f}")
    
    print(f"\nBOARD TYPES:")
    print(f"  Split boards: {stats['split_boards']}")
    print(f"  Dominant boards: {stats['dominant_boards']}")
    print(f"  Wild boards: {stats['wild_boards']}")
    
    print(f"\nPERFORMANCE:")
    print(f"  Overall avg pct: {stats['avg_pct_overall']:.1f}%")
    print(f"  Expected avg pct: {stats['avg_expected_pct']:.1f}%")
    print(f"  Difference: {stats['avg_performance_vs_expected']:+.1f}%")
    
    print(f"\nPERFORMANCE BY BOARD TYPE:")
    if not pd.isna(stats['split_boards_avg_vs_expected']):
        print(f"  Split boards: {stats['split_boards_avg_vs_expected']:+.1f}%")
    if not pd.isna(stats['dominant_boards_avg_vs_expected']):
        print(f"  Dominant boards: {stats['dominant_boards_avg_vs_expected']:+.1f}%")
    if not pd.isna(stats['wild_boards_avg_vs_expected']):
        print(f"  Wild boards: {stats['wild_boards_avg_vs_expected']:+.1f}%")
    
    if stats['best_board'] is not None:
        best = stats['best_board']
        print(f"\nBEST BOARD:")
        print(f"  {best['tournament_date']} - Board {best['board_no']} (Row {best['row']})")
        print(f"  Performance: {best['avg_pct_vs_expected']:+.1f}% vs expected")
    
    if stats['worst_board'] is not None:
        worst = stats['worst_board']
        print(f"\nWORST BOARD:")
        print(f"  {worst['tournament_date']} - Board {worst['board_no']} (Row {worst['row']})")
        print(f"  Performance: {worst['avg_pct_vs_expected']:+.1f}% vs expected")
    
    print("\n" + "="*70)