import pandas as pd
import numpy as np
from datetime import datetime

# ✅ ROLLE-TABEL: Hvis declarer er position X, så er:
DECLARER_ROLES = {
    'N': {'dummy': 'S', 'leader': 'Ø', 'defender': 'V'},
    'S': {'dummy': 'N', 'leader': 'V', 'defender': 'Ø'},
    'Ø': {'dummy': 'V', 'leader': 'S', 'defender': 'N'},
    'V': {'dummy': 'Ø', 'leader': 'N', 'defender': 'S'},
}

def get_side(position):
    """Returner NS eller ØV baseret på position"""
    return 'NS' if position in ['N', 'S'] else 'ØV'

def find_position(row, player_name):
    """Find hvilken position en spiller sidder (N/S/Ø/V)"""
    if row.get('ns1') == player_name:
        return 'N'
    elif row.get('ns2') == player_name:
        return 'S'
    elif row.get('ew1') == player_name:
        return 'Ø'
    elif row.get('ew2') == player_name:
        return 'V'
    return None

def assign_roles(row, henrik, per):
    """
    Bestem roller for Henrik og Per baseret på declarer + deres positioner
    
    Returns: dict med henrik_role, per_role, is_henrik_leader, is_per_leader
    """
    declarer_pos = row.get('decl')
    if not declarer_pos:
        return {
            'henrik_position': None,
            'per_position': None,
            'henrik_role': None,
            'per_role': None,
            'is_henrik_leader': False,
            'is_per_leader': False,
        }
    
    # Find deres positioner
    henrik_pos = find_position(row, henrik)
    per_pos = find_position(row, per)
    
    # Hent rolle-info fra tabel
    roles_info = DECLARER_ROLES[declarer_pos]
    dummy_pos = roles_info['dummy']
    leader_pos = roles_info['leader']
    defender_pos = roles_info['defender']
    
    # Assign Henrik's rolle
    if henrik_pos == declarer_pos:
        henrik_role = 'Declarer'
    elif henrik_pos == dummy_pos:
        henrik_role = 'Dummy'
    elif henrik_pos == leader_pos:
        henrik_role = 'Leader'
    elif henrik_pos == defender_pos:
        henrik_role = 'Defender'
    else:
        henrik_role = None
    
    # Assign Per's rolle
    if per_pos == declarer_pos:
        per_role = 'Declarer'
    elif per_pos == dummy_pos:
        per_role = 'Dummy'
    elif per_pos == leader_pos:
        per_role = 'Leader'
    elif per_pos == defender_pos:
        per_role = 'Defender'
    else:
        per_role = None
    
    return {
        'henrik_position': henrik_pos,
        'per_position': per_pos,
        'henrik_role': henrik_role,
        'per_role': per_role,
        'is_henrik_leader': (henrik_pos == leader_pos),
        'is_per_leader': (per_pos == leader_pos),
    }

def make_declarer_analysis(df_a_only, henrik="Henrik Friis", per="Per Føge Jensen"):
    """
    Lav detaljeret Declarer Analysis for Henrik+Per
    
    Kolonner:
    - tournament_date, board_no, row (A/B/C), contract
    - henrik_position, per_position
    - henrik_role, per_role (Declarer/Dummy/Leader/Defender)
    - your_contract_side, field_contract_side
    - contract_side_mismatch
    - is_henrik_leader, is_per_leader
    - your_lead
    - declarer_mismatch
    - performance
    """
    
    rows = []
    
    for _, row in df_a_only.iterrows():
        # Assign roller
        role_info = assign_roles(row, henrik, per)
        
        # Kontrakt info
        contract = row.get('contract', '')
        
        # Row letter (A, B, C fra 'row' kolonne eller default A)
        row_letter = row.get('row', 'A')
        
        # Din side (Henrik+Per's side baseret på deres positioner)
        henrik_pos = role_info['henrik_position']
        per_pos = role_info['per_position']
        
        # Bestem din side baseret på hvem der var declarer blandt jer
        your_contract_side = None
        if role_info['henrik_role'] == 'Declarer':
            your_contract_side = get_side(henrik_pos)
        elif role_info['per_role'] == 'Declarer':
            your_contract_side = get_side(per_pos)
        elif role_info['henrik_role'] in ['Dummy', 'Leader', 'Defender']:
            your_contract_side = get_side(henrik_pos)
        elif role_info['per_role'] in ['Dummy', 'Leader', 'Defender']:
            your_contract_side = get_side(per_pos)
        
        # Felt's side (baseret på feltet's declarer)
        declarer_pos = row.get('decl')
        field_contract_side = get_side(declarer_pos) if declarer_pos else None
        
        # Contract side mismatch
        contract_side_mismatch = (your_contract_side != field_contract_side) if your_contract_side and field_contract_side else None
        
        # Lead (kun relevant hvis en af dem er leader)
        your_lead = None
        if role_info['is_henrik_leader'] or role_info['is_per_leader']:
            your_lead = row.get('lead')
        
        # Declarer mismatch
        declarer_in_field = row.get('decl')
        declarer_in_your_play = None
        
        # Find hvem var declarer i jeres spil
        if role_info['henrik_role'] == 'Declarer':
            declarer_in_your_play = role_info['henrik_position']
        elif role_info['per_role'] == 'Declarer':
            declarer_in_your_play = role_info['per_position']
        
        declarer_mismatch = (declarer_in_your_play != declarer_in_field) if declarer_in_your_play and declarer_in_field else None
        
        # Performance
        performance = row.get('pct', None)
        
        # Board Type (fra Phase 2.1)
        board_type = row.get('Board_Type', '')
        competitive = row.get('competitive_flag', False)
        
        rows.append({
            'tournament_date': row.get('tournament_date'),
            'board_no': row.get('board_no'),
            'row': row_letter,
            'contract': contract,
            'henrik_position': role_info['henrik_position'],
            'per_position': role_info['per_position'],
            'henrik_role': role_info['henrik_role'],
            'per_role': role_info['per_role'],
            'your_contract_side': your_contract_side,
            'field_contract_side': field_contract_side,
            'contract_side_mismatch': contract_side_mismatch,
            'is_henrik_leader': role_info['is_henrik_leader'],
            'is_per_leader': role_info['is_per_leader'],
            'your_lead': your_lead,
            'declarer_mismatch': declarer_mismatch,
            'performance': performance,
            'board_type': board_type,
            'competitive': competitive,
        })
    
    df = pd.DataFrame(rows)
    return df

