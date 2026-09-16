# FBU 上月考勤保存超时修复（待发布）

## 问题及证据

- 活动：`556722ff`，202608 新泽西区。
- 生产日志：2026-09-16 19:10–19:12（北京时间），`sigma_fbu_commit_snapshot` 报 `canceling statement due to statement timeout`。不是 Excel 格式错误。
- `authenticator` 的 statement timeout 为 8 秒。大考勤 JSON 经原 PostgREST 六参数入口展开后，明显增加数据库处理耗时。
- 使用原活动只读快照和失败的上月文件重建输入，在临时表中验证，没有更新生产活动。
- 两次对比：原请求结构 7,591 / 6,421 ms；整体 JSON 入口 2,246 / 2,310 ms。第二次使用待发布函数原文，仅把 schema 指向临时表；保存成功、旧版本重复提交被拒绝。耗时不是生产 HTTP 端到端测量，仍需部署后验收。

## 修改范围

- 新增 `sigma_fbu_commit_snapshot_raw(jsonb)`，使用单个无名 JSONB 参数，原样委托原事务函数；不调整计算规则、并发版本校验、表结构或超时配置。
- Python 保存入口切换到该函数。只有明确缺少新入口（404/PGRST202）才兼容旧入口；超时不自动重放写入。
- 数据库保存失败时恢复考勤缓存和本地快照；追加上月考勤使用深拷贝，数据库成功保存后才替换原文件。
- 错误保留安全的数据库错误码，并明确提示数据库超时，不展示原始数据库详情。
- JSON 传递方式依据：[PostgREST 官方说明](https://docs.postgrest.org/en/stable/references/api/functions.html#functions-with-a-single-unnamed-json-parameter)。

## 验证

- `python -m pytest tests/test_fbu*.py -q`：378 passed，2 条依赖弃用警告。
- `git diff --check`：通过。
- 临时表复现验证：新函数保存成功、旧 revision 再次提交返回未应用。
- 还未进行：生产迁移、生产发布、真实页面重试。不能据此宣称生产已恢复。

## 发布步骤（需要生产变更确认）

1. 将本分支修复整合到最新生产候选，避免覆盖其他模块已发布内容；不要把本工作树直接当成最新生产整体发布。
2. 先在验证环境执行 `supabase/migrations/20260916130000_fbu_raw_snapshot_transport.sql`，发布代码，验证 RPC 发现、服务角色权限及考勤导入。
3. 生产新增同一函数并刷新 schema cache；保留旧六参数函数，仅服务角色有调用权限。此迁移不修改表结构和活动数据。
4. 发布包含本修复的代码。确认新入口存在，否则兼容路径仍会使用原慢入口，不能认为问题已修复。
5. 与活动操作者确认重试时机，在 `556722ff` 对失败的上月考勤任务只重试一次；观察最终任务成功、跨实例刷新后仍显示已解析、96 工时上下文正确，以及数据库无新的 57014。
6. 保留原当月考勤和补充假勤，不删除活动、不重复上传已成功文件、不更改名单和计算结果。

回滚优先回退应用版本，新增函数可保留（旧版不调用）；无需删除表或数据。但旧版本仍有原超时风险。若写入结果不明确，先读取活动版本和任务状态再决定是否重试。

诊断脚本 `tools/fbu_snapshot_timeout_probe.sql` 仅针对上述活动，使用临时对象；`tools/fbu_reproduce_previous_attendance.py` 的输入输出含员工信息，必须放在非仓库临时目录并在验证后清理，不得提交。
