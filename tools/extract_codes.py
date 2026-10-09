import sqlite3
import hashlib
import os
import shutil
import json

BASE = r"C:\Users\20121\Desktop\opencode-things\ac_remote"
DB = os.path.join(BASE, "irext_database", "db", "irext_db_20260929_sqlite3.db")
BINDIR = os.path.join(BASE, "irext_database", "binaries", "extracted", "irext-binaries_20260929")
OUTDIR = os.path.join(BASE, "codes")
os.makedirs(OUTDIR, exist_ok=True)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

rows = cur.execute(
    "SELECT id, category_name, brand_name, protocol, remote, remote_number, binary_md5 "
    "FROM remote_index WHERE brand_id=7 AND category_id=1 ORDER BY id"
).fetchall()

results = []
for r in rows:
    fname = f"irda_{r['protocol']}_{r['remote']}.bin"
    fpath = os.path.join(BINDIR, fname)
    rec = {"index_id": r["id"], "protocol": r["protocol"], "remote": r["remote"],
           "binary_md5": r["binary_md5"], "file": fname, "found": os.path.isfile(fpath)}
    if rec["found"]:
        data = open(fpath, "rb").read()
        actual = hashlib.md5(data).hexdigest()
        rec["size"] = len(data)
        rec["md5_match"] = (actual == r["binary_md5"])
        rec["md5_actual"] = actual
        dst = os.path.join(OUTDIR, f"konka_ac_{r['id']}.bin")
        shutil.copyfile(fpath, dst)
        rec["dest"] = dst
    results.append(rec)

con.close()

out = os.path.join(BASE, "codes", "konka_ac_manifest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

for rec in results:
    print(f"index_id={rec['index_id']} proto={rec['protocol']} remote={rec['remote']} "
          f"file={rec['file']} found={rec['found']} "
          f"md5_match={rec.get('md5_match')} size={rec.get('size')}")
print(f"\nmanifest -> {out}")
