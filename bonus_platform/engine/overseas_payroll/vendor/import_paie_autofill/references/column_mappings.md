# 列位置对照表

> **重要：模板列位置一律用表头文本动态检测，禁止硬编码列号。**
> 不同月份 / 不同主体的模板列数并不一致（例如 202605 空白 Gonesse 模板比 202608 多出
> 2 列 `Heures complémentaires à 10%/25%`）。早期版本用过的 `COLUMN_MAP` 硬编码字典
> **已被删除**，下文的「实测列号」只作为人工核对时的参考，脚本不依赖它们。

---

## 1. 每周工资计算表 — 周出勤Sheet

Sheet 名包含 `出勤情况`，一个月有 4~5 个（202608 是 4 个：`27.07-02.08出勤情况`、
`03.08-09.08周出勤情况`、`10.08-16.08周出勤情况`、`17.08-23.08出勤情况`）。
每张 Sheet = 一周，列结构一致。

### 行结构

| 行 | 内容 |
|----|------|
| 行1 | 日期（B–H 列 = 本周 7 天的公历日期） |
| 行2 | 星期几（Lundi…Dimanche） |
| 行3+ | 员工数据，**A 列 = 姓名** |

### 脚本使用的列（其余列为周内汇总/校验列，脚本不读）

| 列 | 列号 | 内容 |
|----|------|------|
| A | 1 | 员工姓名 |
| B–H | 2–8 | 周一~周日的逐日单元格：`CP` / `CSS` / `HEURES REPOS` / `rtt` / `JF` / 数字工时 / `0` |
| P | 16 | `HS 1.25` —— HS 25% 原始值 |
| Q | 17 | `HS 1.5 Payfit输入` —— HS 50% 原始值 |

> 列 11 的周汇总列 `HEURE REPOS` **不参与**请假段识别 —— 请假日只从 B–H 逐日单元格读，
> 因为需要日期来归并区间。
> 周出勤Sheet **不提供地点**，地点一律取月工资合计 A 列。

### 逐日列里的文本与处理

| 文本 | 归类 | 处理 |
|------|------|------|
| `CP` | 年假 | 归并成段 → CP 区块 |
| 含 `css` | 事假 | 归并成段 → CSS 区块 |
| 含 `repos` | 调休 | 归并成段 → Repos 区块 |
| 含 `rtt` | RTT | 归并成段 → RTT 区块 |
| `JF` | 公假 | 不填 Fériés（当天放假） |
| `AM` / `AT` / `ABS` | 病假/缺勤 | **不逐日登记**，由月表 H 列整月汇总体现 |
| 数字（`7`、`6.68`…） | 出勤工时 | 仅当该日是法定节假日时用于 Fériés |

匹配为**不区分大小写的子串**匹配（`CP` 例外，要求严格相等），详见 `business_rules.md` §1。

---

## 2. 每周工资计算表 — 月工资合计Sheet

Sheet 名包含 `工资合计`（如 `08月工资合计`）。

| 列 | 列号 | 内容 | 用途 |
|----|------|------|------|
| A | 1 | 地点 | 判定员工归属 Gonesse / Nanteuil / SAINT-MARD；**为空的行直接跳过** |
| B | 2 | 员工姓名 | 员工主键（配合 P 列全名匹配） |
| D | 4 | 加班工时 1.25 | 周表无此人时回退；与周表 P 累加值交叉验证 |
| E | 5 | 加班工时 1.5 Payfit输入 | 同上 |
| H | 8 | RD/ABS总计 | **负值**取绝对值 → `Heures d'absence` |
| J | 10 | 周日天数 | 校验用（周日奖金有金额但无天数时提示） |
| K | 11 | 周日奖金 | → Prime 区块 `Montant` |
| L | 12 | 补餐票 | 仅读取，当前不写入（餐票区块由模板维护） |
| P | 16 | 全名 | 姓名匹配辅助（周表用简称时兜底） |
| Q | 17 | 人员类型 | `实习生` → 不填 HS 与 Type de rémunération |

垃圾行过滤（`_is_junk_name`）：姓名为空、含 `/`、或不含任何拉丁字母的备注行一律跳过。

---

## 3. import 模板 — 行结构

Sheet 名 `Page 1`。

| 行 | 内容 |
|----|------|
| 行1 | 分组带（如 `Ajout de congés payés`、`Ajout d'heures supplémentaires`） |
| 行2 | **字段名表头 —— 列检测的唯一依据** |
| 行3+ | 员工数据：**A 列 = 24 位十六进制 ObjectId**，**D 列 = 姓名** |

