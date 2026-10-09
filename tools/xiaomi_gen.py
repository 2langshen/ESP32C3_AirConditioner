"""Port of halifox/android_xiaomi_ir_lab KkAcLuaEncoder to Python (with lupa for Lua).
Generates Xiaomi Konka AC IR patterns and writes a C header for the firmware."""
import json
import re
import base64
import gzip
from Crypto.Cipher import AES
from lupa import LuaRuntime

KEY = b"fd7e915003168929c1a9b0ec32a60788"
SRC = r"C:\Users\20121\Desktop\opencode-things\ac_remote\xiaomi_lab\app\src\main\assets\3_AC\Konka_90.json"
OUT = r"C:\Users\20121\Desktop\opencode-things\ac_remote\firmware\main\xiaomi_pats.h"

LUA_PRELUDE = """
bit32 = {
  band=function(a,b) return (a & b) & 0xFFFFFFFF end,
  bor=function(a,b) return (a | b) & 0xFFFFFFFF end,
  bxor=function(a,b) return (a ~ b) & 0xFFFFFFFF end,
  bnot=function(a) return (~a) & 0xFFFFFFFF end,
  lshift=function(a,b) return (a << b) & 0xFFFFFFFF end,
  rshift=function(a,b) return (a >> b) & 0xFFFFFFFF end,
}
"""
_lua = LuaRuntime(unpack_returned_tuples=True)
_lua.execute(LUA_PRELUDE)


# ---------------- fixed (type=1) ----------------
def decode_fixed(code):
    ct = base64.b64decode(code)
    dec = AES.new(KEY, AES.MODE_ECB).decrypt(ct)
    n = len(dec)
    while n > 0 and dec[n - 1] == 0x20:
        n -= 1
    return json.loads(gzip.decompress(dec[:n]).decode("utf-8"))


# ---------------- helpers ----------------
def ints(s, sep=","):
    if s is None:
        return []
    out = []
    for p in s.split(sep):
        p = p.strip()
        if p:
            try:
                out.append(int(p))
            except ValueError:
                pass
    return out


def range_list(lo, hi, step):
    step = max(1, step)
    return list(range(lo, hi + 1, step))


DEFAULT_RANGE = re.compile(r"^(-?\d+),(-?\d+)-(-?\d+)(?:,(-?\d+))?$")
SIMPLE_RANGE = re.compile(r"^(-?\d+)-(-?\d+)(?:,(-?\d+))?$")


def range_spec(v):
    v = (v or "").strip()
    m = DEFAULT_RANGE.match(v)
    if m:
        d, lo, hi = int(m.group(1)), int(m.group(2)), int(m.group(3))
        step = int(m.group(4)) if m.group(4) else 1
        return d, range_list(lo, hi, step)
    m = SIMPLE_RANGE.match(v)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        step = int(m.group(3)) if m.group(3) else 1
        return lo, range_list(lo, hi, step)
    ns = ints(v)
    only = ns[0] if ns else 0
    return only, [only]


def marker(value, prefix):
    for part in value.split("|"):
        if part.strip() and part.strip()[0].upper() == prefix:
            return part.strip()
    return None


def temperatures(rule):
    if rule is None or marker(rule, "T") is None:
        return range_list(16, 30, 1)
    mk = marker(rule, "T")
    if "&" not in mk:
        return []
    excl = set(ints(mk.split("&", 1)[1]))
    return [t for t in range_list(16, 30, 1) if t not in excl]


def fanspeeds(rule):
    if rule is None or marker(rule, "S") is None:
        return range_list(0, 3, 1)
    mk = marker(rule, "S")
    if "&" not in mk:
        return []
    excl = set(ints(mk.split("&", 1)[1]))
    return [f for f in range_list(0, 3, 1) if f not in excl]


def supported_modes(v):
    r = []
    for ch, i in (("C", 0), ("H", 1), ("A", 2), ("F", 3), ("D", 4)):
        if ch in v:
            r.append(i)
    return r


