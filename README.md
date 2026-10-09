# ESP32-C3 红外空调控制 —— 完整复现文档

用 ESP32-C3 + 红外发射模块控制康佳空调；控制链路支持 **串口 / 本地 MQTT / 局域网 HTTP（Siri 快捷指令）**。

---

## 1. 成果概览

- 能对这块康佳空调实现：**开关、模式（制冷/制热/自动/送风/除湿）、温度 16–30℃、风速、上下风向、睡眠、强力(TURBO)**。
- 三条控制通道：
  1. 串口命令（调试）
  2. 本地 MQTT（`ac/cmd` 收、`ac/state` 报）
  3. 局域网 HTTP（`siri_http.py`），供 **iPhone 快捷指令 / Siri** 调用
- 关键结论：这台空调是**状态型**协议，Xiaomi 万能遥控里对应 **康佳第 2 款 = 型号 `kk_3_90_8101`**；其编码规则从公开码库解密并**在固件里完整合成**（含电源位）。

## 2. 架构

```
Siri/快捷指令 ──HTTP──▶ PC:8080 (siri_http.py) ──MQTT──▶ PC:1883 (minibroker.py)
                                                              │
ESP32-C3 (WiFi) ──MQTT(ac/cmd/ac/state)───────────────────────┘
   │ RMT 38kHz
   ▼
红外发射模块 ──IR──▶ 康佳空调
```

## 3. 目录 / 文件清单

```
ac_remote/
├─ README.md                    本文件（复现总纲）
├─ Siri快捷指令清单.md            Siri 用法说明
├─ Siri快捷指令_批量.txt          名称<Tab>URL 批量清单
├─ codes/                       IRext 抽取的康佳空调码（已 md5 校验）
│   ├─ konka_ac_3557..3561.bin
│   └─ konka_ac_manifest.json
├─ onenet/thing_model.json      OneNET 物模型（备选云端方案）
├─ tools/                       码库解析/解码/生成脚本（见第 6 节）
├─ broker/                      PC 端服务与测试脚本
│   ├─ minibroker.py            极简 MQTT broker（3.1.1+5.0）
│   ├─ siri_http.py             HTTP→MQTT 桥（Siri 用）
│   ├─ acctl.py                 交互式控制终端
│   ├─ send.py / watch.py / ... 自测脚本
│   └─ start_all.ps1            一键启动 broker+桥
└─ firmware/                    ESP-IDF 工程
    ├─ CMakeLists.txt
    ├─ partitions.csv           2MB app 分区
    ├─ sdkconfig.defaults
    ├─ components/irext/        IRext 解码库（C）
    └─ main/
        ├─ main.c               主程序（红外/MQTT/命令/完整状态合成）
        ├─ konka_ac_3557..3561.bin   IRext 康佳码（备选路径）
        ├─ xiaomi_model_8101.h  ★8101 编码表（模式/温度/风速/风向）
        ├─ xiaomi_pats.h        康佳各型号候选帧（搜码用）
        ├─ xiaomi_state_pats.h  单参数功能帧（验证用）
        └─ xiaomi_off_pats.h    关机位扫描候选帧
```

外部依赖仓库（未随包，需要时克隆）：
- `irext/database`、`irext/core`（通用红外码库）
- `CRANkyoldgit` 无关；`halifox/android_xiaomi_ir_lab`、`ysard/mi_remote_database`（小米码库解析）

## 4. 硬件

| 件 | 说明 |
|---|---|
| ESP32-C3 开发板 | 本机实测 QFN32 rev v0.3，4MB Flash |
| 红外发射模块 | 3 脚 `IN/+5V/GND`，MOS 放大+限流，可 3.3V 直驱（1W 940nm） |
| 接线 | 模块 `+5V→5V`、`GND→GND`、`IN→GPIO4`；模块旁加 100–470µF 电容 |
| （可选）VS1838B | 红外接收头，学习原遥控用：`OUT→GPIO10` |

## 5. 环境

- ESP-IDF **v5.5.1**（本机 `C:\esp32\esp\v5.5.1\esp-idf`，工具 `C:\esp32\.espressif`）
- Python：IDF 自带 3.11（编译用）；系统 Python 3.8（脚本用，含 `paho-mqtt`、`pycryptodome`、`lupa`）
- Windows PowerShell

