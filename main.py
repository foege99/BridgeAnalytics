from datetime import datetime, timedelta
import pandas as pd

from bridge.crawler import get_recent_tournaments
from bridge.scraper import scrape_spilresultater

from bridge.features import add_hand_features

from bridge.analysis import (
    add_roles_and_pct,
    make_role_summary,
    make_tournament_summary,
    make_declarer_list,
    make_evening_role_matrix,
    make_quarterly_summary_with_ci,
    make_pair_field_report,
    make_pair_declarer_report,
)

# ✅ IMPORT PHASE 2.1 REFERENCE-LAG
from bridge.phase21_reference import add_phase21_fields

# ✅ IMPORT BOARD REVIEW
from bridge.board_review import (
    make_board_review_all_hands,
    make_board_review_summary,
    board_review_statistics,
    print_board_review_stats,
)

# ✅ IMPORT DECLARER ANALYSIS
from bridge.declarer_analysis import (
    make_declarer_analysis,
    make_declarer_risk_report,
    print_declarer_analysis_highlights,
)

HENRIK = "Henrik Friis"
PER = "Per Føge Jensen"

# ✅ CUTOFF: 7 dage tilbage
CUTOFF_DATE = datetime.now() - timedelta(days=7)

# Use unique filename to avoid Windows file-lock issues
OUTPUT_FILE = f"Henrik_Per_ANALYSE_{datetime.now():%Y%m%d_%H%M}.xlsx"


