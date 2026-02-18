import pandas as pd
import numpy as np
from typing import Tuple, Optional


def add_phase21_fields(df: pd.DataFrame, n_min: int = 12) -> pd.DataFrame:
    """
    Berigelse af DataFrame med Phase 2.1 reference-lag.
    
    Tilføjer stabil reference-logik, board-klassifikation, og expected_pct
    til support Board Review-analyse.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Input-DataFrame med kolonnerne:
        - tournament_date (str, YYYY-MM-DD)
        - board_no (int)
        - section (str)
        - contract (str, fx "4♥", "3NT", "4♥X")
        - result_status_code (str: "PLAYED", "SITOUT", "NOT_PLAYED_AVERAGE")
        - pct (float, 0-100)
    
    n_min : int
        Minimum antal "PLAYED" resultater for at vælge SECTION/CLUB.
        Default: 12
    
    Returns:
    --------
    pd.DataFrame
        Original DataFrame + nye kolonner:
        - reference_scope (str)
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
        - Board_Type (str)
        - competitive_flag (bool)
        - expected_pct (float or None)
        - contract_norm (str)
        - double_state (str)
    """
    
    # === STEP 1: Input-validering ===
    if df.empty:
        return df
    
    required_cols = ['tournament_date', 'board_no', 'section', 'contract', 
                     'result_status_code', 'pct']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Manglende kolonner: {missing}")
    
    # Kopiér DataFrame
    df = df.copy()
    
    # === STEP 2: Normaliser kontrakter ===
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
    
    # === STEP 3: Initialiser output-kolonner ===
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
    
    # === STEP 4: Filter kun "PLAYED" rækker ===
    played_df = df[(df['result_status_code'] == 'PLAYED') & 
                   (pd.to_numeric(df['pct'], errors='coerce').notna())].copy()
    
    if played_df.empty:
        return df
    
    # === STEP 5: Pre-compute gruppering ===
    # Gruppering per SECTION
    section_groups = played_df.groupby(['tournament_date', 'board_no', 'section']).size()
    
    # Gruppering per CLUB (hele klubben, samme dato + board)
    club_groups = played_df.groupby(['tournament_date', 'board_no']).size()
    
    # === STEP 6: Beregn N_section_played og N_club_played for alle rækker ===
    for idx, row in df.iterrows():
        date = row['tournament_date']
        board = row['board_no']
        sec = row['section']
        
        # N_section_played
        section_key = (date, board, sec)
        df.at[idx, 'N_section_played'] = section_groups.get(section_key, 0)
        
        # N_club_played
        club_key = (date, board)
        df.at[idx, 'N_club_played'] = club_groups.get(club_key, 0)
    
    # === STEP 7: Vælg reference_scope for hver gruppe ===
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
    
    # === STEP 8: MAIN LOOP - Per (tournament_date, board_no, section) ===
    unique_groups = df[['tournament_date', 'board_no', 'section']].drop_duplicates()
    
    for _, group_row in unique_groups.iterrows():
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
        
        # === STEP 8a: Bestem referencegruppe ===
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
        
        # === STEP 8b: Tæl kontrakt-frekvenser ===
        contract_counts = ref_group['contract_norm'].value_counts().to_dict()
        
        if not contract_counts:
            continue
        
        # Sorter efter hyppighed (faldende)
        sorted_contracts = sorted(contract_counts.items(), key=lambda x: x[1], reverse=True)
        
        # === STEP 8c: Gem top 2 kontrakter ===
        top1_contract, top1_count = sorted_contracts[0]
        top1_freq = top1_count / ref_n if ref_n > 0 else 0.0
        
        top2_contract = sorted_contracts[1][0] if len(sorted_contracts) > 1 else None
        top2_count = sorted_contracts[1][1] if len(sorted_contracts) > 1 else None
        
        # === STEP 8d: Klassificér Board_Type ===
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
        
        # === STEP 8e: Beregn expected_pct ===
        if top1_count >= 3:
            # Brug mode-kontrakt
            mode_mask = ref_mask & (played_df['contract_norm'] == top1_contract)
            mode_pcts = played_df[mode_mask]['pct']
            expected_pct_val = mode_pcts.mean() if len(mode_pcts) > 0 else None
        else:
            # Fallback til hele referencegruppen
            expected_pct_val = ref_group['pct'].mean() if len(ref_group) > 0 else None
        
        # === STEP 8f: Gem alle værdier tilbage i gruppe-rækker ===
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
    
    # === STEP 9: Beregn competitive_flag ===
    df['competitive_flag'] = df['Board_Type'] == 'Split'
    
    return df