> 坑：本机系统 `python` 是 3.8，IDF 5.5 需 ≥3.9；编译前把 IDF 的 3.11 venv 加到 PATH 最前。

## 6. 完整复现步骤

### 6.0 环境修复（PowerShell）
```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
$env:PATH = "C:\esp32\.espressif\python_env\idf5.5_py3.11_env\Scripts;" + $env:PATH
. "C:\esp32\esp\v5.5.1\esp-idf\export.ps1"
```

### 6.1 通用码库（IRext）路径 —— 抽取康佳空调码
```powershell
git clone --depth 1 https://github.com/irext/database.git
git -C database lfs pull --include="binaries/*" "db/*"
# 查询康佳空调并抽取（tools 脚本）
python tools\query_konka.py         # 列出康佳空调 remote_index（3557..3561）
python tools\extract_codes.py       # 按 md5 校验抽取到 codes\
```
工具：`inspect_db.py`（表结构）、`query_konka.py`、`extract_codes.py`。

> 结论：IRext 的 `new_ac_*` 康佳码**没能控住**本机空调（码型不符），最终改用 Xiaomi 码库路线。

### 6.2 本地 MQTT 打通
```powershell
python broker\minibroker.py 0.0.0.0 1883      # 启动 broker
```
防火墙放行 1883（管理员）：
```powershell
New-NetFirewallRule -DisplayName "ESP MQTT 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow -Profile Any
```
固件连 `mqtt://<PCIP>:1883`，订阅 `ac/cmd`，上报 `ac/state`。

### 6.3 局域网 HTTP（Siri）
```powershell
python broker\siri_http.py                     # 监听 0.0.0.0:8080
New-NetFirewallRule -DisplayName "AC Siri HTTP 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Any
```
一键启动：`powershell -ExecutionPolicy Bypass -File broker\start_all.ps1`

### 6.4 Xiaomi 码库解码 —— 找到并复现 8101
1. 稀疏克隆实验室仓库（含小米资产）：
   ```powershell
   git clone --depth 1 --filter=blob:none --sparse https://github.com/halifox/android_xiaomi_ir_lab.git xiaomi_lab
   git -C xiaomi_lab sparse-checkout set --no-cone "app/src/main/assets/3_AC" "app/src/main/assets/3_AC.json" "app/src/main/java" "docs"
   ```
2. 码库格式（见 `docs/03-air-conditioner.md`）：
   - 固定码：`Base64 → AES-256-ECB(key="fd7e915003168929c1a9b0ec32a60788" ASCII) → 去尾部0x20 → GZIP → JSON int[]`
   - 状态型空调：`1002` 基础模板字节 + 表 `1011温度/1012模式/1013风速/1015风向`(bit 写规则) + `1017` + Lua + 波形 `300/301/302/306`
3. 关键脚本：
   ```powershell
   python tools\parse_konka.py       # 康佳 20 个型号，定位 type=1/type=2
   python tools\decode_type1.py      # type=1 固定码解码
   python tools\state_probe.py       # 8101 表解码实验
   python tools\xiaomi_gen.py        # 生成康佳候选帧 -> firmware/main/xiaomi_pats.h
   python tools\state_gen.py         # 生成 8101 功能帧 -> xiaomi_state_pats.h
   python tools\off_gen.py           # 生成关机位扫描帧 -> xiaomi_off_pats.h
   python tools\model_gen.py         # 生成 8101 编码表 -> xiaomi_model_8101.h
   ```
4. 筛查过程：
   - 用 `xiaomi_pats.h`（各型号 ON 帧）扫描 → **第 2 个 `8101.on` 生效** → 型号锁定 `kk_3_90_8101`。
   - 温度映射修正：表索引 = `温度-16`。
   - 关机位筛查（`off_gen` 逐位翻转）→ **第 5 字节 bit2 = 电源位（1开/0关）**。
   - 睡眠/强力：Lua 里 `exts[22]/exts[8]` → 写第 8 字节低 3 位。

### 6.5 固件编译烧录
```powershell
# 工作目录 firmware\
idf.py set-target esp32c3
idf.py build
idf.py -p COM5 flash
```
凭据放在 `firmware/main/secrets.h`（已 gitignore）。首次构建前执行 `copy firmware\main\secrets.h.example firmware\main\secrets.h` 并填入你自己的 WiFi / MQTT(PC IP)。

## 7. 接口参考