# ---------------- AcConfiguration ----------------
class Config:
    def __init__(self, model_id, key):
        raw = {}
        for k, v in key.items():
            try:
                if isinstance(v, str):
                    raw[int(k)] = v
            except (ValueError, TypeError):
                pass
        self.model_id = model_id
        self.raw = raw
        names = ["cool", "heat", "auto", "fan", "dry"]
        self.modes = []
        for mode in range(5):
            rule = raw.get(1501 + mode)
            if rule is not None and "NA" in rule.upper():
                continue
            self.modes.append((mode, temperatures(rule), fanspeeds(rule)))
        if not self.modes:
            self.modes = [(0, range_list(16, 30, 1), range_list(0, 3, 1))]
        self.winds = list(dict.fromkeys(ints(raw.get(1506)))) or [0, 1]
        self.extras = self._parse_extras(key, raw.get(1515))
        self.overrides = self._parse_overrides(key)
        self.assoc = self._parse_assoc(raw.get(1517))
        self.cond = []  # field 600 (unused by Konka)

    def _parse_extras(self, key, rules):
        names = {}
        arr = key.get("888888")
        if isinstance(arr, list):
            for item in arr:
                fid = item.get("fid", -1)
                nm = item.get("fname") or item.get("fkey") or f"F{fid}"
                names[fid] = nm
        res = {}
        if rules:
            for item in rules.split("@"):
                f = item.split("|")
                if len(f) < 4:
                    continue
                try:
                    fid = int(f[0])
                    if fid <= 7:
                        continue
                    default, values = range_spec(f[1])
                    res[fid] = {"default": default, "values": values}
                except ValueError:
                    pass
        return res

    def _parse_overrides(self, key):
        res = {}
        arr = key.get("888888")
        if isinstance(arr, list):
            for item in arr:
                fid = item.get("fid", -1)
                exts = item.get("exts")
                if fid < 0 or not isinstance(exts, dict):
                    continue
                d = {}
                for k, v in exts.items():
                    if isinstance(v, str):
                        d[int(k)] = v
                if d:
                    res[fid] = d
        return res

    def _parse_assoc(self, enc):
        res = []
        if not enc:
            return res
        for item in enc.split("|"):
            try:
                apply_primary = "@" in item
                halves = re.split(r"[$@]", item)
                if len(halves) != 2:
                    continue
                primary = set(ints(halves[0]))
                tgt = re.split(r"[&*]", halves[1])
                if len(tgt) != 3:
                    continue
                b = tgt[1].split("-")
                if len(b) != 2:
                    continue
                res.append((primary, apply_primary, int(tgt[0]), int(b[0]), int(b[1]), int(tgt[2])))
            except ValueError:
                pass
        return res

    def fields_for(self, fid):
        ov = self.overrides.get(fid)
        if not ov:
            return self.raw
        d = dict(self.raw)
        d.update(ov)
        return d

    def default_temp(self, mode):
        _, temps, _ = mode
        if not temps:
            return -1
        pref = {0: 26, 1: 20, 4: 23}.get(mode[0], 24)
        return pref if pref in temps else temps[0]

    def initial_state(self):
        mode = self.modes[0]
        fan = mode[2][0] if mode[2] else -1
        extras = {fid: e["default"] for fid, e in self.extras.items()}
        return {"power": 1, "mode": mode[0], "temp": self.default_temp(mode),
                "fan": fan, "wind": self.winds[0] if self.winds else 0, "extras": extras}

    def normalize(self, st, fid):
        st = dict(st)
        st["extras"] = dict(st["extras"])
        if fid == 1:
            st["extras"].update({9: 0, 10: 0, 22: 0})
        for primary, apply_primary, target, lo, hi, val in self.assoc:
            is_primary = fid in primary
            if (apply_primary == is_primary) and fid != target:
                cur = st["extras"].get(target, 0)
                if lo <= cur <= hi:
                    st["extras"][target] = val
        return st


# ---------------- KkAcLuaEncoder ----------------
def template(encoded):
    v = [int(encoded[i:i + 2], 16) for i in range(0, len(encoded), 2)]
    if v and v[0] == len(v) - 1:
        v = v[1:]
    return v


def write_bits(b, start, end, value):
    width = end - start
    for off in range(width):
        pos = start + off
        bi = pos // 8
        if bi < 0 or bi >= len(b):
            continue
        mask = 1 << (7 - pos % 8)
        bit = (value >> (width - 1 - off)) & 1
        b[bi] = (b[bi] | mask) if bit else (b[bi] & ~mask)


def apply_function_rules(b, encoded, states):
    if not encoded:
        return
    for item in encoded.split("@"):
        try:
            rec = [int(item[i:i + 2], 16) for i in range(0, len(item), 2)]
        except ValueError:
            continue
        if len(rec) < 3 or rec[0] != len(rec) - 1:
            continue
        if states.get(rec[1]) != rec[2]:
            continue
        i = 3
        while i + 2 < len(rec):
            write_bits(b, rec[i], rec[i + 1], rec[i + 2])
            i += 3


