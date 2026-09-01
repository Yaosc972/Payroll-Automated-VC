# 列位置对照表

## 每周工资计算表 — 周出勤Sheet

5个周出勤Sheet的列结构一致，名称格式为 `DD.MM-DD.MM出勤情况` 或 `DD.MM-DD.MM周出勤情况`。

### 行结构

| 行 | 内容 |
|----|------|
| 行1 | 日期（B-H列为当周每天的日期，datetime对象） |
| 行2 | 星期几（Lundi/Mardi/Mercredi/Jeudi/Vendredi/Samedi/Dimanche） |
| 行3+ | 员工数据，A列=姓名 |

### 列位置

| 列 | 列号 | 内容 |
|----|------|------|
| A | 1 | 员工姓名 |
| B | 2 | 周一出勤/请假标记 |
| C | 3 | 周二出勤/请假标记 |
| D | 4 | 周三出勤/请假标记 |
| E | 5 | 周四出勤/请假标记 |
| F | 6 | 周五出勤/请假标记 |
| G | 7 | 周六出勤/请假标记 |
| H | 8 | 周日出勤/请假标记 |
| N | 14 | HS FINAL（加班最终值） |
| O | 15 | HS OEHR |
| P | 16 | HS 1.25（加班25%原始值） |
| Q | 17 | HS 1.5 Payfit输入（加班50%原始值） |
| S | 19 | CP天数 |
| T | 20 | DIMANCHE（周日加班天数） |
| AA | 27 | 地点（部分Sheet） |
| AB | 28 | 地点（第一个Sheet 22.06-28.06） |

### 每日列中的请假代码

| 代码 | 含义 |
|------|------|
| CP | 年假（Congé Payé） |
| CSS | 事假（Congé Sans Solde） |
| HEURES REPOS | 调休 |
| rtt | 补工作时间假（仅凡哥和Cathy） |
| AM | 病假（Arrêt Maladie） |
| AT | 病假（Accident de Travail） |
| JF | 公假（Jour Férié，国庆节等） |
| ABS | 缺勤 |
| 数字 | 正常出勤工时（如7、7.0等） |

---

## 每周工资计算表 — 月工资合计Sheet

Sheet名称格式为 `MM月工资合计`（如 `06月工资合计`）。

### 列位置

| 列 | 列号 | 内容 |
|----|------|------|
| A | 1 | 地点 |
| B | 2 | 员工姓名 |
| H | 8 | RD/ABS总计（需取负数的绝对值填入import的Heures d'absence） |

---

## import模板 — Gonesse

Sheet名：`Page 1`

### 行结构

| 行 | 内容 |
|----|------|
| 行1 | 大类标题（可为空） |
| 行2 | 字段名 |
| 行3+ | 员工数据（D列=姓名，可能有多行） |

### 列位置

| 列 | 列号 | 字段名 | 填写规则 |
|----|------|--------|---------|
| A | 1 | Identifiant | 模板预填，不修改 |
| B | 2 | Compte analytique | 模板预填，不修改 |
| C | 3 | Matricule | 模板预填，不修改 |
| D | 4 | Collaborateur（姓名） | 模板预填，不修改 |
| E | 5 | CP — Date de début | CP开始日期 |
| F | 6 | CP — Choix | 固定"Journée entière" |
| G | 7 | CP — Date de fin | CP结束日期 |
| H-I | 8-9 | CP —相关 | 不填写 |
| J | 10 | CSS — Date de début | CSS开始日期 |
| K | 11 | CSS — Choix | 固定"Journée entière" |
| L | 12 | CSS — Date de fin | CSS结束日期 |
| M | 13 | CSS — Absence injustifiée | 固定"Non" |
| N-O | 14-15 | RTT | RTT开始/结束日期（仅凡哥和Cathy） |
| P-Q | 16-17 | RTT — Choix/Solde | RTT相关 |
| R | 18 | HEURES REPOS — Date de début | 调休开始日期 |
| S | 19 | HEURES REPOS — Choix | 固定"Journée entière" |
| T | 20 | HEURES REPOS — Date de fin | 调休结束日期 |
| U | 21 | HEURES REPOS — Solde à débiter | 固定"Contrepartie des heures supplémentaires" |
| V | 22 | HEURES REPOS — Heures à décompter | 调休小时数（天数×7） |
| W | 23 | HEURES REPOS — Taux de majoration | 不填写 |
| X-AC | 24-29 | 其他调休字段 | 不填写 |
| AD | 30 | Heures supplémentaires à 25% (h) | HS 25%加班（P列5周累加） |
| AE | 31 | Taux de majoration 25% | 不填写 |
| AF | 32 | Heures à 25% — Heures à payer | 不填写 |
| AG | 33 | Heures à 50% (h) | HS 50%加班（Q列5周总和，封顶25） |
| AH | 34 | Taux de majoration 50% | 不填写 |
| AI | 35 | Heures à 50% — Heures à payer | 不填写 |
| AJ | 36 | Heures à 50% — majoration | 不填写 |
| AK | 37 | Travail du dimanche habituel (h) | 不填写 |
| AL | 38 | Taux de majoration dimanche habituel | 不填写 |
| AM | 39 | Travail du dimanche exceptionnel (h) | 不填写 |
| AN | 40 | Taux de majoration dimanche exceptionnel | 不填写 |
| AO | 41 | Nombre de dimanches travaillés | 不填写 |
| AP | 42 | Heures à ajouter | 不填写 |
| AQ | 43 | Heures de nuit | 不填写 |
| AR | 44 | École | 不填写 |
| AS | 45 | 1er mai | 不填写 |
| AT | 46 | Fériés habituelles (h) | 7/14公假日（有出勤填实际工时，JF不填） |
| AU | 47 | Taux de majoration fériés | 不填写 |
| AV | 48 | Heures fériés à payer | 不填写 |
| AW | 49 | Heures fériés à payer majoration | 不填写 |
| AX | 50 | Congés exceptionnels | 不填写 |
| AY | 51 | Heures d'absence (injustifiées) | 不填写 |
| AZ | 52 | Primes — fixed | 不填写 |
| BA | 53 | Heures d'absence | 月工资合计H列负数绝对值 |
| BB | 54 | Taux de majoration absence | 不填写 |
| BC-BD | 55-56 | Absence相关 | 不填写 |
| BE | 57 | Transport — montant | 不填写 |
| BF | 60 | Transport — Frequence | 不填写 |
| BG | 59 | Titres restaurant — Gérer | 不填写 |
| BH | 60 | Titres restaurant — Frequence | 不填写 |
| BI | 61 | Titres restaurant — Nombre | 不填写 |
| BJ | 62 | Titres restaurant — Montant | 不填写 |
| BK-BM | 63-65 | Titres restaurant相关 | 不填写 |
| BN-BQ | 66-69 | 其他餐票字段 | 不填写 |

