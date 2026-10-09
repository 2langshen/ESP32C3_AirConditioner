import json
import xiaomi_gen as xg

SRC = xg.SRC
OUT = r"C:\Users\20121\Desktop\opencode-things\ac_remote\firmware\main\xiaomi_state_pats.h"
MODEL = "kk_3_90_8101"


def parse_table(s):
    ops = []
    i = 0
    while i < len(s):
        ln = int(s[i:i + 2], 16)
        i += 2
        rec = [int(s[i + 2 * k:i + 2 * k + 2], 16) for k in range(ln)]
        i += 2 * ln
        ops.append(rec)
    return ops


def apply_op(b, rec):
    j = 0
    while j + 2 < len(rec):
        xg.write_bits(b, rec[j], rec[j + 1], rec[j + 2])
        j += 3


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    o = [x for x in d["data"]["others"] if x["_id"] == MODEL][0]
    key = o["key"]
    freq = int(key.get("frequency", o.get("frequency")) or 38000)
    cfg = xg.Config(MODEL, key)
    f = cfg.raw
    tables = {}
    for name in (1011, 1012, 1013, 1015):
        if name in f:
            t = parse_table(f[name])
            tables[len(t)] = t
    temp_t = tables.get(15)
    mode_t = tables.get(5)
    fan_t = tables.get(4)
    wind_t = tables.get(7)
    base = xg.template(f[1002])
    lua = f.get(1522) or f.get(1518)

    def frame(mode=None, temp=None, fan=None, wind=None):
        b = list(base)
        if mode is not None and mode_t:
            apply_op(b, mode_t[mode])
        if fan is not None and fan_t:
            apply_op(b, fan_t[fan])
        if wind is not None and wind_t:
            apply_op(b, wind_t[wind])
        if temp is not None and temp_t:
            apply_op(b, temp_t[temp - 16])  # index 0 -> 16C (verified against AC)
        st = cfg.initial_state()
        st["extras"] = {9: 0, 10: 0, 22: 0}
        b = xg.run_lua(lua, b, st, 1)
        return xg.build_wave(f, b)

    fames = []  # (label, pattern)

    # power bit = byte5 bit2 (verified against AC): 1=on, 0=off
    def power_frame(on):
        b = list(base)
        if on:
            b[5] |= 0x04
        else:
            b[5] &= ~0x04
        st = cfg.initial_state()
        st["extras"] = {9: 0, 10: 0, 22: 0}
        b = xg.run_lua(lua, b, st, 1)
        return xg.build_wave(f, b)

    fames.append(("power_on", power_frame(True)))
    fames.append(("power_off", power_frame(False)))
    for m, nm in enumerate(["cool", "heat", "auto", "fan", "dry"]):
        fames.append((f"mode_{nm}", frame(mode=m)))
    for t in range(16, 31):
        fames.append((f"temp_{t}", frame(temp=t)))
    for fa in range(4):
        fames.append((f"fan_{fa}", frame(fan=fa)))
    for w in range(7):
        fames.append((f"wind_{w}", frame(wind=w)))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// auto-generated Xiaomi %s state frames\n" % MODEL)
        fh.write("#pragma once\n#include <stdint.h>\n\n")
        for i, (label, p) in enumerate(fames):
            fh.write(f"static const uint16_t xs_{i}[] = {{{','.join(str(x) for x in p)}}};\n")
        fh.write("\ntypedef struct { const char* label; uint16_t freq; const uint16_t* data; uint16_t len; } xiaomi_state_t;\n")
        fh.write("static const xiaomi_state_t xiaomi_states[] = {\n")
        for i, (label, p) in enumerate(fames):
            fh.write(f'  {{"{label}",{freq},xs_{i},sizeof(xs_{i})/2}},\n')
        fh.write("};\n#define XIAOMI_STATE_COUNT (sizeof(xiaomi_states)/sizeof(xiaomi_states[0]))\n")
    print("wrote", OUT, "frames:", len(fames))


if __name__ == "__main__":
    main()
