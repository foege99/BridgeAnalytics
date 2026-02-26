import sys
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import pandas as pd

from bridge.data_cache import DataCache
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
    write_board1_layout_sheet,
)

# ✅ IMPORT DECLARER ANALYSIS
from bridge.declarer_analysis import (
    make_declarer_analysis,
    make_declarer_risk_report,
    print_declarer_analysis_highlights,
)

HENRIK = "Henrik Friis"
PER = "Per Føge Jensen"

# Use unique filename to avoid Windows file-lock issues
OUTPUT_FILE = f"Henrik_Per_ANALYSE_{datetime.now():%Y%m%d_%H%M}.xlsx"


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Bridge Analytics - Scrap og analyser bridge-turneringer med smart caching'
    )
    
    parser.add_argument(
        '--cutoff',
        type=str,
        help='Cutoff dato (fra denne dato til i dag). Format: YYYY-MM-DD. Default: sidste 7 dage'
    )
    
    parser.add_argument(
        '--from',
        dest='from_date',
        type=str,
        help='Start dato for interval. Format: YYYY-MM-DD'
    )
    
    parser.add_argument(
        '--to',
        dest='to_date',
        type=str,
        help='Slut dato for interval. Format: YYYY-MM-DD'
    )
    
    parser.add_argument(
        '--force-refresh',
        action='store_true',
        help='Tvinger refresh af alle turneringer i perioden'
    )
    
    parser.add_argument(
        '--cache-status',
        action='store_true',
        help='Vis cache status og exit'
    )
    
    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help='Slet hele cache (kræver bekræftelse)'
    )
    
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Lav backup af cache før start'
    )
    
    return parser.parse_args()


