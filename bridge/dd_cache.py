"""SQLite cache for double-dummy results.

Database location: Data/dd_cache.db (relative to project root).

Tables
------
dd_deals
    deal_hash TEXT PRIMARY KEY
    dd_{dir}_{strain} for all 4*5 = 20 DD columns
    created_at TEXT

dd_par
    deal_hash TEXT
    vul TEXT
    par_score INTEGER
    par_contract TEXT
    par_side TEXT
    created_at TEXT
    PRIMARY KEY (deal_hash, vul)

dd_lead_tables
    deal_hash TEXT
    contract_strain TEXT  (field-name strain: NT/S/H/D/C)
    declarer_dir TEXT     (Danish direction: N/Ø/S/V)
    lead_card TEXT        (canonical: "H5", "SA", …)
    declarer_tricks INTEGER
    created_at TEXT
    PRIMARY KEY (deal_hash, contract_strain, declarer_dir, lead_card)

Deal hash
---------
SHA-256 of the canonical string  "N:{n}|E:{e}|S:{s}|W:{w}"
where n/e/s/w are dot-notation hands in English rank notation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Database path (relative to this file's package root)
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).parent.parent / "Data" / "dd_cache.db"

_DD_DIRS = ["N", "Ø", "S", "V"]
_DD_STRAINS = ["NT", "S", "H", "D", "C"]
_DD_COLS = [f"dd_{d}_{s}" for d in _DD_DIRS for s in _DD_STRAINS]

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_DD_DEALS = f"""
CREATE TABLE IF NOT EXISTS dd_deals (
    deal_hash TEXT PRIMARY KEY,
    {', '.join(f'{col} INTEGER' for col in _DD_COLS)},
    created_at TEXT NOT NULL
);
"""

_CREATE_DD_PAR = """
CREATE TABLE IF NOT EXISTS dd_par (
    deal_hash TEXT NOT NULL,
    vul TEXT NOT NULL,
    par_score INTEGER,
    par_contract TEXT,
    par_side TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (deal_hash, vul)
);
"""

_CREATE_DD_LEAD_TABLES = """
CREATE TABLE IF NOT EXISTS dd_lead_tables (
    deal_hash TEXT NOT NULL,
    contract_strain TEXT NOT NULL,
    declarer_dir TEXT NOT NULL,
    lead_card TEXT NOT NULL,
    declarer_tricks INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (deal_hash, contract_strain, declarer_dir, lead_card)
);
"""


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_DD_DEALS)
    conn.execute(_CREATE_DD_PAR)
    conn.execute(_CREATE_DD_LEAD_TABLES)
    conn.commit()


def _get_connection() -> sqlite3.Connection:
    conn = _connect()
    _ensure_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Deal hash
# ---------------------------------------------------------------------------

# Direction mapping for canonical hash (Danish → NESW)
_DK_TO_NESW = {"N": "N", "Ø": "E", "S": "S", "V": "W"}


def get_deal_hash(row: dict) -> Optional[str]:
    """Compute sha256-based deal hash from the four hands in a board row.

    Returns None if any hand is missing.
    """
    try:
        n = str(row["N_hand"])
        e = str(row["Ø_hand"])
        s = str(row["S_hand"])
        w = str(row["V_hand"])
    except KeyError:
        return None
    if not all([n, e, s, w]):
        return None
    canonical = f"N:{n}|E:{e}|S:{s}|W:{w}"
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# DD table CRUD
# ---------------------------------------------------------------------------


def get_dd_table(deal_hash: str) -> Optional[dict]:
    """Return cached DD table dict or None if not cached.

    Dict has keys dd_{dir}_{strain} for all 20 combinations.
    """
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dd_deals WHERE deal_hash = ?", (deal_hash,)
        ).fetchone()
    if row is None:
        return None
    return {col: row[col] for col in _DD_COLS}


def save_dd_table(deal_hash: str, data: dict) -> None:
    """Persist a DD table dict to the cache.

    data must contain all 20 dd_{dir}_{strain} keys.
    """
    now = datetime.now(timezone.utc).isoformat()
    row_data = {col: data.get(col) for col in _DD_COLS}
    cols = ["deal_hash"] + _DD_COLS + ["created_at"]
    placeholders = ", ".join("?" for _ in cols)
    values = [deal_hash] + [row_data[c] for c in _DD_COLS] + [now]
    sql = f"INSERT OR REPLACE INTO dd_deals ({', '.join(cols)}) VALUES ({placeholders})"
    with _get_connection() as conn:
        conn.execute(sql, values)
        conn.commit()


# ---------------------------------------------------------------------------
# Par CRUD
# ---------------------------------------------------------------------------


def get_par(deal_hash: str, vul: str) -> Optional[dict]:
    """Return cached par result or None.

    Returns dict with keys: par_score, par_contract, par_side.
    """
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT par_score, par_contract, par_side FROM dd_par "
            "WHERE deal_hash = ? AND vul = ?",
            (deal_hash, vul),
        ).fetchone()
    if row is None:
        return None
    return {
        "par_score": row["par_score"],
        "par_contract": row["par_contract"],
        "par_side": row["par_side"],
    }


def save_par(deal_hash: str, vul: str, data: dict) -> None:
    """Persist par result to cache."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO dd_par "
            "(deal_hash, vul, par_score, par_contract, par_side, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (deal_hash, vul, data.get("par_score"), data.get("par_contract"),
             data.get("par_side"), now),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Lead table CRUD
# ---------------------------------------------------------------------------


def get_lead_table(deal_hash: str, contract_strain: str, declarer_dir: str) -> Optional[dict]:
    """Return cached lead table or None.

    Returns dict mapping canonical card key → declarer tricks.
    E.g. {"H5": 9, "C3": 7, …}
    """
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT lead_card, declarer_tricks FROM dd_lead_tables "
            "WHERE deal_hash = ? AND contract_strain = ? AND declarer_dir = ?",
            (deal_hash, contract_strain, declarer_dir),
        ).fetchall()
    if not rows:
        return None
    return {r["lead_card"]: r["declarer_tricks"] for r in rows}


def save_lead_table(deal_hash: str, contract_strain: str, declarer_dir: str, data: dict) -> None:
    """Persist a lead table to the cache.

    data: {card_canonical: declarer_tricks}
    """
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        for card, tricks in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO dd_lead_tables "
                "(deal_hash, contract_strain, declarer_dir, lead_card, declarer_tricks, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (deal_hash, contract_strain, declarer_dir, card, tricks, now),
            )
        conn.commit()
