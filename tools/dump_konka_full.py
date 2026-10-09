import json

P = r"C:\Users\20121\Desktop\opencode-things\ac_remote\xiaomi_lab\app\src\main\assets\3_AC\Konka_90.json"
d = json.load(open(P, encoding="utf-8"))
for i, o in enumerate(d["data"]["others"]):
    k = o["key"]
    typ = k.get("type", o.get("type"))
    print("=" * 70)
    print(f"[{i}] {o['_id']} type={typ} freq={k.get('frequency', o.get('frequency'))}")
    if typ == 1:
        for kk, vv in k.items():
            if isinstance(vv, str) and len(vv) > 60:
                print(f"   {kk}: {vv[:60]}...")
            else:
                print(f"   {kk}: {vv}")
        continue
    for f in (1002, 300, 301, 302, 303, 304, 305, 306, 307, 309, 310, 1017, 1508, 1509, 1008, 1001):
        if str(f) in k:
            print(f"   {f}: {k[str(f)]}")
    for luakey in ("1522", "1518"):
        if luakey in k:
            print(f"   ---{luakey}---")
            print(k[luakey])
