# 业务规则详解

## 1. 请假日期合并规则

### CP年假（Congé Payé）

- **数据来源**：周出勤Sheet中日列(B-H)标记为"CP"的日期
- **合并逻辑**：将连续的CP日期合并为一个起止范围
- **跨周末合并**：如果周五和下周一都是CP，则合并为一个范围（跳过周六日）
- **跨周合并**：如果一周的最后一天和下一周的第一天都是CP，则合并
- **跨节假日合并**：如果CP期间包含7/14国庆假日（标记为"JF"），JF当天不算CP但合并范围不中断
- **多段处理**：不连续的CP段分别填写在不同行
- **日期格式**：import中填写为datetime对象（如 date(2026, 6, 22)）

### CSS事假（Congé Sans Solde）

- **数据来源**：日列标记为"CSS"
- **合并逻辑**：同CP，连续日期合并为起止范围
- **额外字段**："Absence injustifiée"列固定填写"Non"
- **choix列**：固定填写"Journée entière"

### HEURES REPOS调休

- **数据来源**：日列标记为"HEURES REPOS"
- **合并逻辑**：同CP，连续日期合并
- **额外字段**：
  - "Solde à débiter"列固定填写"Contrepartie des heures supplémentaires"
  - "Heures à décompter"列填写调休总小时数 = 天数 × 7
- **choix列**：固定填写"Journée entière"

### RTT

- **数据来源**：日列标记为"rtt"（小写）
- **适用范围**：仅凡哥和Cathy有RTT，且仅Gonesse模板有RTT列
- **合并逻辑**：同CP

---

## 2. 加班规则

### HS 25%（Heures supplémentaires à 25%）

- **数据来源**：周出勤Sheet的P列(HS 1.25)，列号16
- **计算方式**：5个周出勤Sheet的P列值直接累加
- **填写位置**：
  - Gonesse: AD列(30)
  - Nanteuil/SM: Y列(25)

### HS 50%（Heures à 50%）

- **数据来源**：周出勤Sheet的Q列(HS 1.5 Payfit输入)，列号17
- **计算方式**：5个周出勤Sheet的Q列值直接累加得到总和
- **封顶规则**：如果总和 > 25，则填写25；否则填写实际总和
- **填写位置**：
  - Gonesse: AG列(33)
  - Nanteuil/SM: Y列(25)（注意确认实际列位置，可能与HS 25%不同列）
- **重要**：不是每周封顶5h后累加，而是总和后简单封顶25

---

## 3. 7/14公假日（Fériés habituelles）

- **数据来源**：7/14所在周的出勤Sheet中7/14对应列的值
- **规则**：
  - 如果值为"JF"：不填写公假日（该员工当天放假）
  - 如果值为数字（如7、7.0）：填入该数字作为实际出勤工时
  - 如果值为空：不填写
- **填写位置**：
  - Gonesse: AT列(46)
  - Nanteuil/SM: AJ列(36)
- **费率列**：不填写Taux de majoration

---

## 4. Heures d'absence（Ajout d'heures d'absences）

- **数据来源**：月工资合计Sheet（如"06月工资合计"）的H列"RD/ABS总计"
- **规则**：
  - 取H列中所有负数值
  - 将负数取绝对值后填入import的"Heures d'absence"列
  - 正数和零不填写
- **填写位置**：
  - Gonesse: BA列(53)
  - Nanteuil/SM: AQ列(43)
- **注意**：此值不是按AM病假天数×7h计算，而是直接使用月工资合计表中的RD/ABS总计负值
- **列检测注意**：模板中包含"Début CSS/Absence In. (date)"等列，其表头也包含"absence"字样但不能匹配。列检测时必须精确匹配"heures d'absence"，不能仅匹配"absence"关键词，否则会误匹配到CSS相关列（如Col 18）

---

## 5. 不填写字段清单

