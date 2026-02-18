import pandas as pd
import numpy as np


def make_declarer_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Declarer Analysis rapport: Identificer melde-systemfejl
    
    Viser for hver board:
    - Hvem blev declarer hos jer
    - Hvem blev declarer hos fleste andre
    - Udspillet hos jer vs typisk udspil
    - Risiko-vurdering
    
    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame med Phase 2.1 + følgende kolonner:
        - board_no
        - contract_norm
        - decl (N/S/Ø/V)
        - lead (♥5 format)
        - Declarer_Side (NS/ØV)
        - pct_NS
        - expected_pct
    
    Returns:
    --------
    pd.DataFrame
        Declarer analyse per board
    """
    
    if df.empty:
        return df
    
    # Grupper per board
    grouped = df.groupby(['tournament_date', 'board_no']).agg({
        'contract_norm': 'first',
        'pct_NS': 'mean',
        'expected_pct': 'first',
        'Board_Type': 'first',
        'competitive_flag': 'first',
        'N_section_played': 'first',
    }).reset_index()
    
    # Beregn performance
    grouped['pct_vs_expected'] = grouped['pct_NS'] - grouped['expected_pct']
    
    # For hver board: hvem var declarer?
    declarer_analysis = []
    
    for (date, board), group in df.groupby(['tournament_date', 'board_no']):
        # Din declarer og lead
        your_decl = group['decl'].iloc[0] if len(group) > 0 else None
        your_lead = group['lead'].iloc[0] if len(group) > 0 else None
        your_side = group['Declarer_Side'].iloc[0] if len(group) > 0 else None
        
        # Fleste andre: hvem var declarer?
        declarer_counts = group['decl'].value_counts()
        field_decl = declarer_counts.index[0] if len(declarer_counts) > 0 else None
        field_decl_count = declarer_counts.iloc[0] if len(declarer_counts) > 0 else 0
        field_decl_pct = (field_decl_count / len(group) * 100) if len(group) > 0 else 0
        
        # Typisk lead
        lead_counts = group['lead'].value_counts()
        field_lead = lead_counts.index[0] if len(lead_counts) > 0 else None
        field_lead_count = lead_counts.iloc[0] if len(lead_counts) > 0 else 0
        field_lead_pct = (field_lead_count / len(group) * 100) if len(group) > 0 else 0
        
        # Performance
        your_pct = group['pct_NS'].mean()
        expected_pct = group['expected_pct'].iloc[0]
        performance = your_pct - expected_pct
        
        # Declarer-mismatch?
        declarer_mismatch = (your_decl != field_decl)
        
        # Hvad er risikoen ved at skifte declarer?
        # Hvis du havde anden declarer, fik du andet udspil
        lead_mismatch = (your_lead != field_lead)
        
        declarer_analysis.append({
            'tournament_date': date,
            'board_no': board,
            'contract': group['contract_norm'].iloc[0],
            'your_declarer': your_decl,
            'your_side': your_side,
            'your_lead': your_lead,
            'field_declarer': field_decl,
            'field_declarer_count': field_decl_count,
            'field_declarer_pct': field_decl_pct,
            'field_lead': field_lead,
            'field_lead_count': field_lead_count,
            'field_lead_pct': field_lead_pct,
            'your_pct': your_pct,
            'expected_pct': expected_pct,
            'performance': performance,
            'declarer_mismatch': declarer_mismatch,
            'lead_mismatch': lead_mismatch,
            'num_hands': len(group),
            'Board_Type': group['Board_Type'].iloc[0],
            'competitive_flag': group['competitive_flag'].iloc[0],
        })
    
    report = pd.DataFrame(declarer_analysis)
    
    # Sorter efter declarer_mismatch + performance
    report = report.sort_values(
        ['declarer_mismatch', 'performance'],
        ascending=[False, True],  # Mismatch først, så worst performance
        na_position='last'
    )
    
    print(f"✓ Declarer Analysis: {len(report)} boards")
    print(f"  Boards med declarer-mismatch: {report['declarer_mismatch'].sum()}")
    print(f"  Boards med lead-mismatch: {report['lead_mismatch'].sum()}")
    print(f"  Boards med begge mismatches: {(report['declarer_mismatch'] & report['lead_mismatch']).sum()}")
    
    return report


def make_declarer_risk_report(df_declarer: pd.DataFrame) -> pd.DataFrame:
    """
    Filtrer til højeste risiko-boards: declarer-mismatch + dårlig performance
    
    Parameters:
    -----------
    df_declarer : pd.DataFrame
        Output fra make_declarer_analysis()
    
    Returns:
    --------
    pd.DataFrame
        Høj-risiko boards sorteret efter performance
    """
    
    if df_declarer.empty:
        return df_declarer
    
    # Høj risiko: declarer-mismatch OG performance < -5%
    high_risk = df_declarer[
        (df_declarer['declarer_mismatch']) & 
        (df_declarer['performance'] < -5)
    ].copy()
    
    high_risk = high_risk.sort_values('performance', ascending=True)
    
    print(f"\n✓ Høj-risiko boards (declarer-mismatch + performance < -5%): {len(high_risk)}")
    
    return high_risk


def print_declarer_analysis_highlights(df_declarer: pd.DataFrame, top_n: int = 5) -> None:
    """
    Print vigtigste findings fra declarer analyse.
    
    Parameters:
    -----------
    df_declarer : pd.DataFrame
        Output fra make_declarer_analysis()
    
    top_n : int
        Antal top-boards at vise
    """
    
    print("\n" + "="*80)
    print("DECLARER ANALYSIS – HØJTLIGTER")
    print("="*80)
    
    # Top N worst performance på declarer-mismatch boards
    mismatch_boards = df_declarer[df_declarer['declarer_mismatch']].copy()
    
    if not mismatch_boards.empty:
        print(f"\nTOP {top_n} WORST PERFORMANCE (declarer-mismatch):")
        print("-"*80)
        
        for idx, (_, row) in enumerate(mismatch_boards.head(top_n).iterrows(), 1):
            print(f"\n{idx}. {row['tournament_date']} – Board {row['board_no']}")
            print(f"   Kontrakt: {row['contract']}")
            print(f"   Din declarer: {row['your_declarer']} ({row['your_side']})")
            print(f"   Felt declarer: {row['field_declarer']} ({row['field_declarer_pct']:.0f}%)")
            print(f"   Dit udspil: {row['your_lead']}")
            print(f"   Felt udspil: {row['field_lead']} ({row['field_lead_pct']:.0f}%)")
            print(f"   Performance: {row['performance']:+.1f}% (du: {row['your_pct']:.1f}% vs expected: {row['expected_pct']:.1f}%)")
            
            if row['lead_mismatch']:
                print(f"   ⚠️  UDSPIL-MISMATCH! Andet udspil pga. anden declarer")
            else:
                print(f"   ℹ️  Samme udspil, men forkert declarer påvirkede spillet")
    
    # Boards uden mismatch men dårlig performance
    no_mismatch_bad = df_declarer[
        (~df_declarer['declarer_mismatch']) & 
        (df_declarer['performance'] < -5)
    ].sort_values('performance')
    
    if not no_mismatch_bad.empty:
        print(f"\n\nBOARDS UDEN DECLARER-MISMATCH MEN DÅRLIG PERFORMANCE (< -5%):")
        print("-"*80)
        
        for idx, (_, row) in enumerate(no_mismatch_bad.head(3).iterrows(), 1):
            print(f"\n{idx}. {row['tournament_date']} – Board {row['board_no']}")
            print(f"   Kontrakt: {row['contract']}")
            print(f"   Declarer: {row['your_declarer']} (samme som felt)")
            print(f"   Performance: {row['performance']:+.1f}%")
            print(f"   → Spil-problem, ikke melding-problem")
    
    print("\n" + "="*80)