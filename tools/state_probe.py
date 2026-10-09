import json
import xiaomi_gen as xg

SRC = xg.SRC


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
    o = [x for x in d["data"]["others"] if x["_id"] == "kk_3_90_8101"][0]
    key = o["key"]
    cfg = xg.Config("kk_3_90_8101", key)
    f = cfg.raw
    tables = {}
    for name in (1011, 1012, 1013, 1015):
        if name in f:
            t = parse_table(f[name])
            tables[len(t)] = (name, t)
            print(name, "entries", len(t), t[:3])
    base = xg.template(f[1002])
    print("base bytes:", [hex(x) for x in base])

    # guess: 15->temp, 5->mode, 4->fan, 7->wind
    temp_t = tables.get(15, (None, None))[1]
    mode_t = tables.get(5, (None, None))[1]
    fan_t = tables.get(4, (None, None))[1]
    wind_t = tables.get(7, (None, None))[1]

    def frame(mode=None, temp=None, fan=None, wind=None):
        b = list(base)
        if mode is not None and mode_t: apply_op(b, mode_t[mode])
        if fan is not None and fan_t: apply_op(b, fan_t[fan])
        if wind is not None and wind_t: apply_op(b, wind_t[wind])
        if temp is not None and temp_t:
            idx = 30 - temp
            apply_op(b, temp_t[idx])
        st = cfg.initial_state()
        st["extras"] = {9: 0, 10: 0, 22: 0}
        b = xg.run_lua(f.get(1522) or f.get(1518), b, st, 1)
        return xg.build_wave(f, b), b

    for label, kw in [
        ("default", {}),
        ("mode_cool", dict(mode=0)),
        ("mode_heat", dict(mode=1)),
        ("mode_auto", dict(mode=2)),
        ("mode_fan", dict(mode=3)),
        ("mode_dry", dict(mode=4)),
        ("temp_30", dict(temp=30)),
        ("temp_16", dict(temp=16)),
        ("fan_1", dict(fan=1)),
        ("wind_3", dict(wind=3)),
    ]:
        pat, b = frame(**kw)
        print(f"{label:10s} bytes={[hex(x) for x in b]} len={len(pat)}")


if __name__ == "__main__":
    main()
