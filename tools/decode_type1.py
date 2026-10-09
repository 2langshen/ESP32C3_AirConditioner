import json
import base64
import gzip
from Crypto.Cipher import AES

KEY = b"fd7e915003168929c1a9b0ec32a60788"
P = r"C:\Users\20121\Desktop\opencode-things\ac_remote\xiaomi_lab\app\src\main\assets\3_AC\Konka_90.json"


def decode(code):
    ct = base64.b64decode(code)
    if len(ct) % 16:
        ct = ct[: len(ct) // 16 * 16]
    dec = AES.new(KEY, AES.MODE_ECB).decrypt(ct)
    n = len(dec)
    while n > 0 and dec[n - 1] == 0x20:
        n -= 1
    raw = gzip.decompress(dec[:n])
    return json.loads(raw.decode("utf-8"))


d = json.load(open(P, encoding="utf-8"))
for o in d["data"]["others"]:
    typ = o["key"].get("type", o.get("type"))
    if typ != 1:
        continue
    print("model", o["_id"], "freq", o["key"].get("frequency", o.get("frequency")))
    for name, code in o["key"].items():
        if not isinstance(code, str) or len(code) < 40:
            continue
        if name.endswith("_r"):
            continue
        try:
            pat = decode(code)
            print(f"  {name:18s} len={len(pat):4d} first={pat[:8]} last={pat[-4:]} sum={sum(pat)}")
        except Exception as e:
            print(f"  {name:18s} ERR {e}")