# === TEST-EKSEMPLER (til validering) ===

if __name__ == "__main__":
    
    # Test 1: SECTION valg (N >= 12)
    print("=" * 60)
    print("TEST 1: SECTION valg")
    print("=" * 60)
    
    test1_data = {
        'tournament_date': ['2026-02-14'] * 14,
        'board_no': [1] * 14,
        'section': ['A'] * 14,
        'contract': ['4♥'] * 14,
        'result_status_code': ['PLAYED'] * 14,
        'pct': [50.0, 52.0, 48.0, 55.0, 51.0, 49.0, 54.0, 50.0, 53.0, 47.0, 51.0, 50.0, 52.0, 49.0]
    }
    df_test1 = pd.DataFrame(test1_data)
    result1 = add_phase21_fields(df_test1)
    
    print(f"reference_scope: {result1['reference_scope'].iloc[0]}")
    print(f"N_section_played: {result1['N_section_played'].iloc[0]}")
    print(f"Board_Type: {result1['Board_Type'].iloc[0]}")
    print(f"field_mode_contract: {result1['field_mode_contract'].iloc[0]}")
    print(f"field_mode_freq: {result1['field_mode_freq'].iloc[0]:.2f}")
    print()
    
    # Test 2: CLUB fallback
    print("=" * 60)
    print("TEST 2: CLUB fallback (SECTION < 12, CLUB >= 12)")
    print("=" * 60)
    
    test2_data = {
        'tournament_date': ['2026-02-14'] * 13,
        'board_no': [1] * 13,
        'section': ['A'] * 5 + ['B'] * 8,
        'contract': ['4♥'] * 10 + ['3NT'] * 3,
        'result_status_code': ['PLAYED'] * 13,
        'pct': [50.0] * 10 + [45.0, 48.0, 42.0]
    }
    df_test2 = pd.DataFrame(test2_data)
    result2 = add_phase21_fields(df_test2)
    
    print(f"Sektion A, board 1:")
    print(f"  reference_scope: {result2[result2['section'] == 'A']['reference_scope'].iloc[0]}")
    print(f"  N_section_played: {result2[result2['section'] == 'A']['N_section_played'].iloc[0]}")
    print(f"  N_club_played: {result2[result2['section'] == 'A']['N_club_played'].iloc[0]}")
    print(f"  Board_Type: {result2[result2['section'] == 'A']['Board_Type'].iloc[0]}")
    print()
    
    # Test 3: Split board
    print("=" * 60)
    print("TEST 3: Split board")
    print("=" * 60)
    
    test3_data = {
        'tournament_date': ['2026-02-14'] * 20,
        'board_no': [2] * 20,
        'section': ['A'] * 20,
        'contract': ['4♥'] * 9 + ['3NT'] * 8 + ['5♣'] * 2 + ['6NT'] * 1,
        'result_status_code': ['PLAYED'] * 20,
        'pct': [50.0] * 9 + [48.0] * 8 + [42.0] * 2 + [45.0]
    }
    df_test3 = pd.DataFrame(test3_data)
    result3 = add_phase21_fields(df_test3)
    
    print(f"field_mode_contract: {result3['field_mode_contract'].iloc[0]}")
    print(f"field_mode_count: {result3['field_mode_count'].iloc[0]}")
    print(f"top2_contract_2: {result3['top2_contract_2'].iloc[0]}")
    print(f"top2_count_2: {result3['top2_count_2'].iloc[0]}")
    print(f"Board_Type: {result3['Board_Type'].iloc[0]}")
    print(f"competitive_flag: {result3['competitive_flag'].iloc[0]}")
    print()
    
    # Test 4: LOW_SAMPLE
    print("=" * 60)
    print("TEST 4: LOW_SAMPLE (< 12)")
    print("=" * 60)
    
    test4_data = {
        'tournament_date': ['2026-02-14'] * 7,
        'board_no': [3] * 7,
        'section': ['A'] * 7,
        'contract': ['4♥', '4♥', '4♥', '4♥', '3NT', '3NT', '5♣'],
        'result_status_code': ['PLAYED'] * 7,
        'pct': [50.0, 52.0, 48.0, 55.0, 45.0, 48.0, 40.0]
    }
    df_test4 = pd.DataFrame(test4_data)
    result4 = add_phase21_fields(df_test4)
    
    print(f"reference_scope: {result4['reference_scope'].iloc[0]}")
    print(f"Board_Type: {result4['Board_Type'].iloc[0]}")
    print(f"N_section_played: {result4['N_section_played'].iloc[0]}")
    print()
    
    print("✅ Alle tests kørte!")