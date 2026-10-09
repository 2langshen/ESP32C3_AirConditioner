import json
import xiaomi_gen as xg

SRC = xg.SRC
OUT = r"C:\Users\20121\Desktop\opencode-things\ac_remote\firmware\main\xiaomi_off_pats.h"
MODEL = "kk_3_90_8101"


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    o = [x for x in d["data"]["others"] if x["_id"] == MODEL][0]
    key = o["key"]
    freq = int(key.get("frequency", o.get("frequency")) or 38000)
    cfg = xg.Config(MODEL, key)
    f = cfg.raw
    base = xg.template(f[1002])
    lua = f.get(1522) or f.get(1518)

    def frame(b):
        st = cfg.initial_state()
        st["extras"] = {9: 0, 10: 0, 22: 0}
        b = xg.run_lua(lua, list(b), st, 1)
        return xg.build_wave(f, b)

    frames = []
    for byte in (2, 3, 4, 5, 9, 10, 11, 12, 0, 1, 6, 7, 8, 13):
        for bit in range(8):
            b = list(base)
            b[byte] ^= (1 << bit)
            frames.append((f"b{byte}_{bit}", frame(b)))
    # also a couple of multi-bit toggles
    for byte, mask, name in ((3, 0xFF, "b3_all"), (5, 0xFF, "b5_all"), (4, 0xFF, "b4_all")):
        b = list(base)
        b[byte] ^= mask
        frames.append((name, frame(b)))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// auto-generated candidate OFF frames (single-bit flips) for %s\n" % MODEL)
        fh.write("#pragma once\n#include <stdint.h>\n\n")
        for i, (label, p) in enumerate(frames):
            fh.write(f"static const uint16_t xf_{i}[] = {{{','.join(str(x) for x in p)}}};\n")
        fh.write("\ntypedef struct { const char* label; uint16_t freq; const uint16_t* data; uint16_t len; } xiaomi_off_t;\n")
        fh.write("static const xiaomi_off_t xiaomi_offs[] = {\n")
        for i, (label, p) in enumerate(frames):
            fh.write(f'  {{"{label}",{freq},xf_{i},sizeof(xf_{i})/2}},\n')
        fh.write("};\n#define XIAOMI_OFF_COUNT (sizeof(xiaomi_offs)/sizeof(xiaomi_offs[0]))\n")
    print("wrote", OUT, "frames:", len(frames))


if __name__ == "__main__":
    main()
