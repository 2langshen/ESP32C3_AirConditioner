import json
import xiaomi_gen as xg

SRC = xg.SRC
OUT = r"C:\Users\20121\Desktop\opencode-things\ac_remote\firmware\main\xiaomi_model_8101.h"
MODEL = "kk_3_90_8101"


def parse_table(s):
    ops = []
    i = 0
    while i < len(s):
        ln = int(s[i:i + 2], 16)
        i += 2
        rec = [int(s[i + 2 * k:i + 2 * k + 2], 16) for k in range(ln)]
        i += 2 * ln
        ops.append(rec)  # flat triples
    return ops


def emit_ops(fh, name, table, max_triples):
    fh.write(f"static const m8101_op {name}[{len(table)}] = {{\n")
    for rec in table:
        triples = [rec[j:j + 3] for j in range(0, len(rec), 3)]
        n = len(triples)
        parts = ",".join("{ %d,%d,%d }" % (t[0], t[1], t[2]) for t in triples)
        pad = ",".join("{ 0,0,0 }" for _ in range(max_triples - n)) if max_triples > n else ""
        fh.write("  { %d, { %s%s } },\n" % (n, parts, ("," + pad) if pad else ""))
    fh.write("};\n")


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    o = [x for x in d["data"]["others"] if x["_id"] == MODEL][0]
    key = o["key"]
    f = {int(k): v for k, v in key.items() if isinstance(v, str)}
    freq = int(key.get("frequency", o.get("frequency")) or 38000)
    base = xg.template(f[1002])
    tables = {len(parse_table(f[n])): parse_table(f[n]) for n in (1011, 1012, 1013, 1015) if n in f}
    temp_t = tables[15]
    mode_t = tables[5]
    fan_t = tables[4]
    wind_t = tables[7]
    maxt = max(len(r) // 3 for t in (mode_t, temp_t, fan_t, wind_t) for r in t)
    lead = xg.ints(f.get(300))
    zero = xg.ints(f.get(301))
    one = xg.ints(f.get(302))
    little = 1 if f.get(306) == "1" else 0

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// auto-generated model tables for %s\n#pragma once\n#include <stdint.h>\n\n" % MODEL)
        fh.write("#define M8101_FREQ %d\n" % freq)
        fh.write("#define M8101_BASE_LEN %d\n" % len(base))
        fh.write("static const uint8_t M8101_BASE[%d] = {%s};\n" % (len(base), ",".join("0x%02X" % x for x in base)))
        fh.write("typedef struct { int n; int op[%d][3]; } m8101_op;\n" % maxt)
        emit_ops(fh, "M8101_MODE", mode_t, maxt)
        emit_ops(fh, "M8101_TEMP", temp_t, maxt)
        emit_ops(fh, "M8101_FAN", fan_t, maxt)
        emit_ops(fh, "M8101_WIND", wind_t, maxt)
        fh.write("static const uint16_t M8101_LEAD[] = {%s};\n" % ",".join(str(x) for x in lead))
        fh.write("static const uint16_t M8101_ZERO[] = {%s};\n" % ",".join(str(x) for x in zero))
        fh.write("static const uint16_t M8101_ONE[] = {%s};\n" % ",".join(str(x) for x in one))
        fh.write("#define M8101_LITTLE %d\n" % little)
        fh.write("#define M8101_NMODE %d\n#define M8101_NTEMP %d\n#define M8101_NFAN %d\n#define M8101_NWIND %d\n"
                 % (len(mode_t), len(temp_t), len(fan_t), len(wind_t)))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