def main():
    args = parse_arguments()
    
    # ==================== SETUP CACHE ====================
    print("🚀 Initialiserer cache system...")
    cache = DataCache(data_dir="data")
    
    # ==================== HANDLE SPECIAL FLAGS ====================
    
    # Show cache status
    if args.cache_status:
        cache.print_cache_status()
        return
    
    # Clear cache
    if args.clear_cache:
        response = input("⚠️  Sikker på du vil slette hele cache? (ja/nej): ")
        if response.lower() in ['ja', 'yes', 'y']:
            cache.clear_cache(confirm=True)
        return
    
    # Create backup
    if args.backup:
        cache.create_backup()
    
    # ==================== PARSE DATE RANGE ====================
    print("Starter crawler + scraper + analyse...")
    
    start_date, end_date = cache.parse_date_range(
        cutoff=args.cutoff,
        from_date=args.from_date,
        to_date=args.to_date
    )
    
    force_refresh = args.force_refresh
    if force_refresh:
        print("🔄 FORCE REFRESH MODE - Scraper alt på tværs af regler")
    
    # ==================== CRAWL BRIDGE.DK ====================
    print(f"📡 Søger turneringer på bridge.dk fra {start_date} til {end_date}...")
    
    # Crawler finder turneringer fra bridge.dk
    all_tournaments_on_site = get_recent_tournaments(start_date)
    
    if not all_tournaments_on_site:
        print("Ingen turneringer fundet indenfor perioden.")
        return
    
    print(f"Antal turneringer fundet på bridge.dk: {len(all_tournaments_on_site)}")
    
    # Filter turneringer til vores periode
    tournaments_in_range = [
        t for t in all_tournaments_on_site 
        if start_date <= t['date'].date() <= end_date
    ]
    
    print(f"Antal turneringer i période [{start_date} - {end_date}]: {len(tournaments_in_range)}")
    
    # ==================== BESLUT OM SCRAPING ====================
    print("\n📋 Beslutter hvad skal skrabes...")
    print("="*70)
    
    tournaments_to_scrape = []
    tournaments_to_use_cache = []
    
    for tournament in tournaments_in_range:
        tournament_id = tournament['tournament_id']
        tournament_date = tournament['date']
        
        # Tjek om bruger specifikt bad om denne periode (hvis --from/--to er brugt)
        user_requested_older = bool(args.from_date and args.to_date)
        
        should_scrape = cache.should_scrape_tournament(
            tournament_id=tournament_id,
            tournament_date=tournament_date,
            force_refresh=force_refresh,
            user_requested_older=user_requested_older
        )
        
        if should_scrape:
            tournaments_to_scrape.append(tournament)
        else:
            tournaments_to_use_cache.append(tournament)
    
    print("="*70)
    print(f"\n📊 Beslutninger:")
    print(f"  🔄 SCRAPE: {len(tournaments_to_scrape)} turneringer")
    print(f"  💾 CACHE: {len(tournaments_to_use_cache)} turneringer")
    
    # ==================== SCRAPE & CACHE ====================
    print("\n🌐 Starter scraping...")
    all_rows = []
    tournaments_scraped = 0
    
    for t_idx, tournament in enumerate(tournaments_to_scrape, 1):
        tournament_id = tournament['tournament_id']
        tdate = tournament['date']
        sections = tournament['sections']
        
        print(f"\n({t_idx}/{len(tournaments_to_scrape)}) SCRAPE: {tdate.date()} – Turnering {tournament_id}")
        print(f"  Sections: {', '.join([s['name'] for s in sections])}")
        
        tournament_rows = []
        tournament_data = {"tournament_id": tournament_id, "date": str(tdate.date()), "sections": {}}
        
        # Scrape hver section
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
                
                # Tilføj section kolonne
                for row in rows:
                    row['section'] = section_name
                
                print(f"      ✓ {len(rows)} rækker")
                tournament_rows.extend(rows)
                tournament_data["sections"][section_name] = rows
                
            except Exception as e:
                print(f"      !!! Fejl ved scraping: {e}")
        
        # Gem i cache
        if tournament_rows:
            cache.save_tournament_data(
                tournament_id=tournament_id,
                tournament_date=tdate,
                sections=sections,
                data=tournament_data
            )
            all_rows.extend(tournament_rows)
            tournaments_scraped += 1
    
        # ==================== LOAD CACHED DATA ====================
    print(f"\n💾 Indlæser {len(tournaments_to_use_cache)} turneringer fra cache...")
    
    for tournament in tournaments_to_use_cache:
        tournament_id = tournament['tournament_id']
        tdate = tournament['date']
        
        cached_data = cache.get_cached_tournament(tournament_id)
        
        if cached_data:
            print(f"  ✓ Turnering {tournament_id} ({tdate.date()}) - fra cache")
            
            # ✅ KONVERTER strings tilbage til datetime
            # Fordi JSON lagrer alt som strings
            for section_name, rows in cached_data.get("sections", {}).items():
                for row in rows:
                    row['section'] = section_name
                    
                    # Konverter date strings tilbage til date objekter
                    if 'date' in row and isinstance(row['date'], str):
                        try:
                            row['date'] = datetime.strptime(row['date'], '%Y-%m-%d').date()
                        except:
                            pass
                    
                    all_rows.append(row)
        else:
            print(f"  ❌ Turnering {tournament_id} ({tdate.date()}) - FEJL, cache findes ikke")# ==================== PROCESS DATA ====================
    
    if not all_rows:
        print("Ingen data fundet.")
        return
    
    df_all = pd.DataFrame(all_rows)
    
    print(f"\n✓ I alt {len(df_all)} rækker fra {len(tournaments_in_range)} turneringer")
    print(f"  Sections: {df_all['section'].unique().tolist()}")
    print(f"  Scraped: {tournaments_scraped}, fra Cache: {len(tournaments_to_use_cache)}")
    
    print("\nTilføjer hånd-features...")
    df_all = add_hand_features(df_all)
    
    # ✅ TILFØJ PHASE 2.1 REFERENCE-LAG
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
    
    # ✅ KLASSISKE RAPPORTER
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
    
    # ✅ FIELD REPORTS
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
        
        # Board 1 layout from latest tournament
        write_board1_layout_sheet(writer, df_all, PER)
    
    print(f"✅ Analyse færdig! Output: {OUTPUT_FILE}")
    
    # ==================== SHOW CACHE STATUS ====================
    cache.print_cache_status()

    # ✅ SKRIV JSON (samme data som Excel, men som JSON-fil)
    json_file = str(Path(OUTPUT_FILE).with_suffix(".json"))
    save_as_json(
        {
            "Board_Review_All": df_board_review_all,
            "Board_Review_Summary": df_board_review_summary,
            "Declarer_Analysis": df_declarer_analysis,
            "Declarer_List": df_declarer,
            "Role_Summary": df_summary,
            "Tournament_Summary": df_tournament,
            "Evening_Matrix": df_evening_matrix,
            "Quarterly_Summary": df_quarterly,
            "Field_Defense": df_field_defense,
            "Field_Declarer": df_field_declarer,
        },
        json_file,
    )


def save_as_json(sheets: dict, json_path: str) -> None:
    """
    Gem alle analyse-DataFrames som én JSON-fil.

    Strukturen er::

        {
          "Board_Review_All": [ {...}, {...}, ... ],
          "Tournament_Summary": [ {...}, ... ],
          ...
        }

    Dato-kolonner serialiseres som ISO-8601 strings.
    NaN-værdier konverteres til null.

    Parameters
    ----------
    sheets : dict
        {ark_navn: pd.DataFrame}  – samme navne som Excel-arkene.
    json_path : str
        Sti til output-filen, f.eks. "Henrik_Per_ANALYSE_20260221_2023.json".
    """
    output: dict = {}
    for sheet_name, df in sheets.items():
        if df is None or df.empty:
            continue
        # Konverter til records-liste med ISO-datoer og Python-native typer
        records = json.loads(
            df.to_json(orient="records", date_format="iso", force_ascii=False)
        )
        output[sheet_name] = records

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ JSON gemt: {json_path}")


if __name__ == "__main__":
    main()