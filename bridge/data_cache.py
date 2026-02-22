import json
import os
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import shutil

class DataCache:
    """
    Smart cache system for bridge tournament data
    
    REGLER:
    1. Hvis <= 2 dage gammel: SCRAPE (data kan ændres)
    2. Hvis > 2 dage gammel OG i cache: SKIP (data låst)
    3. Hvis > 2 dage gammel OG IKKE i cache: SCRAPE (bruger spørger)
    4. --force-refresh: Ignorér alle regler, SCRAPE ALT
    
    PERIODE-MODES:
    - Default: sidste 7 dage
    - Custom cutoff: --cutoff=DATO
    - Interval: --from=DATO --to=DATO
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        self.manifest_file = self.data_dir / "cache_manifest.json"
        self.tournaments_dir = self.data_dir / "tournaments"
        self.tournaments_dir.mkdir(exist_ok=True)
        
        self.manifest = self._load_manifest()
    
    # ==================== MANIFEST MANAGEMENT ====================
    
    def _load_manifest(self) -> Dict:
        """Load manifest from JSON or create empty"""
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return self._create_empty_manifest()
        return self._create_empty_manifest()
    
    def _create_empty_manifest(self) -> Dict:
        """Create empty manifest structure"""
        return {
            "version": "1.0",
            "last_sync": None,
            "default_cutoff_days": 7,
            "lock_period_hours": 48,
            "tournaments": {}
        }
    
    def _save_manifest(self):
        """Save manifest to JSON"""
        with open(self.manifest_file, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)
    
    # ==================== DATE RANGE PARSING ====================
    
    def parse_date_range(
        self,
        cutoff: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> Tuple[datetime, datetime]:
        """
        Bestem perioden baseret på argumenter
        
        Prioritet:
        1. Hvis --from og --to: Brug dem (INTERVAL MODE)
        2. Else hvis --cutoff: Fra --cutoff til i dag (CUSTOM CUTOFF MODE)
        3. Else: Fra i dag - 7 dage til i dag (DEFAULT MODE)
        """
        today = datetime.now().date()
        
        # MODE 3: Interval
        if from_date and to_date:
            start = datetime.strptime(from_date, '%Y-%m-%d').date()
            end = datetime.strptime(to_date, '%Y-%m-%d').date()
            print(f"📅 MODE 3 - Interval: {start} til {end}")
            return start, end
        
        # MODE 2: Custom cutoff
        if cutoff:
            start = datetime.strptime(cutoff, '%Y-%m-%d').date()
            end = today
            print(f"📅 MODE 2 - Custom cutoff: {start} til {end} (i dag)")
            return start, end
        
        # MODE 1: Default (7 dage)
        default_cutoff_days = self.manifest.get("default_cutoff_days", 7)
        start = today - timedelta(days=default_cutoff_days)
        end = today
        print(f"📅 MODE 1 - Default: {start} til {end} (sidste {default_cutoff_days} dage)")
        return start, end
    
    # ==================== SCRAPING DECISION LOGIC ====================
    
    def should_scrape_tournament(
        self,
        tournament_id: int,
        tournament_date: datetime,
        force_refresh: bool = False,
        user_requested_older: bool = False
    ) -> bool:
        """
        Bestem om vi skal scrape denne turnering
        """
        today = datetime.now().date()
        if isinstance(tournament_date, datetime):
            tournament_date = tournament_date.date()
        
        days_old = (today - tournament_date).days
        is_in_cache = str(tournament_id) in self.manifest["tournaments"]
        
        lock_period_hours = self.manifest.get("lock_period_hours", 48)
        lock_period_days = lock_period_hours / 24
        
        # REGEL 1: Force refresh
        if force_refresh:
            print(f"    🔄 SCRAPE: Turnering {tournament_id} ({tournament_date}) - force refresh")
            return True
        
        # REGEL 2: Bruger bad specifikt om det
        if user_requested_older:
            print(f"    🔄 SCRAPE: Turnering {tournament_id} ({tournament_date}) - bruger bad om det")
            return True
        
        # REGEL 3: Inden for lock period (48 timer)
        if days_old <= lock_period_days:
            if is_in_cache:
                print(f"    🔄 SCRAPE: Turnering {tournament_id} ({tournament_date}) - refresh (<{lock_period_hours}h, data kan ændres)")
            else:
                print(f"    🔄 SCRAPE: Turnering {tournament_id} ({tournament_date}) - ny turnering (<{lock_period_hours}h)")
            return True
        
        # REGEL 4 & 5: Over lock period
        if is_in_cache:
            print(f"    ⊘ SKIP: Turnering {tournament_id} ({tournament_date}) - allerede i cache (>{lock_period_hours}h, data låst)")
            return False
        else:
            print(f"    🔄 SCRAPE: Turnering {tournament_id} ({tournament_date}) - ny turnering bruger spørger om")
            return True
    
    # ==================== HELPER: CONVERT DATES ====================
    
    def _convert_dates_to_strings(self, obj):
        """
        Rekursivt konverter alle datetime/date objekter til strings
        """
        if isinstance(obj, (datetime, date)):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: self._convert_dates_to_strings(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._convert_dates_to_strings(item) for item in obj]
        else:
            return obj
    
    # ==================== CACHE OPERATIONS ====================
    
    def tournament_exists(self, tournament_id: int) -> bool:
        """Check if tournament data exists in cache"""
        return str(tournament_id) in self.manifest["tournaments"]
    
    def get_cached_tournament(self, tournament_id: int) -> Optional[Dict]:
        """Hent cachet turnerings-data fra JSON"""
        if not self.tournament_exists(tournament_id):
            return None
        
        tournament_file = self.tournaments_dir / f"tournament_{tournament_id}.json"
        if not tournament_file.exists():
            return None
        
        try:
            with open(tournament_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Fejl ved laesning af tournament {tournament_id}: {e}")
            return None
    
    def save_tournament_data(
        self,
        tournament_id: int,
        tournament_date: datetime,
        sections: List[Dict],
        data: Dict
    ):
        """Gem turneringsd-data til JSON og opdater manifest"""
        
        # Konverter alle datetime/date objekter til strings i data
        data_to_save = self._convert_dates_to_strings(data)
        
        # Gem turnerings-data
        tournament_file = self.tournaments_dir / f"tournament_{tournament_id}.json"
        with open(tournament_file, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)
        
        # Opdater manifest
        if isinstance(tournament_date, datetime):
            tournament_date = tournament_date.date()
        
        self.manifest["tournaments"][str(tournament_id)] = {
            "tournament_id": tournament_id,
            "date": str(tournament_date),
            "days_old": (datetime.now().date() - tournament_date).days,
            "cached_at": datetime.now().isoformat(),
            "sections": [s["name"] for s in sections],
            "hand_count": sum(len(data.get("sections", {}).get(s["name"], [])) for s in sections),
            "status": "complete",
            "is_locked": (datetime.now().date() - tournament_date).days > 2
        }
        
        self.manifest["last_sync"] = datetime.now().isoformat()
        self._save_manifest()
        
        print(f"    Gemt i cache: tournament_{tournament_id}.json")
    
    # ==================== BACKUP OPERATIONS ====================
    
    def create_backup(self, backup_dir: str = "backups") -> str:
        """Lav backup af hele cache-mappen"""
        backup_path = Path(backup_dir)
        backup_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_path / f"cache_backup_{timestamp}.zip"
        
        shutil.make_archive(
            str(backup_file.with_suffix('')),
            'zip',
            self.data_dir
        )
        
        print(f"Backup lavet: {backup_file}")
        return str(backup_file)
    
    # ==================== CACHE STATUS ====================
    
    def print_cache_status(self):
        """Print status paa cache"""
        print("\n" + "="*70)
        print("CACHE STATUS")
        print("="*70)
        
        total_tournaments = len(self.manifest["tournaments"])
        locked_tournaments = sum(
            1 for t in self.manifest["tournaments"].values()
            if t.get("is_locked", False)
        )
        unlocked_tournaments = total_tournaments - locked_tournaments
        
        print(f"Total turneringer i cache: {total_tournaments}")
        print(f"  - Laast (>48h): {locked_tournaments}")
        print(f"  - Oplaast (<48h): {unlocked_tournaments}")
        print(f"Sidst synkroniseret: {self.manifest.get('last_sync', 'Aldrig')}")
        
        if self.manifest["tournaments"]:
            print("\nTurneringer i cache:")
            for tid, tdata in sorted(
                self.manifest["tournaments"].items(),
                key=lambda x: x[1]["date"],
                reverse=True
            ):
                status = "Laast" if tdata.get("is_locked") else "Opraast"
                date_str = tdata["date"]
                days = tdata.get("days_old", "?")
                sections = ", ".join(tdata.get("sections", []))
                print(f"  {status} | {tid}: {date_str} ({days}d) - Sections: {sections}")
        
        print("="*70 + "\n")
    
    # ==================== UTILITY ====================
    
    def clear_cache(self, confirm: bool = False):
        """Slet hele cache-mappen"""
        if not confirm:
            print("Bekraeftelse paakraevet. Brug clear_cache(confirm=True)")
            return
        
        shutil.rmtree(self.data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.manifest = self._create_empty_manifest()
        print("Cache slettet")