def make_declarer_risk_report(df_declarer_analysis):
    """
    Lag risiko-rapport: Boards med declarer-mismatch OG dårlig performance
    """
    # Høj-risiko: declarer_mismatch=True og performance < -5%
    high_risk = df_declarer_analysis[
        (df_declarer_analysis['declarer_mismatch'] == True) &
        (df_declarer_analysis['performance'] < -5)
    ].copy()
    
    if high_risk.empty:
        return pd.DataFrame()
    
    high_risk = high_risk.sort_values('performance', ascending=True)
    return high_risk

def print_declarer_analysis_highlights(df_declarer_analysis, top_n=5):
    """
    Print highlights fra Declarer Analysis
    """
    print("\n" + "="*80)
    print("DECLARER ANALYSIS – HIGHLIGHTS")
    print("="*80)
    
    # Boards med declarer mismatch
    declarer_mismatch = df_declarer_analysis[
        df_declarer_analysis['declarer_mismatch'] == True
    ]
    
    print(f"\nBoards med declarer-mismatch: {len(declarer_mismatch)}")
    
    if len(declarer_mismatch) > 0:
        worst = declarer_mismatch.nsmallest(top_n, 'performance')
        print(f"\nTOP {top_n} WORST (declarer-mismatch):")
        print("-" * 80)
        
        for idx, (_, row) in enumerate(worst.iterrows(), 1):
            print(f"\n{idx}. {row['tournament_date'].date()} – Board {row['board_no']} (Row {row['row']})")
            print(f"   Kontrakt: {row['contract']}")
            print(f"   Henrik: {row['henrik_role']} ({row['henrik_position']})")
            print(f"   Per: {row['per_role']} ({row['per_position']})")
            print(f"   Din side: {row['your_contract_side']}, Felt: {row['field_contract_side']}")
            print(f"   Performance: {row['performance']:.1f}%")
            
            if row['is_henrik_leader']:
                print(f"   Henrik var Leader, spillede: {row['your_lead']}")
            if row['is_per_leader']:
                print(f"   Per var Leader, spillede: {row['your_lead']}")
            
            if row['contract_side_mismatch']:
                print(f"   ⚠️  CONTRACT-SIDE MISMATCH!")
    
    # Boards uden mismatch men dårlig performance
    no_mismatch_bad = df_declarer_analysis[
        (df_declarer_analysis['declarer_mismatch'] != True) &
        (df_declarer_analysis['performance'] < -5)
    ]
    
    if len(no_mismatch_bad) > 0:
        print(f"\n\nBoards uden mismatch men dårlig performance (< -5%):")
        print("-" * 80)
        worst_no_mismatch = no_mismatch_bad.nsmallest(top_n, 'performance')
        
        for idx, (_, row) in enumerate(worst_no_mismatch.iterrows(), 1):
            print(f"\n{idx}. {row['tournament_date'].date()} – Board {row['board_no']} (Row {row['row']})")
            print(f"   Kontrakt: {row['contract']}")
            print(f"   Henrik: {row['henrik_role']} ({row['henrik_position']})")
            print(f"   Per: {row['per_role']} ({row['per_position']})")
            print(f"   Performance: {row['performance']:.1f}% (spil-problem)")
    
    print("\n" + "="*80)