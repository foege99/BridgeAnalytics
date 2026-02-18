import pandas as pd
import numpy as np
from typing import Optional


def add_phase21_fields(df: pd.DataFrame, section: str = "A", n_min: int = 12) -> pd.DataFrame:
    """
    Berigelse af DataFrame med Phase 2.1 reference-lag.
    
    Tilpasset til bridge.dk scraper-output hvor:
    - board_no kommer fra kolonne "board"
    - section er konstant (samme for hele datasættet)
    - Alle rækker antages være PLAYED
    - pct kommer fra "pct_NS"
    
    Parameters:
    -----------
    df : pd.DataFrame
        Input-DataFrame med kolonner fra bridge.dk scraper:
        - tournament_date (str, YYYY-MM-DD)
        - board (int) → mappes til board_no
        - contract (str, fx "4♥", "3NT", "4♥X")
        - pct_NS (float, 0-100) → mappes til pct
    
    section : str
        Section-identifikator (default: "A")
        I Sprint 1 er dette konstant for hele datasættet.
    
    n_min : int
        Minimum antal PLAYED resultater for at vælge SECTION/CLUB.
        Default: 12
    
    Returns:
    --------
    pd.DataFrame
        Original DataFrame + nye kolonner:
        - reference_scope (str: "SECTION", "CLUB", "LOW_SAMPLE")
        - N_section_played (int)
        - N_club_played (int)
        - reference_n_played (int)
        - field_mode_contract (str or None)
        - field_mode_count (int or None)
        - field_mode_freq (float or None)
        - top2_contract_1 (str or None)
        - top2_contract_2 (str or None)
        - top2_count_1 (int or None)
        - top2_count_2 (int or None)
        - Board_Type (str: "Dominant", "Split", "Wild", "LOW_SAMPLE")
        - competitive_flag (bool)
        - expected_pct (float or None)
        - contract_norm (str)
        - double_state (str: "", "X", "XX")
    """
    
    # === STEP 1: Input-validering ===
    if df.empty:
        print("⚠️ Phase 2.1: Input DataFrame er tom")
        return df
    
    required_cols = ['tournament_date', 'board', 'contract', 'pct_NS']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"❌ Phase 2.1: Manglende kolonner: {missing}")
    
    # Kopiér DataFrame
    df = df.copy()
    
    # === STEP 2: Map kolonnenavne til Phase 2.1 standard ===
    df['board_no'] = df['board'].astype(int)
    df['pct'] = pd.to_numeric(df['pct_NS'], errors='coerce')
    df['section'] = section
    df['result_status_code'] = 'PLAYED'  # Antag alle er PLAYED
    
    # === STEP 3: Normaliser kontrakter ===
    df['contract_norm'] = df['contract'].astype(str)
    df['double_state'] = ''
    
    for idx, row in df.iterrows():
        contract = str(row['contract'])
        
        if contract.endswith('XX'):
            df.at[idx, 'contract_norm'] = contract[:-2]
            df.at[idx, 'double_state'] = 'XX'
        elif contract.endswith('X'):
            df.at[idx, 'contract_norm'] = contract[:-1]
            df.at[idx, 'double_state'] = 'X'
        else:
            df.at[idx, 'contract_norm'] = contract
            df.at[idx, 'double_state'] = ''
    
    # === STEP 4: Initialiser output-kolonner ===
    df['reference_scope'] = None
    df['N_section_played'] = 0
    df['N_club_played'] = 0
    df['reference_n_played'] = 0
    df['field_mode_contract'] = None
    df['field_mode_count'] = None
    df['field_mode_freq'] = None
    df['top2_contract_1'] = None
    df['top2_contract_2'] = None
    df['top2_count_1'] = None
    df['top2_count_2'] = None
    df['Board_Type'] = 'LOW_SAMPLE'
    df['competitive_flag'] = False
    df['expected_pct'] = None
    
    # === STEP 5: Filter kun PLAYED rækker med gyldig pct ===
    played_df = df[(df['result_status_code'] == 'PLAYED') & 
                   (df['pct'].notna())].copy()
    
    if played_df.empty:
        print("⚠️ Phase 2.1: Ingen PLAYED rækker med gyldig pct")
        return df
    
    print(f"✓ Phase 2.1: {len(played_df)} PLAYED rækker fundet")
    
    # === STEP 6: Pre-compute gruppering ===
    # Gruppering per SECTION (i Sprint 1: én gruppe per turnering)
    section_groups = played_df.groupby(['tournament_date', 'board_no', 'section']).size()
    
    # Gruppering per CLUB (samme logik i Sprint 1, men prepared for scale)
    club_groups = played_df.groupby(['tournament_date', 'board_no']).size()
    
    # === STEP 7: Beregn N_section_played og N_club_played ===
    for idx, row in df.iterrows():
        date = row['tournament_date']
        board = row['board_no']
        sec = row['section']
        
        # N_section_played
        section_key = (date, board, sec)
        df.at[idx, 'N_section_played'] = section_groups.get(section_key, 0)
        
        # N_club_played (i Sprint 1 = N_section_played, men struktur er klar for scale)
        club_key = (date, board)
        df.at[idx, 'N_club_played'] = club_groups.get(club_key, 0)
    
    # === STEP 8: Vælg reference_scope ===
    for idx, row in df.iterrows():
        n_section = df.at[idx, 'N_section_played']
        n_club = df.at[idx, 'N_club_played']
        
        if n_section >= n_min:
            df.at[idx, 'reference_scope'] = 'SECTION'
            df.at[idx, 'reference_n_played'] = n_section
        elif n_club >= n_min:
            df.at[idx, 'reference_scope'] = 'CLUB'
            df.at[idx, 'reference_n_played'] = n_club
        else:
            df.at[idx, 'reference_scope'] = 'LOW_SAMPLE'
            df.at[idx, 'reference_n_played'] = n_club
    
    # === STEP 9: MAIN LOOP - Per (tournament_date, board_no, section) ===
    unique_groups = df[['tournament_date', 'board_no', 'section']].drop_duplicates()
    
    print(f"✓ Phase 2.1: Behandler {len(unique_groups)} unikke grupper (turnering+board+sektion)")
    
    for group_idx, (_, group_row) in enumerate(unique_groups.iterrows(), 1):
        date = group_row['tournament_date']
        board = group_row['board_no']
        sec = group_row['section']
        
        # Filtrer rækker for denne gruppe
        group_mask = (df['tournament_date'] == date) & \
                     (df['board_no'] == board) & \
                     (df['section'] == sec)
        group_indices = df[group_mask].index
        
        if len(group_indices) == 0:
            continue
        
        # Hent reference_scope for denne gruppe
        ref_scope = df.at[group_indices[0], 'reference_scope']
        ref_n = df.at[group_indices[0], 'reference_n_played']
        
        # === STEP 9a: Bestem referencegruppe ===
        if ref_scope == 'SECTION':
            # Kun denne sektion
            ref_mask = (played_df['tournament_date'] == date) & \
                       (played_df['board_no'] == board) & \
                       (played_df['section'] == sec)
        else:
            # CLUB eller LOW_SAMPLE: hele klubben samme dag + board
            ref_mask = (played_df['tournament_date'] == date) & \
                       (played_df['board_no'] == board)
        
        ref_group = played_df[ref_mask]
        
        if ref_group.empty:
            continue
        
        # === STEP 9b: Tæl kontrakt-frekvenser ===
        contract_counts = ref_group['contract_norm'].value_counts().to_dict()
        
        if not contract_counts:
            continue
        
        # Sorter efter hyppighed (faldende)
        sorted_contracts = sorted(contract_counts.items(), key=lambda x: x[1], reverse=True)
        
        # === STEP 9c: Gem top 2 kontrakter ===
        top1_contract, top1_count = sorted_contracts[0]
        top1_freq = top1_count / ref_n if ref_n > 0 else 0.0
        
        top2_contract = sorted_contracts[1][0] if len(sorted_contracts) > 1 else None
        top2_count = sorted_contracts[1][1] if len(sorted_contracts) > 1 else None
        
        # === STEP 9d: Klassificér Board_Type ===
        if ref_scope == 'LOW_SAMPLE':
            board_type = 'LOW_SAMPLE'
        else:
            p1 = top1_count / ref_n if ref_n > 0 else 0.0
            p2 = (top2_count / ref_n) if (top2_count is not None and ref_n > 0) else 0.0
            
            if p1 >= 0.70:
                board_type = 'Dominant'
            elif (p1 + p2) >= 0.80 and p2 >= 0.25:
                board_type = 'Split'
            else:
                board_type = 'Wild'
        
        # === STEP 9e: Beregn expected_pct ===
        if top1_count >= 3:
            # Brug mode-kontrakt
            mode_mask = ref_mask & (played_df['contract_norm'] == top1_contract)
            mode_pcts = played_df[mode_mask]['pct']
            expected_pct_val = mode_pcts.mean() if len(mode_pcts) > 0 else None
        else:
            # Fallback til hele referencegruppen
            expected_pct_val = ref_group['pct'].mean() if len(ref_group) > 0 else None
        
        # === STEP 9f: Gem alle værdier tilbage i gruppe-rækker ===
        for idx in group_indices:
            df.at[idx, 'field_mode_contract'] = top1_contract
            df.at[idx, 'field_mode_count'] = top1_count
            df.at[idx, 'field_mode_freq'] = top1_freq
            df.at[idx, 'top2_contract_1'] = top1_contract
            df.at[idx, 'top2_count_1'] = top1_count
            df.at[idx, 'top2_contract_2'] = top2_contract
            df.at[idx, 'top2_count_2'] = top2_count
            df.at[idx, 'Board_Type'] = board_type
            df.at[idx, 'expected_pct'] = expected_pct_val
        
        if group_idx % 50 == 0:
            print(f"  ... behandlet {group_idx}/{len(unique_groups)} grupper")
    
    # === STEP 10: Beregn competitive_flag ===
    df['competitive_flag'] = df['Board_Type'] == 'Split'
    
    # === STEP 11: Statistik ===
    board_type_counts = df['Board_Type'].value_counts().to_dict()
    print(f"\n✓ Phase 2.1 færdig:")
    print(f"  Dominant boards: {board_type_counts.get('Dominant', 0)}")
    print(f"  Split boards (competitive): {board_type_counts.get('Split', 0)}")
    print(f"  Wild boards: {board_type_counts.get('Wild', 0)}")
    print(f"  LOW_SAMPLE boards: {board_type_counts.get('LOW_SAMPLE', 0)}")
    
    return df