def run_lua(script, b, st, fid):
    t = _lua.table()
    for i, v in enumerate(b):
        t[i + 1] = v
    ex = _lua.table()
    for k, v in st["extras"].items():
        ex[k] = v
    g = _lua.globals()
    g.bytes = t
    g.power = st["power"]
    g.mode = st["mode"]
    g.temperature = st["temp"]
    g.windSpeed = st["fan"]
    g.udWindMode = st["wind"]
    g.functionId = fid
    g.exts = ex
    _lua.execute(script)
    out = _lua.globals().bytes
    vals = dict(out.items())
    n = max(vals.keys()) if vals else 0
    return [int(vals.get(i, 0)) & 0xFF for i in range(1, n + 1)]


def build_wave(fields, b):
    if fields.get(309):
        raise ValueError("309 pattern wave not implemented")
    lead = ints(fields.get(300))
    zero = ints(fields.get(301))
    one = ints(fields.get(302))
    little = fields.get(306) == "1"
    add_trailer = fields.get(307) != "1"
    repeat = max(1, int(fields.get(1508, "1")))
    bit_counts = {}
    if fields.get(1509):
        for item in fields[1509].split("|"):
            p = item.split("&")
            if len(p) == 2:
                bit_counts[int(p[0])] = int(p[1])
    delays = {}
    if fields.get(303):
        for item in fields[303].split("|"):
            if "&" in item:
                k, v = item.split("&", 1)
                delays[int(k)] = ints(v)
    out = []
    out += lead
    last = len(b) - 1
    for byte_index, val in enumerate(b):
        cnt = bit_counts.get(byte_index, bit_counts.get(-1, 8) if byte_index == last else 8)
        if little:
            for bit in range(cnt):
                out += (zero if (val & (1 << bit)) == 0 else one)
        else:
            for bit in range(cnt - 1, -1, -1):
                out += (zero if (val & (1 << bit)) == 0 else one)
        out += delays.get(byte_index, [])
    if add_trailer and one:
        out.append(one[0])
    out += delays.get(-1, [])
    if len(out) % 2 == 1:
        out.append(1000)
    frame = out[:]
    return frame * repeat


def encode(cfg, st, fid):
    fields = cfg.fields_for(fid)
    b = template(fields[1002])
    apply_function_rules(b, fields.get(1017), st["extras"])
    script = fields.get(1522)
    if script is None:
        script = fields.get(1518)
    if script:
        b = run_lua(script, b, st, fid)
    pat = build_wave(fields, b)
    if not pat or any(x <= 0 for x in pat):
        raise ValueError("bad pattern")
    return pat


# ---------------- main ----------------
def main():
    data = json.load(open(SRC, encoding="utf-8"))
    pats = []  # (label, freq, [ints])
    for o in data["data"]["others"]:
        key = o["key"]
        typ = key.get("type", o.get("type"))
        freq = key.get("frequency", o.get("frequency")) or 38000
        mid = o["_id"]
        if typ == 1:
            for name, code in key.items():
                if not isinstance(code, str) or len(code) < 40 or name.endswith("_r"):
                    continue
                try:
                    pats.append((f"{mid}.{name}", int(freq), decode_fixed(code)))
                except Exception as e:
                    print("fixed fail", mid, name, e)
        else:
            try:
                cfg = Config(mid, key)
                off = cfg.initial_state()
                on = cfg.normalize(dict(off, power=0), 1)
                p_on = encode(cfg, on, 1)
                pats.append((f"{mid}.ON", int(freq), p_on))
            except Exception as e:
                print("type2 fail", mid, repr(e))

    print(f"total patterns: {len(pats)}")
    for label, freq, p in pats:
        print(f"  {label:28s} freq={freq} len={len(p)} max={max(p)}")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// auto-generated from Xiaomi mi_remote_database (Konka, device 3)\n")
        f.write("#pragma once\n#include <stdint.h>\n\n")
        for i, (label, freq, p) in enumerate(pats):
            f.write(f"static const uint16_t xp_{i}[] = {{{','.join(str(x) for x in p)}}};\n")
        f.write("\ntypedef struct { const char* label; uint16_t freq; const uint16_t* data; uint16_t len; } xiaomi_pat_t;\n")
        f.write("static const xiaomi_pat_t xiaomi_pats[] = {\n")
        for i, (label, freq, p) in enumerate(pats):
            lbl = label.lower().replace("kk_3_90_", "").replace("90_", "")
            f.write(f'  {{"{lbl}",{freq},xp_{i},sizeof(xp_{i})/2}},\n')
        f.write("};\n#define XIAOMI_PAT_COUNT (sizeof(xiaomi_pats)/sizeof(xiaomi_pats[0]))\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
