from datetime import datetime, timedelta
import pandas as pd

from bridge.crawler import get_recent_tournaments
from bridge.scraper import to_spilresultater_url, scrape_spilresultater
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

    resultater_date_map = get_recent_tournaments(CUTOFF_DATE)
    if not resultater_date_map:
        print("Ingen turneringer fundet indenfor cutoff.")
        return

    print("Antal turneringer fundet:", len(resultater_date_map))

    all_rows = []

    for i, (res_url, tdate) in enumerate(sorted(resultater_date_map.items(), key=lambda x: x[1]), 1):
        spil_url = to_spilresultater_url(res_url)
        print(f"\n({i}/{len(resultater_date_map)}) {tdate.date()}  Scraper: {spil_url}")

        try:
            rows = scrape_spilresultater(
                spil_url,
                tdate,
                include_hands=True,
                debug_hands=False,
            )
            print("  ... rækker:", len(rows))
            all_rows.extend(rows)
        except Exception as e:
            print("  !!! Fejl ved scraping:", e)

    if not all_rows:
        print("Ingen data fundet.")
        return

    df_all = pd.DataFrame(all_rows)

    print("Tilføjer hånd-features...")
    df_all = add_hand_features(df_all)

    # ✅ TILFØJ PHASE 2.1 REFERENCE-LAG
    print("Tilføjer Phase 2.1 reference-lag...")
    df_all = add_phase21_fields(df_all, n_min=12)
    print("  ✓ Phase 2.1 felt-data beregnet")
    print(f"    - Board Types fundet: {df_all['Board_Type'].value_counts().to_dict()}")
    print(f"    - Split boards (competitive): {df_all['competitive_flag'].sum()}")

    # ✅ BOARD REVIEW ANALYSE
    print("\nGenererer Board Review rapporter...")
    df_board_review_all = make_board_review_all_hands(df_all)
    df_board_review_summary = make_board_review_summary(df_all)
    
    # Statistik
    review_stats = board_review_statistics(df_board_review_all, df_board_review_summary)
    print_board_review_stats(review_stats)

    # ✅ DECLARER ANALYSIS
    print("\nGenererer Declarer Analysis...")
    df_declarer_analysis = make_declarer_analysis(df_all)
    df_declarer_risk = make_declarer_risk_report(df_declarer_analysis)
    print_declarer_analysis_highlights(df_declarer_analysis, top_n=5)

    # Kun rækker hvor I begge er med
    df_pair = df_all[
        df_all.apply(
            lambda r: (HENRIK in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]) and
                      (PER in [r["ns1"], r["ns2"], r["ew1"], r["ew2"]]),
            axis=1
        )
    ].copy()

    # Roller + pct (+ statusfelter, hvis din analysis.py har dem)
    df_pair = add_roles_and_pct(df_pair, henrik=HENRIK, per=PER)

    # Klassiske ark
    df_declarer = make_declarer_list(df_pair)
    df_summary = make_role_summary(df_pair)
    df_tournament = make_tournament_summary(df_pair)

    # Nye ark
    df_evening_matrix = make_evening_role_matrix(df_pair)
    df_quarterly = make_quarterly_summary_with_ci(df_pair)

    # Field data: defence + declarer (alle par, min 50 boards)
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
        df_pair.to_excel(writer, sheet_name="HF_PF_Only", index=False)
        df_declarer.to_excel(writer, sheet_name="Declarer_Games", index=False)
        df_summary.to_excel(writer, sheet_name="Summary", index=False)
        df_tournament.to_excel(writer, sheet_name="Tournament_Summary", index=False)

        df_evening_matrix.to_excel(writer, sheet_name="Evening_Role_Matrix", index=False)
        df_quarterly.to_excel(writer, sheet_name="Quarterly_CI", index=False)

        # ✅ Field data
        df_field_defense.to_excel(writer, sheet_name="Field_Data_Defense", index=False)
        df_field_declarer.to_excel(writer, sheet_name="Field_Data_Declarer", index=False)

        # ✅ Board Review
        df_board_review_all.to_excel(writer, sheet_name="Board_Review_AllHands", index=False)
        df_board_review_summary.to_excel(writer, sheet_name="Board_Review_Summary", index=False)

        # ✅ Declarer Analysis
        df_declarer_analysis.to_excel(writer, sheet_name="Declarer_Analysis", index=False)
        if not df_declarer_risk.empty:
            df_declarer_risk.to_excel(writer, sheet_name="Declarer_Risk", index=False)

    print("\n" + "="*60)
    print("ANALYSE FÆRDIG!")
    print("="*60)
    print(f"Rå rækker totalt:          {len(df_all)}")
    print(f"Rækker hvor I begge er med: {len(df_pair)}")
    print(f"Excel gemt som:            {OUTPUT_FILE}")
    print("="*60)


if __name__ == "__main__":
    main()