import json

P = r"C:\Users\20121\Desktop\opencode-things\ac_remote\xiaomi_lab\app\src\main\assets\3_AC\Konka_90.json"
d = json.load(open(P, encoding="utf-8"))
others = d["data"]["others"]
print("Konka count:", len(others))
for i, o in enumerate(others):
    _id = o.get("_id")
    key = o.get("key", {})
    typ = key.get("type", o.get("type"))
    freq = key.get("frequency", o.get("frequency"))
    has_power = "power" in key
    has_1002 = "1002" in key
    has_lua = ("1522" in key) or ("1518" in key)
    print(f"[{i}] _id={_id} type={typ} freq={freq} power_fixed={has_power} base1002={has_1002} lua={has_lua} keys={len(key)}")
