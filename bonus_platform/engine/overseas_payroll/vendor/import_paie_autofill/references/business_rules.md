# 业务规则详解

> **本文档已按 2026-08 人工版（`import_variables_paie-202608 {Gonesse,Nanteuil,SM}.xlsx`）
> 逐单元格核对过，与 `scripts/auto_fill_import.py`（v3.1）实现一一对应。**
> 核对结果：SM 完全一致（0 处差异）；Gonesse 33 行、Nanteuil 28 行员工区与人工版逐行对齐，
> 仅剩 2 处人工版超出考勤表的额外记录（见 §11）。

---

## 1. 请假标记与日期合并

### 1.1 数据来源

只有**周出勤Sheet的每日列（B–H，列号 2–8）**里的文本标记才产生请假段。
`parse_weekly_file` 通过 `classify_leave_code()` 归类，匹配规则是**子串**匹配（不区分大小写）：

| 日列文本 | 归类 | 说明 |
|---------|------|------|
| `CP` | `cp` | 年假（严格等于，不按子串） |
| 含 `css` | `css` | 事假 Congé Sans Solde |
| 含 `repos` | `repos` | 调休（源表写作 `HEURES REPOS` / `HEURE REPOS` 等） |
| 含 `rtt` | `rtt` | RTT |

以下标记**不产生请假段**（`classify_leave_code` 返回 None）：
`JF`（当天放假，见 §3）、`AM`、`AT`、`ABS`、`0`、纯数字工时、其他文本。
也就是说 AM/AT 病假不会写进 import —— 病假/缺勤通过 §4 的 `Heures d'absence` 整月汇总体现，
不在 import 里逐日登记。

### 1.2 合并规则（`merge_consecutive_dates`）

同一类型的天数先按日期排序去重，然后：

- **相邻日合并**：`d == prev + 1 天` → 并入同一段。
- **跨周末/节假日合并**：与上一日间隔 ≤ 3 天，且**中间所有被跳过的日期**
  都是周六/周日或 2026 法定节假日 → 仍并入同一段。
  例：Fri 08-14 → Mon 08-17（跳过 Sat/Sun）合并为一段；
  Thu 08-13 → Mon 08-17（跳过 Fri 工作日）**不**合并，拆成两段。
- 其余情况断段。

合并结果是一组 `(开始日, 结束日)` 区间。经 202608 验证：
连续 3 周（08-03~08-21，中间只隔周末）的事假会被合并成**单段** `08-03 ~ 08-21`，
人工版同样只写一条，所以跨多周合并是正确行为，不要按周拆分。

### 1.3 各类型的附加字段

| 类型 | 写入列 | 固定值 |
|------|--------|--------|
| 全部类型 | Début / Fin 的 `(date)` 列 | 该段的开始日 / 结束日（datetime） |
| 全部类型 | Début / Fin 的 `(choix)` 列 | `Journée entière` |
| CSS | `Absence injustifiée` | `Non` |
| Repos | `Solde à débiter` | `Contrepartie des heures supplémentaires` |

**`Heures à décompter`（Repos 调休小时数）不填写** —— 人工版三个主体该列全空，
v2 曾按「天数 × 7」填写，属错误规则，已删除。

---

## 2. 加班（Heures supplémentaires）

### 2.1 数据来源与回退

- **主来源**：周出勤Sheet 的 **P 列（列号 16，HS 1.25）** 与 **Q 列（列号 17，HS 1.5 Payfit输入）**，
  多个周出勤Sheet 的数值**直接累加**。
- **回退**：周出勤Sheet 里完全没有该员工时（如整月缺勤/只在月表出现），
  取**月工资合计的 D 列（HS 1.25）/ E 列（HS 1.5）**。
- 经 202608 全员工对照，周表累加值与月表 D/E **完全一致**（仅 2 人周表无行，且月表 D/E 均为 0），
  两套口径互为印证。

### 2.2 封顶

- **HS 25%：不封顶**，累加值原样填入。
- **HS 50%：封顶 = 周数 × 5**（周数 = 周出勤Sheet 个数；4 周 = 20h，5 周 = 25h）。
  是「累加后整体封顶」，**不是**「每周封顶 5h 再累加」。
  触发封顶时会在日志里打印 `[封顶] 姓名: 原始 x -> 封顶 y`。

### 2.3 实习生例外

月工资合计 **Q 列「人员类型」= `实习生`** 的人：**既不填 HS，也不填 Type de rémunération**
（人工版即如此，实习生加班费按其他方式处理）。此时会写入一条 `warnings` 提示，
把源表里的加班小时数报出来，便于人工复核。

### 2.4 Type de rémunération

只要最终 HS25 或 HS50 有值（> 0），就在该员工**第一行**写
`Type de rémunération = Paiement des heures supplémentaires`。

---

## 3. 公休（Fériés habituelles）

