import sqlite3

DB = r"C:\Users\20121\Desktop\opencode-things\ac_remote\irext_database\db\irext_db_20260929_sqlite3.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=== CATEGORIES ===")
for r in cur.execute("SELECT id, name, name_en, name_short FROM category ORDER BY id"):
    print(f"  id={r['id']:<3} {r['name']:<10} {r['name_en']:<14} {r['name_short']}")

print("\n=== BRANDS containing 康佳 / konka ===")
rows = cur.execute(
    "SELECT id, name, category_id, category_name, name_en, status "
    "FROM brand WHERE name LIKE '%康佳%' OR name_en LIKE '%konka%' OR name LIKE '%Konka%'"
).fetchall()
for r in rows:
    print(f"  brand_id={r['id']:<5} name={r['name']:<8} cat={r['category_id']}({r['category_name']}) en={r['name_en']} status={r['status']}")
if not rows:
    print("  (none)")

print("\n=== remote_index for 康佳 ===")
rows = cur.execute(
    "SELECT id, category_id, category_name, brand_id, brand_name, protocol, remote, remote_number, binary_md5, status "
    "FROM remote_index WHERE brand_name LIKE '%康佳%' OR brand_name LIKE '%konka%'"
).fetchall()
for r in rows:
    print(f"  index_id={r['id']:<6} cat={r['category_id']}({r['category_name']}) brand={r['brand_name']} "
          f"proto={r['protocol']} remote={r['remote']} num={r['remote_number']} md5={r['binary_md5']} status={r['status']}")
print(f"  total: {len(rows)}")

con.close()