| 字段 | 原因 |
|------|------|
| Travail du dimanche（周日加班） | 用户确认不需要填写 |
| Titres restaurant（餐票） | 用户确认不需要填写 |
| Primes（奖金，如Prime sur objectif） | 数据不在每周工资计算表中 |
| Transport（交通补贴） | 数据不在每周工资计算表中 |
| Heures à ajouter | 不填写 |
| Télétravail（远程办公） | 不填写 |
| École（学校） | 不填写 |
| Nuit（夜班） | 不填写 |
| 1er mai（五月一日） | 不填写 |
| Congés exceptionnels | 不填写 |
| Heures d'absence injustifiées | 不填写 |
| 所有Taux de majoration列 | 不填写（费率由模板预填或系统自动计算） |

---

## 6. 姓名匹配规则

每周工资计算表和import模板中的员工姓名可能存在以下差异：

### 6.1 大小写差异
- 每周表："Hermione ADJOVI"
- import模板："Reglore Hermione B ADJOVI"
- 匹配方式：包含匹配（一方姓名包含另一方）

### 6.2 姓名顺序反转
- 每周表："Tian Haoran"
- import模板："Haoran TIAN"
- 匹配方式：将姓名拆分为token，反转后比较

### 6.3 简写/全名
- 每周表："Cathy" / "凡哥"
- import模板：全名
- 匹配方式：已知特殊映射表

### 匹配优先级
1. 精确匹配（忽略前后空格）
2. 包含匹配（一方姓名包含另一方）
3. Token反转匹配（将姓名按空格拆分，反转顺序后比较）

---

## 7. 多行处理规则

### 7.1 何时产生多行
同一员工有多个不连续的请假时段时，每个时段占一行。例如：
- Shujun LIN有3段CP → 3行
- Guoqing FAN有4段CP → 4行
- Jie CHEN有CP + 2段Repos → 3行

### 7.2 非请假字段只在第一行填写
以下字段只在员工的第一行数据中填写，其余行留空：
- HS 25%（加班25%）
- HS 50%（加班50%）
- Fériés habituelles（公假日）
- Heures d'absence（缺勤时长）

### 7.3 请假字段按行填写
每行的CP/CSS/Repos日期范围只填写该行对应的请假时段。

### 7.4 行的排列
同一员工的多行连续排列。新增行时复制A列(Identifiant)和D列(姓名)。

---

## 9. 未匹配员工处理规则

### 9.1 不手动添加
- 在每周工资计算表中存在、但未在import模板中找到匹配的员工，**不手动添加到模板中**
- 这些员工的数据保留在解析结果中，但不写入import文件

### 9.2 填写完成后提醒
- 三个import文件全部填写完成后，汇总所有未匹配的员工姓名
- 按地点分类输出提醒，格式示例：
  ```
  ⚠️ 以下员工在每周工资计算表中存在，但未在模板中找到匹配：
  - Gonesse: Yuqiao ZHANG, Jiaqi TONG
  - Nanteuil: Keying JIANG
  请确认是否需要手动添加到模板中。
  ```
- 用户根据提醒自行决定是否添加这些员工到模板

### 9.3 脚本实现
- `fill_template` 函数返回 `(filled_count, unmatched_names)` 元组
- `main` 函数收集三个地点的未匹配员工，在全部完成后统一输出提醒

---

## 10. 验证要点

1. 日期格式正确（datetime对象，非字符串）
2. choix列值为"Journée entière"
3. CSS的Absence injustifiée为"Non"
4. Repos的Solde à débiter为"Contrepartie des heures supplémentaires"
5. Repos的Heures à décompter = 天数 × 7
6. HS 50%不超过25
7. 多行员工的非请假字段只在第一行
8. Travail du dimanche列全部为空
9. Titres restaurant列全部为空
10. Heures d'absence值为月工资合计H列负数的绝对值
11. 7/14标JF的员工Fériés列为空
12. 7/14有出勤的员工Fériés列为实际工时
13. 姓名匹配覆盖所有员工（注意反转匹配）
14. 模板预填的Identifiant/Matricule不被修改
15. 模板预填的taux de majoration不被修改
16. 输出文件名含"(自动生成)"后缀
17. 未匹配员工不手动添加到模板，仅汇总提醒
