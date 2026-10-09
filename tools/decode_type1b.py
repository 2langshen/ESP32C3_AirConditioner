import json
import base64
import gzip
import hashlib
from Crypto.Cipher import AES

KEY = b"fd7e915003168929c1a9b0ec32a60788"
P = r"C:\Users\20121\Desktop\opencode-things\ac_remote\xiaomi_lab\app\src\main\assets\3_AC\Konka_90.json"


def decode(code):
    ct = base64.b64decode(code)
    dec = AES.new(KEY, AES.MODE_ECB).decrypt(ct)
    n = len(dec)
    while n > 0 and dec[n - 1] == 0x20:
        n -= 1
    return json.loads(gzip.decompress(dec[:n]).decode("utf-8"))


d = json.load(open(P, encoding="utf-8"))
o = [x for x in d["data"]["others"] if x["_id"] == "kk_3_90_4872"][0]
keys = {k: v for k, v in o["key"].items() if isinstance(v, str) and len(v) > 40 and not k.endswith("_r")}
pats = {k: decode(v) for k, v in keys.items()}
for k, p in pats.items():
    print(k, "md5", hashlib.md5(bytes(str(p), "utf8")).hexdigest(), "len", len(p))
p1 = pats["power"]
p2 = pats["COOL"]
print("power == COOL ?", p1 == p2)
diffs = [i for i in range(min(len(p1), len(p2))) if p1[i] != p2[i]]
print("num diff idx:", len(diffs), "first diffs:", diffs[:20])
print("power:", p1)