- 节假日集合 = `FRENCH_HOLIDAYS_2026`（1/1、4/6、5/1、5/8、5/14、5/25、7/14、8/15、11/1、11/11、12/25）。
- 只有在「当天的日期属于节假日**且**该员工当天的单元格是**数值 > 0**」时才填。
- 填入值 = 节假日当天所有实际出勤工时的**合计**（写在该员工第一行）。
- 当天标 `JF`（放假）或为空 → 不填。
- 费率列（`Taux de majoration fériés` 等）不动。

---

## 4. Heures d'absence（缺勤时长）

- 来源：月工资合计 **H 列「RD/ABS总计」**。
- 只取**负数值**，取绝对值后填入。
- 正数、0、空 → 不填。
- 不是「病假天数 × 7」，直接使用月表的汇总值。
- **列检测注意**：模板里 `Début CSS/Absence In. (date)` 等列的表头也含 `absence`，
  必须精确匹配 `heures d'absence`，否则会误匹配到 CSS 列（v3 已按精确文本处理）。

---

## 5. 周日 / 奖金区块

人工版**不填** `Travail du dimanche habituel / exceptionnel / Nombre de dimanches travaillés`
这三列，改为在 **Prime 区块**登记周日奖金：

| Prime 区块列 | 写入值 |
|-------------|--------|
| `Type de prime (conventionnelle ou non)` | `Prime de dimanche` |
| `Nom de la prime` | `Prime de dimanche` |
| `Montant` | 月工资合计 **K 列（周日奖金）** |
| `Date de début de versement` | 当月 1 日（由源表文件名推导的年月） |
| `Fréquence` | `une seule fois` |

- 写入位置 = 该员工**第一个未被他人 prime 占用的行**；该员工所有行都被占用时追加新行。
- **已存在的他人 prime 行不动**：若某行 `Type de prime` 有值且不等于 `Prime de dimanche`
  （典型是 `Prime sur objectif` 绩效奖金），该行的整个 prime 区块一律保留、不覆盖、不清空。
- 月表有周日奖金但模板没有 `Type de prime` 列 → 不填，写入 `warnings`。

---

## 6. 保留不动的区块

| 区块 | 处理 |
|------|------|
| `Titres restaurant`（餐票） | **完全不动**。该区块由模板预置（`Gérer les titres` / `Valeur du titre` / `Gestion du nombre` / `Part payée par l'employeur` 等，少量人员预填 `Non` + 8€ / 4.32€ / `Automatique`）。v2 会先清空，等于把模板预置信息抹掉，v3 起不再触碰。月表 L 列「补餐票」当前**只读取不写入**。 |
| `Prime sur objectif` 等他人奖金行 | 保留（见 §5） |
| `Taux de majoration` 等费率列 | 保留，模板预填或 Payfit 自动算 |
| `Transport`（交通） | 保留 |
| A/B/C/D 列（Identifiant / Compte analytique / Matricule / Collaborateur） | 模板预填，绝不修改（追加行时复制过去） |

---

## 7. 行的分配（槽位模型）

> v3.1 修正。v3 及更早版本把一名员工所有类型的请假段混在一起按 `(类型, 开始日)` 排序，
> 每段占一行，结果 CP/CSS/Repos 被排到不同行、段数一多还额外追加行。**这是错的。**

正确规则（人工版实测）：

- **第 i 行同时承载 CP 的第 i 段、CSS 的第 i 段、Repos 的第 i 段、RTT 的第 i 段**
  —— 各类型占用的是不同列，互不冲突，一行可以同时是「CP + CSS + Repos」。
- 槽位数 = `max(各类型段数)`。只有当某类型的段数**超过该员工在模板中已有的行数**时，
  才从员工区末尾游标追加新行（复制 A–D 列与该行样式）。
- **非请假字段只写第一行**：HS 25%、HS 50%、`Type de rémunération`、Fériés、Heures d'absence、
  周日奖金（周日奖金写第一个未被他人 prime 占用的行，见 §5）。

202608 实测证据：

| 员工 | 源表考勤 | 人工版 | v3 旧逻辑 |
|------|---------|--------|----------|
| Yu-Tzu Liao | CP 08-03；CSS 08-14 | 两段同在第 **20** 行 | CP 在第 20 行，CSS 被推到追加的第 36 行 ✗ |
| Sabil BARKATI | CP#0 = 07-30~08-04，CSS#0 = 08-05~08-07，CSS#1 = 08-14 | 第 **3** 行 = CP#0+CSS#0，第 **4** 行 = CSS#1 | CSS#0 落到第 4 行，CSS#1 被推到追加行 ✗ |
| Qiyu WANG | Repos 08-11 | Repos 与 CP#0 同在第 **25** 行 | Repos 被推到追加的第 32 行 ✗ |

注意源表姓名拼写可能与模板不同（如源表 `Yu-tzu LIAO` vs 模板 `Yu-Tzu Liao`），
姓名比对一律走 `normalize_name`（小写 + 去多余空格），不要用大小写敏感的比较。

---

## 8. 姓名匹配规则

`match_employee(weekly_name, template_names)` 的优先级：

