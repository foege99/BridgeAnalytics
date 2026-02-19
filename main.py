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

    for t_idx, tournament in enumerate(tournaments, 1):
        tournament_id = tournament['tournament_id']
        tdate = tournament['date']
        sections = tournament['sections']
        
        print(f"\n({t_idx}/{len(tournaments)}) {tdate.date()} – Turnering {tournament_id}")
        print(f"  Sections fundet: {', '.join([s['name'] for s in sections])}")

        # ✅ SCRAPE ALLE SECTIONS (A, B, C, D...)
        for section in sections:
            section_name = section['name']
            # ✅ VIGTIG ÆNDRING: Brug spilresultater_url i stedet for url
            section_url = section['spilresultater_url']
            
            print(f"  → Scraper section {section_name}: {section_url}")
            
            try:
                rows = scrape_spilresultater(
                    section_url,
                    tdate,
                    include_hands=True,
                    debug_hands=False,
                )
                
                # ✅ TILFØJ SECTION KOLONNE
                for row in rows:
                    row['section'] = section_name
                
                print(f"      ✓ {len(rows)} rækker")
                all_rows.extend(rows)
                
            except Exception as e:
                print(f"      !!! Fejl ved scraping: {e}")

    if not all_rows:
        print("Ingen data fundet.")
        return

    df_all = pd.DataFrame(all_rows)

    print(f"\n✓ I alt {len(df_all)} rækker fra alle sections")
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
    print_board_review_stats(review_stats)

    # ✅ DECLARER ANALYSIS (kun A-rækken)
    print("\nGenererer Declarer Analysis (kun A-rækken)...")
    df_declarer_analysis = make_declarer_analysis(df_a_only)
    
    # ✅ SORTERING: tournament_date + board_no
    df_declarer_analysis = df_declarer_analysis.sort_values(
        ['tournament_date', 'board_no'],
        ascending=[False, True]
    ).reset_index(drop=True)
    
    df_declarer_risk = make_declarer_risk_report(df_declarer_analysis)
    print_declarer_analysis_highlights(df_declarer_analysis, top_n=5)

    # Kun rækker hvor I begge er med (A-rækken)
    df_pair = df_a_only[
        df_a_only.apply(
            lambda r: (HENRIK in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]) and
                      (PER in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]),
            axis=1
        )
    ].copy()

    print(f"\nHenrik+Per sammen i A-rækken: {len(df_pair)} rækker")

    # Roller + pct
    df_pair = add_roles_and_pct(df_pair, henrik=HENRIK, per=PER)

    # Klassiske ark
    df_declarer = make_declarer_list(df_pair)
    df_summary = make_role_summary(df_pair)
    df_tournament = make_tournament_summary(df_pair)

    # Nye ark
    df_evening_matrix = make_evening_role_matrix(df_pair)
    df_quarterly = make_quarterly_summary_with_ci(df_pair)

    # Field data: defence + declarer (alle par, min 50 boards)
    # ✅ Brug hele df_all (A+B+C) som reference!
    df_field_defense = make_pair_field_report(df_all, min_boards=50)
    df_field_declarer = make_pair_declarer_report(df_all, min_boards=50)

    print("\nSkriver Excel-fil...")
    with pd.ExcelWriter(
        OUTPUT_FILE,
        engine="xlsxwriter",
        datetime_format="yyyy-mm-dd",
        date_format="yyyy-mm-dd"
    ) as writer:
        df_all.to_excel(writer, sheet_name="All_Rows_Raw", index=False)
        df_a_only.to_excel(writer, sheet_name="A_Section_Only", index=False)
        df_pair.to_excel(writer, sheet_name="HF_PF_Only", index=False)
        df_declarer.to_excel(writer, sheet_name="Declarer_Games", index=False)
        df_summary.to_excel(writer, sheet_name="Summary", index=False)
        df_tournament.to_excel(writer, sheet_name="Tournament_Summary", index=False)

        df_evening_matrix.to_excel(writer, sheet_name="Evening_Role_Matrix", index=False)
        df_quarterly.to_excel(writer, sheet_name="Quarterly_CI", index=False)

        # ✅ Field data (fra hele datasættet A+B+C)
        df_field_defense.to_excel(writer, sheet_name="Field_Data_Defense", index=False)
        df_field_declarer.to_excel(writer, sheet_name="Field_Data_Declarer", index=False)

        # ✅ Board Review (kun A-rækken)
        df_board_review_all.to_excel(writer, sheet_name="Board_Review_AllHands", index=False)
        df_board_review_summary.to_excel(writer, sheet_name="Board_Review_Summary", index=False)

        # ✅ Declarer Analysis (kun A-rækken, sorteret)
        df_declarer_analysis.to_excel(writer, sheet_name="Declarer_Analysis", index=False)
        if not df_declarer_risk.empty:
            df_declarer_risk.to_excel(writer, sheet_name="Declarer_Risk", index=False)

    print("\n" + "="*60)
    print("ANALYSE FÆRDIG!")
    print("="*60)
    print(f"Total rækker (alle sections):  {len(df_all)}")
    print(f"A-rækken rækker:               {len(df_a_only)}")
    print(f"Henrik+Per sammen i A:         {len(df_pair)}")
    print(f"Excel gemt som:                {OUTPUT_FILE}")
    print("="*60)


if __name__ == "__main__":
    main()