def main():
    print("Starter crawler + scraper + analyse...")
    print("Cutoff:", CUTOFF_DATE.date())

    # ✅ NY CRAWLER: Returner list of tournaments med sections
    tournaments = get_recent_tournaments(CUTOFF_DATE)
    
    if not tournaments:
        print("Ingen turneringer fundet indenfor cutoff.")
        return

    print(f"Antal turneringer fundet: {len(tournaments)}")

    all_rows = []
    tournaments_processed = 0

    for t_idx, tournament in enumerate(tournaments, 1):
        tournament_id = tournament['tournament_id']
        tdate = tournament['date']
        sections = tournament['sections']
        
        print(f"\n({t_idx}/{len(tournaments)}) {tdate.date()} – Turnering {tournament_id}")
        print(f"  Sections fundet: {', '.join([s['name'] for s in sections])}")

        # ✅ SCRAPE ALLE SECTIONS (A, B, C, D...)
        for section in sections:
            section_name = section['name']
            section_url = section['spilresultater_url']
            
            print(f"  → Scraper section {section_name}: {section_url}")
            
            try:
                rows = scrape_spilresultater(
                    section_url,
                    tdate,
                    include_hands=True,
                    debug_hands=False,
                )
                
                # ✅ TILFØJ SECTION KOLONNE (noter: 'row' kommer allerede fra scraper!)
                for row in rows:
                    row['section'] = section_name
                
                print(f"      ✓ {len(rows)} rækker")
                all_rows.extend(rows)
                
            except Exception as e:
                print(f"      !!! Fejl ved scraping: {e}")

        tournaments_processed += 1
        
        # ✅ EARLY EXIT: Hvis CUTOFF <= 7 dage, stop efter 1-2 turneringer
        if (CUTOFF_DATE.date() >= (datetime.now() - timedelta(days=7)).date()) and tournaments_processed >= 2:
            print(f"\n⏸ CUTOFF <= 7 dage – stopper efter {tournaments_processed} turneringer")
            break

    if not all_rows:
        print("Ingen data fundet.")
        return

    df_all = pd.DataFrame(all_rows)

    print(f"\n✓ I alt {len(df_all)} rækker fra {tournaments_processed} turneringer")
    print(f"  Sections: {df_all['section'].unique().tolist()}")

    print("\nTilføjer hånd-features...")
    df_all = add_hand_features(df_all)

    # ✅ TILFØJ PHASE 2.1 REFERENCE-LAG (bruger ALLE sections som reference)
    print("Tilføjer Phase 2.1 reference-lag (fra alle sections A+B+C+D...)...")
    df_all = add_phase21_fields(df_all, n_min=12)
    print("  ✓ Phase 2.1 felt-data beregnet")
    print(f"    - Board Types fundet: {df_all['Board_Type'].value_counts().to_dict()}")
    print(f"    - Split boards (competitive): {df_all['competitive_flag'].sum()}")

    # ✅ BOARD REVIEW ANALYSE (kun A-rækken)
    print("\nGenererer Board Review rapporter (kun A-rækken)...")
    df_a_only = df_all[df_all['section'] == 'A'].copy()
    
    if len(df_a_only) == 0:
        print("Ingen data fra A-rækken!")
        return
    
    df_board_review_all = make_board_review_all_hands(df_a_only)
    df_board_review_summary = make_board_review_summary(df_a_only)
    
    # Statistik
    review_stats = board_review_statistics(df_board_review_all, df_board_review_summary)
    print(f"  ✓ Board Review: {len(df_board_review_all)} boards med hand-records")
    print_board_review_stats(review_stats)

    # ✅ DECLARER ANALYSIS (kun A-rækken)
    print("\nGenererer Declarer Analysis...")
    df_pair = df_a_only[
        df_a_only.apply(
            lambda r: (HENRIK in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]) and
                      (PER in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]),
            axis=1
        )
    ].copy()

    if len(df_pair) == 0:
        print("  (Ingen boards hvor Henrik og Per spiller sammen i A-rækken)")
        df_declarer_analysis = pd.DataFrame()
    else:
        # Tilføj roller + pct
        df_pair = add_roles_and_pct(df_pair, henrik=HENRIK, per=PER)
        
        # Lav Declarer Analysis
        df_declarer_analysis = make_declarer_analysis(df_pair, henrik=HENRIK, per=PER)
        
        print(f"  ✓ Declarer Analysis: {len(df_declarer_analysis)} boards")
        
        # Print highlights
        print_declarer_analysis_highlights(df_declarer_analysis, top_n=5)

    # ✅ KLASSISKE RAPPORTER (fra hele A-rækken, ikke kun hvor de spiller sammen)
    print("\nGenererer klassiske rapporter...")
    
    # Filter til kun boards hvor de spiller sammen
    df_pair_all = df_a_only[
        df_a_only.apply(
            lambda r: (HENRIK in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]) and
                      (PER in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]),
            axis=1
        )
    ].copy()
    
    if len(df_pair_all) > 0:
        df_pair_all = add_roles_and_pct(df_pair_all, henrik=HENRIK, per=PER)
        
        df_declarer = make_declarer_list(df_pair_all)
        df_summary = make_role_summary(df_pair_all)
        df_tournament = make_tournament_summary(df_pair_all)
        df_evening_matrix = make_evening_role_matrix(df_pair_all)
        df_quarterly = make_quarterly_summary_with_ci(df_pair_all)
        
        print(f"  ✓ Klassiske rapporter genereret")
    else:
        df_declarer = pd.DataFrame()
        df_summary = pd.DataFrame()
        df_tournament = pd.DataFrame()
        df_evening_matrix = pd.DataFrame()
        df_quarterly = pd.DataFrame()
        print("  (Ingen data til klassiske rapporter)")

    # ✅ FIELD REPORTS (alle par, fra hele feltet)
    print("\nGenererer Field Reports...")
    df_field_defense = make_pair_field_report(df_all, min_boards=50)
    df_field_declarer = make_pair_declarer_report(df_all, min_boards=50)
    print(f"  ✓ Field Reports: {len(df_field_defense)} par i defense, {len(df_field_declarer)} par i declarer")

    # ✅ SKRIV EXCEL
    print(f"\nSkriver Excel: {OUTPUT_FILE}")
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        # Board Review
        df_board_review_all.to_excel(writer, sheet_name='Board_Review_All', index=False)
        df_board_review_summary.to_excel(writer, sheet_name='Board_Review_Summary', index=False)
        
        # Declarer Analysis
        if not df_declarer_analysis.empty:
            df_declarer_analysis.to_excel(writer, sheet_name='Declarer_Analysis', index=False)
        
        # Klassiske rapporter
        if not df_declarer.empty:
            df_declarer.to_excel(writer, sheet_name='Declarer_List', index=False)
        if not df_summary.empty:
            df_summary.to_excel(writer, sheet_name='Role_Summary', index=False)
        if not df_tournament.empty:
            df_tournament.to_excel(writer, sheet_name='Tournament_Summary', index=False)
        if not df_evening_matrix.empty:
            df_evening_matrix.to_excel(writer, sheet_name='Evening_Matrix', index=False)
        if not df_quarterly.empty:
            df_quarterly.to_excel(writer, sheet_name='Quarterly_Summary', index=False)
        
        # Field Reports
        if not df_field_defense.empty:
            df_field_defense.to_excel(writer, sheet_name='Field_Defense', index=False)
        if not df_field_declarer.empty:
            df_field_declarer.to_excel(writer, sheet_name='Field_Declarer', index=False)
    
    print(f"✅ Analyse færdig! Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()