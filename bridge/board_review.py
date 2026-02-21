import pandas as pd
import numpy as np


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