### 7.1 MQTT
- 主题：`ac/cmd`（下发）、`ac/state`（上报）、`ac/try`（扫描进度）
- 载荷：JSON `{"power":1,"mode":0,"temp":26,"fan":0,"wind":0,"sleep":0,"turbo":0}`；也支持简写文本 `on/off/p`、`@<标签>`、`O<序号>`（扫描）

### 7.2 HTTP（`siri_http.py`）
| 功能 | URL |
|---|---|
| 开/关/切换 | `/on` `/off` `/toggle` |
| 模式 | `/mode/cool|heat|auto|fan|dry` |
| 温度 | `/temp/16`…`/temp/30` |
| 风速 | `/fan/0|1|2|3`（0自动1低2中3高） |
| 风向 | `/wind/0`…`/wind/6` |
| 睡眠 | `/sleep`（切换）、`/sleep/0`、`/sleep/1` |
| 强力 | `/turbo`（切换）、`/turbo/0`、`/turbo/1` |
| 状态 | `/state` |
| 原始载荷 | `/raw?p=<payload>`（含 URL 编码 JSON） |
均返回 `OK ...`；示例 `http://192.168.31.32:8080/on`。

### 7.3 串口命令
`p`开关 `m`模式 `+/-`温度 `f`风速 `w`摆风 `i`状态 `o`上报 `g`发基帧 `a`IRext扫 `x`频率×码矩阵 `z`各型号ON `Z`功能帧 `O[序号]`关机位扫描 `@标签`发指定帧 `h`帮助

## 8. 8101 协议要点

- 载波 **38kHz**；帧长 228 个时长；引导 `3000,1600`，逻辑0 `450,1150`，逻辑1 `450,2150`，低位优先，帧尾补一个 `450`。
- 基础模板字节（`1002` 去长度头，14 字节）：
  `23 CB 26 01 00 24 03 07 78 00 00 00 00 BB`（末字节 = 校验和占位）
- 校验：`byte[13] = (sum(byte[0..12])) & 0xFF`
- 电源位：`byte5` bit2（1=开，0=关）
- 表写入（`(start,end,value)` 位，MSB 优先进）：
  - 模式 `1012`：bits[52,56]；其中 送风/除湿 另写 bits[60,62]
  - 温度 `1011`：bits[60,64]，索引 = 温度-16（16→14…30→0 值递减）
  - 风速 `1013`：bits[69,72]
  - 风向 `1015`：bits[66,69]
  - 睡眠：`byte8=(byte8&0xF8)|1`；强力：`|7`（互斥）

## 9. 已知限制

- 该机型的 `Light/Aux Heat/左右风` 及**静音**不在码库脚本可编码范围（需原生 `enc`，未开源）；若原遥控器有静音键，可用扫位法或接收头学习。
- 状态为"设定值"，无空调回读（红外单向）；`ac/state` 反映的是"我们下发的设定"，不是空调真实状态。
- PC 需常开且手机同网；iOS 首次需授权"本地网络"。
- OneNET 云端方案已备好物模型与 MQTT 代码思路，但当前采用本地方案。

## 10. 排错

- 串口打不开/烧不进去：确认 CH340 的 COM 号、关闭其它串口工具。
- 手机打不开 8080：确认同 WiFi、防火墙规则、iOS 本地网络权限；先用手机 Safari 打开 `/state`。
- MQTT 连不上：检查 PC IP、broker 是否运行、1883 是否放行。
- 睡眠/温度不生效：确认用的是 `8101` 路径（`@`/JSON），而不是 IRext 码。

---

## 附：关键复现命令（速查）

```powershell
# 1) 启动 PC 服务
powershell -ExecutionPolicy Bypass -File C:\Users\20121\Desktop\opencode-things\ac_remote\broker\start_all.ps1
# 2) 交互控制
python C:\Users\20121\Desktop\opencode-things\ac_remote\broker\acctl.py
# 3) 重新生成 8101 表并编译（改了码库/表时）
python C:\Users\20121\Desktop\opencode-things\ac_remote\tools\model_gen.py
cd C:\Users\20121\Desktop\opencode-things\ac_remote\firmware
Set-ExecutionPolicy -Scope Process Bypass -Force
$env:PATH = "C:\esp32\.espressif\python_env\idf5.5_py3.11_env\Scripts;" + $env:PATH
. "C:\esp32\esp\v5.5.1\esp-idf\export.ps1"
idf.py -p COM5 flash
```
