# 公司社保报盘运行配置

公司部署沿 GitLab master → AIDeploy 发布线。API 镜像包含 Node.js 22.22.3 和 LibreOffice Calc，社保连接器通过 `SIGMA_SOCIAL_INSURANCE_ENGINE_DIR=/app/social_insurance_connector` 运行，规则版本须与代码一致：`SOCIAL_INSURANCE_RULE_VERSION=2026.10.12-01`。不使用本地 macOS Keychain；BEISEN_APP_KEY、BEISEN_APP_SECRET 由公司密钥配置注入，沿用现有授权范围。

活动、文件及主体社保账号复用公司现有私有 S3/OBS 存储。生产保持 `SIGMA_SOCIAL_INSURANCE_STORAGE_ENV=production`；预览单独覆盖为 `aideploy-preview-social-20261012`，避免覆盖生产账号与批次。主体账号存于 `subject-settings/<主体名称SHA256>.json`，每次读写访问持久化存储，按主体隔离，保留前导零；读写失败阻止操作，不回退本机配置。无需新增数据库、权限或 OBS CORS。

政府最新版模板通过批次的模板上传入口提供，每月需人工确认；本机资料库不会随发布进入生产。导出支持直接下载 XLS 和可选 ZIP；每次格式转换使用独立 LibreOffice 用户配置目录，避免并行请求串用转换进程。账号、模板或人员资料有问题时重新校验，失效的旧报盘文件停止下载。

生产验证范围：北森同步、主体账号保存与刷新、模板校验、生成、历史回看和下载。政府网站上传及最终受理、Windows/RPA 均不在本次发布范围。保留既有模块权限与正式工 Worker。回滚只切回上一生产镜像和配置，不删除历史数据。
