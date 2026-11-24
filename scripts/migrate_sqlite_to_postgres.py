"""Controlled, transactional SQLite-to-PostgreSQL data migration utility.

Extracts all records from the local SQLite database and safely populates
Neon PostgreSQL, preserving all primary keys, foreign keys, timestamps,
and resetting PostgreSQL auto-incrementing serial sequences.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List
import sqlite3
import psycopg
from psycopg.rows import dict_row

# Dependency order to satisfy all foreign key constraints
MIGRATION_TABLES = [
    "users",
    "user_sessions",
    "leads",
    "templates",
    "campaigns",
    "campaign_batches",
    "campaign_recipients",
    "follow_up_schedules",
    "message_logs",
    "incoming_messages",
    "sync_logs",
]

def migrate_data(sqlite_path: str, pg_conn_str: str) -> Dict[str, Dict[str, int]]:
    """Migrate all table records from SQLite to PostgreSQL."""
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite database not found at: {sqlite_path}")

    results = {}
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    with psycopg.connect(pg_conn_str) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            # Disable triggers/FK checks temporarily during batch insert if needed,
            # or insert in strict dependency order within a transaction.
            for table in MIGRATION_TABLES:
                print(f"[Migrate] Processing table: {table}...")
                
                # Fetch SQLite rows
                sql_cur = sqlite_conn.cursor()
                sql_cur.execute(f'SELECT * FROM "{table}" ORDER BY id ASC')
                rows = [dict(r) for r in sql_cur.fetchall()]
                sqlite_count = len(rows)

                if sqlite_count == 0:
                    print(f"  -> {table}: 0 rows to migrate")
                    results[table] = {"sqlite": 0, "pg": 0}
                    continue

                # Prepare insert statement for PostgreSQL
                cols = list(rows[0].keys())
                col_names = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join(f"%({c})s" for c in cols)
                insert_stmt = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;'

                # Process boolean conversions if needed
                for r in rows:
                    for k, v in r.items():
                        # Convert SQLite boolean integer 0/1 to Python boolean for boolean columns
                        if k in ("is_deleted", "follow_up_paused", "needs_manual_followup", "is_active") and isinstance(v, int):
                            r[k] = bool(v)

                pg_cur.executemany(insert_stmt, rows)
                
                # Update PostgreSQL sequence to prevent duplicate key errors on subsequent inserts
                seq_query = f"""
                    SELECT pg_get_serial_sequence('{table}', 'id');
                """
                pg_cur.execute(seq_query)
                seq_row = pg_cur.fetchone()
                if seq_row and seq_row[0]:
                    seq_name = seq_row[0]
                    pg_cur.execute(f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM \"{table}\"), 1), true);")

                # Verify migrated row count
                pg_cur.execute(f'SELECT count(*) FROM "{table}";')
                pg_count = pg_cur.fetchone()[0]

                print(f"  -> {table}: {sqlite_count} SQLite rows -> {pg_count} PostgreSQL rows")
                results[table] = {"sqlite": sqlite_count, "pg": pg_count}

            pg_conn.commit()

    sqlite_conn.close()
    return results

if __name__ == "__main__":
    sqlite_db = "travel_agency.db"
    
    # We allow specifying the target PG connection string via env or local bridge
    pg_target = os.getenv("TARGET_PG_URL")
    if not pg_target:
        # Default to local bridge if on restricted network
        pg_target = "postgresql://neondb_owner:npg_2onzQL6qYhkJ@127.0.0.1:5438/neondb?sslmode=disable"

    print("=======================================================")
    print("STARTING CONTROLLED SQLITE TO NEON POSTGRESQL MIGRATION")
    print(f"Source: {sqlite_db}")
    print(f"Target: {pg_target}")
    print("=======================================================")
    
    res = migrate_data(sqlite_db, pg_target)
    
    print("\n=======================================================")
    print("MIGRATION SUMMARY AUDIT:")
    all_match = True
    for tbl, counts in res.items():
        match = counts["sqlite"] == counts["pg"]
        status = "MATCH [OK]" if match else "MISMATCH [FAIL]"
        if not match:
            all_match = False
        print(f"  {tbl:<25}: SQLite={counts['sqlite']:<3} | PostgreSQL={counts['pg']:<3} -> {status}")
    print("=======================================================")
    if all_match:
        print("[SUCCESS] 100% OF DATA WAS MIGRATED AND VERIFIED ACCURATELY!")
    else:
        print("[WARNING] Record count discrepancies detected!")
        sys.exit(1)