同一员工的多行在 A 列重复出现该 ObjectId，连续排列。员工区 = 从第 3 行起的连续 ObjectId 段。

### 列检测规则（`detect_columns`）

| 逻辑列 | 检测方式 |
|--------|---------|
| `cp_start` / `cp_end` | 表头同时含 `cp` + `début` / `cp` + `fin` |
| `cp_start_choix` / `cp_end_choix` | 再叠加 `choix` |
| `css_*` | 同 CP，关键词换成 `css` |
| `css_injustifiee` | **不含 `css`**！用 `absence` + `injustifiée` 检测 |
| `repos_*` | 同类，关键词 `repos` |
| `repos_solde` | **表头不含 `repos`**！用 `solde à débiter` 检测（v2 曾因此完全填不进这一列） |
| `hs_25` | 含 `25%` 且**不含** `50%` |
| `hs_50` | 含 `50%` |
| `type_remu` | `type de rémunération` |
| `feries` | `fériés` + `habituelles` |
| `heures_absence` | **精确**匹配 `heures d'absence`（否则会误命中 `Début CSS/Absence In.`） |
| `dim_hab` / `dim_exc` / `dim_nb` | `dimanche` + `habituel` / `exceptionnel` / `nombre` |
| `prime_type` | `type de prime` |
| `prime_name` / `prime_amount` / `prime_date` / `prime_freq` / `prime_end` | 以 `prime_type` 为锚点向右扫描同组列：`nom de la prime` / 以 `montant` 开头 / `date de début de versement` / 以 `fréquence` 开头 / 以 `date de fin` 开头 |
| `titre_*` | `gérer les titres` / `valeur du titre` / `gestion du nombre` / `nombre de titres` / `part payée par l'` —— **只统计不修改** |

若 `required` 里的列（CP/CSS/Repos 的起止、HS25%、HS50%、Fériés、Heures d'absence、
Type de rémunération、Solde à débiter）检测不到，会在日志打印
`WARNING: 以下列未检测到: [...]`，请先核对模板是否换了表头写法。

---

## 4. 202608 实测列号（仅供人工核对，脚本不依赖）

### Gonesse

| 字段 | 列号 | 列字母 |
|------|------|--------|
| CP 起 / 起choix / 止 / 止choix | 5 / 6 / 7 / 8 | E / F / G / H |
| CSS `Absence injustifiée` | 17 | Q |
| CSS 起 / 起choix / 止 / 止choix | 18 / 19 / 20 / 21 | R / S / T / U |
| Repos 起 / 起choix / 止 / 止choix / `Solde à débiter` | 22 / 23 / 24 / 25 / 26 | V / W / X / Y / Z |
| HS 25% | 32 | AF |
| HS 50% | 33 | AG |
| Type de rémunération | 34 | AH |
| Fériés habituelles | 44 | AR |
| Heures d'absence | 51 | AY |
| Prime — `Type de prime` / `Montant` | 52 / 57 | AZ / BE |

### Nanteuil / SM（两者结构一致）

| 字段 | 列号 | 列字母 |
|------|------|--------|
| CP 起 / 起choix / 止 / 止choix | 5 / 6 / 7 / 8 | E / F / G / H |
| CSS `Absence injustifiée` | 13 | M |
| CSS 起 / 起choix / 止 / 止choix | 14 / 15 / 16 / 17 | N / O / P / Q |
| Repos 起 / 起choix / 止 / 止choix / `Solde à débiter` | 18 / 19 / 20 / 21 / 22 | R / S / T / U / V |
| HS 25% | 24 | X |
| HS 50% | 25 | Y |
| Type de rémunération | 26 | Z |
| Fériés habituelles | 36 | AJ |
| Heures d'absence | 43 | AQ |
| Prime — `Type de prime` / `Montant` | 44 / 49 | AR / AV |

> **Gonesse 与 Nanteuil/SM 的列位置完全不同**（列数、区块顺序都不一样），
> 这正是必须按表头文本检测的原因。
>
> ⚠️ **已作废的错误记载**（旧版本本文档写过，特此更正）：
> - ❌「Nanteuil/SM 的 HS 25% 和 HS 50% 共用 Y 列(25)」—— 实测 HS25%=24(X)、HS50%=25(Y)，两列不同。
> - ❌「Gonesse HS 25%=AD(30)、HS 50%=AG(33)、Fériés=AT(46)、Heures d'absence=BA(53)」——
>   这些是老月份模板的列号，202608 已不同；**不要沿用**。
> - ❌「模板列位置通过 `COLUMN_MAP` 字典映射」—— 该字典不存在，用表头文本检测。
