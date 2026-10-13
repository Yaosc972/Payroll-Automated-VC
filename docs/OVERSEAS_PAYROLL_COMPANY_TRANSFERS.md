# 公司海外薪酬工具文件传输

公司 OBS 环境的海外工具输入上传和用户结果下载使用同源 API，由服务器转交私有存储。无需启用 OBS 桶的浏览器 CORS。选择依据为现有 `labor_obs_storage_enabled()`；没有新增配置、数据库表或存储权限。

- 创建任务返回 `/api/overseas-payroll/tasks/{task_id}/files/{file_id}/content` 上传地址。接口校验登录、模块权限、任务归属、可上传状态、清单大小（单文件最多 40 MB）与 SHA256，限制读取大小后写入 OBS。浏览器仍需调用 finalize，由既有存储元数据检查确认文件到达，再开始处理。
- `/api/overseas-payroll/tasks/{task_id}/download` 为公司 OBS 返回同源结果地址；结果内容接口再次校验用户和任务归属，只允许完成且输出 ready 的任务，读取私有对象并设置 attachment 与 private/no-store。历史已完成任务也使用此下载方式。
- 存储传输失败返回可重试的 503 中文提示，不返回凭据或底层异常正文。输入上传失败不会被标记为完成，也不回退到本机存储。

Supabase 环境继续使用原有签名传输；本地存储继续使用本地文件。Worker 输入下载、输出上传与 finalize 沿用既有服务间协议。

回归：`python3 -m pytest -q tests/test_overseas_payroll.py`，覆盖公司上传及 finalize、结果下载、大小/摘要不一致、已排队任务、跨用户访问及存储异常。测试使用隔离内存存储，不接生产。

发布后需要在已授权的隔离任务中核验真实上传、解析、下载，以及刷新后历史结果下载。网络上传恢复不表示任意 PDF 都能解析；德国提取工具要求 DATEV Lohnjournal（LOA313）文本型报表。