---

## import模板 — Nanteuil / SM

Sheet名：`Page 1`

Nanteuil和SM模板结构完全一致，但与Gonesse不同。

### 列位置

| 列 | 列号 | 字段名 | 填写规则 |
|----|------|--------|---------|
| A | 1 | Identifiant | 模板预填，不修改 |
| B | 2 | Compte analytique | 模板预填，不修改 |
| C | 3 | Matricule | 模板预填，不修改 |
| D | 4 | Collaborateur（姓名） | 模板预填，不修改 |
| E | 5 | CP — Date de début | CP开始日期 |
| F | 6 | CP — Choix | 固定"Journée entière" |
| G | 7 | CP — Date de fin | CP结束日期 |
| H | 8 | CSS — Date de début | CSS开始日期 |
| I | 9 | CSS — Choix | 固定"Journée entière" |
| J | 10 | CSS — Date de fin | CSS结束日期 |
| K | 11 | CSS — Absence injustifiée | 固定"Non" |
| L | 12 | HEURES REPOS — Date de début | 调休开始日期 |
| M | 13 | HEURES REPOS — Choix | 固定"Journée entière" |
| N | 14 | HEURES REPOS — Date de fin | 调休结束日期 |
| O | 15 | HEURES REPOS — Solde à débiter | 固定"Contrepartie des heures supplémentaires" |
| P | 16 | HEURES REPOS — Heures à décompter | 调休小时数（天数×7） |
| Q | 17 | HEURES REPOS — Taux de majoration | 不填写 |
| R-X | 18-24 | 其他调休字段 | 不填写 |
| Y | 25 | Heures supplémentaires à 25% (h) | HS 25%加班（P列5周累加） |
| Z | 26 | Taux de majoration 25% | 不填写 |
| AA | 27 | Heures à 25% — Heures à payer | 不填写 |
| AB | 28 | Heures à 25% — majoration | 不填写 |
| ... | | | |
| Y | 25 | Heures à 50% (h) | 注意：Nanteuil/SM中HS50%在Y列(25)而非AG列 |

> **重要差异**：Gonesse和Nanteuil/SM模板的列位置不同！
> - Gonesse: HS 25%=AD(30), HS 50%=AG(33), Fériés=AT(46), Heures d'absence=BA(53)
> - Nanteuil/SM: HS 25%=Y(25), HS 50%=Y(25), Fériés=AJ(36), Heures d'absence=AQ(43)
>
> 编写脚本时必须根据模板类型使用不同的列位置映射。脚本 `auto_fill_import.py` 中已通过 `COLUMN_MAP` 字典处理此差异。

### Nanteuil/SM 关键列速查

| 字段 | 列号 | 列字母 |
|------|------|--------|
| CP开始 | 5 | E |
| CP结束 | 7 | G |
| CSS开始 | 8 | H |
| CSS结束 | 10 | J |
| CSS Absence injustifiée | 11 | K |
| Repos开始 | 12 | L |
| Repos结束 | 14 | N |
| Repos Solde à débiter | 15 | O |
| Repos Heures à décompter | 16 | P |
| HS 25% | 25 | Y |
| HS 50% | 25 | Y |
| Fériés habituelles | 36 | AJ |
| Heures d'absence | 43 | AQ |

> 注意：Nanteuil/SM模板中HS 25%和HS 50%可能共用同一列区域，需确认实际表头。以脚本中的COLUMN_MAP为准。