1. **归一化精确匹配**：小写 + 去首尾空格 + 合并双空格后完全相等。
2. **包含匹配**：一方姓名包含另一方（处理 `Hermione ADJOVI` vs `Reglore Hermione B ADJOVI`）。
3. **token 集合相等**：按空格拆分后排序比较（处理 `Tian Haoran` vs `Haoran TIAN`）。
4. **token 交集 ≥ 2 且一方被另一方覆盖**：宽松兜底。

已识别的差异类型：
- 大小写：`Yu-tzu LIAO` / `Yu-Tzu Liao`
- 顺序反转：`Tian Haoran` / `Haoran TIAN`
- 简写 / 中文昵称：`Cathy` / `凡哥` 这类无法靠字符串匹配的，**脚本不猜**，会落到「未匹配」提醒里。

**同名预警**：模板中若出现两个同名员工，会写入 `warnings`（按姓名匹配可能串行，需人工确认）。

---

## 9. 员工区边界与残留行

- 员工区 = **第 3 行起连续的 ObjectId 段**（允许 ≤ 3 个空行）。
  **不能**用 `ws.max_row` 扫描 —— 模板样式把 `max_row` 撑到 5000+，
  历史版本用 `ws.max_row + 1` 追加行留下的孤儿行会被误当成员工。
- 追加行从「员工区最后一行的下一行」游标开始，不从 `max_row + 1` 开始。
- 员工区之外、ObjectId 已在员工区出现过的**残留行**（202608：Gonesse 5108–5110、
  Nanteuil 5094–5101、SM 5099–5101）会被清理掉工具负责的列，并写入 `warnings`。
- 员工区之外出现**未知** ObjectId 的行 → 保留不动，只写 `warnings` 提示。

---

## 10. 未匹配员工处理规则

- 每周工资计算表里有、但三个模板都没有的员工（202608：`Jiaqi TONG`、`Yuqiao ZHANG`）：
  **不手动添加到模板**，只在 `report['source_extra']` 里汇总。
- 模板里有、源表没有的员工：正常现象（新入职/离职/整月无数据），保持空白即可，
  记在 `report['template_missing']`，**不算错误**。
- 202608 实测 `template_missing` 为空集合，没有出现「模板有人却没匹配上」的假阴性。

---

## 11. 人工版超出考勤表的记录（工具无法推导，属正常残留）

202608 核对后仅剩 2 处差异，都是人工版在考勤表之外做的决定，
**不要试图用规则去复现**，保持原样输出并在交付时向业务说明即可：

1. **Tingting MAN（Gonesse 第 23 行）**
   源表两周每日标记都是 `CP`（07-27~07-31 与 08-03~08-07），
   人工版把第一周改成了 `Repos 07-27~07-31`（`Solde à débiter = Contrepartie des heures supplémentaires`），
   并把 HS25 从源表的 **11.82** 改成 **10.69**。
   源表周表 P 列累加 = 11.82，月表 D 列也 = 11.82，两处一致；
   人工版的 10.69 没有任何单元格数据支撑，属人工调账（疑似用掉调休抵扣加班）。

2. **Shasha LIU（Nanteuil 第 13 行）**
   源表 CSS 覆盖 08-03~08-07 / 08-10~08-14 / 08-17~08-21，按 §1.2 合并为单段 08-03~08-21
   （人工版第 12 行同样是这一条，工具输出与之完全一致）。
   人工版第 13 行**额外**又写了一条 `CSS 08-17~08-23`，与第 12 行自身重叠；
   08-22/08-23 在源表是周末且标记为 `0`，不是 CSS。
   该行是人工重复录入，Payfit 侧会造成 08-17~08-21 重复扣假，建议业务侧复核。

---

## 12. 验证要点（202608 核对清单）

1. 日期为 datetime 对象（非字符串），`choix` 列 = `Journée entière`
2. CSS 的 `Absence injustifiée` = `Non`；Repos 的 `Solde à débiter` = `Contrepartie des heures supplémentaires`
3. `Heures à décompter` 全表为空（不填）
4. HS 50% ≤ 周数 × 5；HS 25% 不封顶
5. `人员类型 = 实习生` 的人 HS 与 `Type de rémunération` 均为空
6. 多行员工的非请假字段（HS / Fériés / Heures d'absence / Type de rémunération）只在第一行
7. 同一员工的 CP#i / CSS#i / Repos#i 落在同一行（§7 槽位模型）
8. `Travail du dimanche` 三列为空；周日奖金写在 Prime 区块
9. `Titres restaurant` 区块与模板原值一致（未被清空）
10. `Prime sur objectif` 等他人 prime 行未被覆盖
11. Heures d'absence = 月表 H 列负数的绝对值
12. 节假日标 `JF` 的人 Fériés 列为空；有实际工时的人为实际工时
13. 模板预填的 Identifiant / Matricule / taux de majoration 未被修改
14. 员工区之外没有本工具追加的孤儿行；历史残留行已清理并出现在 `warnings`
15. 输出文件名含 `(自动生成)` 后缀
16. `report['source_extra']` 已列出源表有、模板无的员工（不自动添加）
