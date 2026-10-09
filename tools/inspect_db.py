import sqlite3
import sys

DB = r"C:\Users\20121\Desktop\opencode-things\ac_remote\irext_database\db\irext_db_20260929_sqlite3.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=== TABLES ===")
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
for t in tables:
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
    except Exception as e:
        n = f"err:{e}"
    print(f"{t:40s} rows={n}")

print("\n=== SCHEMAS ===")
for t in tables:
    cols = cur.execute(f"PRAGMA table_info(\"{t}\")").fetchall()
    colstr = ", ".join(f"{c[1]}:{c[2]}" for c in cols)
    print(f"[{t}] {colstr}")

con.close()
