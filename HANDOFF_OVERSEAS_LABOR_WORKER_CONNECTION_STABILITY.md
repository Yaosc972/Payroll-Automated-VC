# 海外劳务核对助手连接稳定性发布交接

更新时间：2026-07-28
分支：`codex/overseas-labor-async-storage`
目标版本：`0.3.14`
边界：不包含开机/登录自动启动；不得直接在本任务部署生产。

## 生产故障证据

- 本机 Worker 日志在 2026-07-28 22:26—23:04 之间持续出现 `worker API unavailable: timed out`，约每 19 秒一次。
- 本机 Worker 状态长期停留在“正在检查本人待处理任务”，版本为 `0.3.12`。
- API 地址为 `https://sigma-workbench.vercel.app`。
- macOS 系统 HTTP/HTTPS/SOCKS 代理均指向 `127.0.0.1:7890`；FlClash 进程存在，但诊断时 7890 没有监听。
- `curl` 访问生产 Worker 接口 20 秒超时，Python `httpx` 连接 10 秒超时。
- 同期 Vercel Production 日志没有对应 Worker 请求，因此故障发生在请求到达 Vercel之前。

## 本次修复

1. Electron 使用 `session.defaultSession.resolveProxy()` 读取系统代理，并将确定的 HTTP/HTTPS/SOCKS 代理传给 Python Worker；如果系统代理在建立连接前明确失败，Worker 会安全回退直连，但不会在已收到响应或读取中断后盲目重放请求。
2. Python Worker 连接超时由 15 秒降到 3 秒；第一个鉴权请求成功后立即显示已连接，不再每次轮询闪回“正在连接”。
3. 助手区分：系统代理不可用、网络离线、生产服务不可用、身份失效、正在恢复。
4. 页面根据最近在线时间和设备凭据到期时间区分：在线、正在恢复、网络离线、身份失效。
5. 设备凭据存放在系统安全存储中；服务端在每次有效使用时把有效期滑动续至 30 天，最长配置上限 90 天，设备撤销仍立即使凭据失效。
6. 修复重新连接时旧 PID 尚未退出就启动新进程的竞态；重新连接会等待旧 Worker 退出。
7. Electron 每 5 秒监督 Worker 进程；异常退出后 1 秒重启；系统睡眠恢复后重新解析代理并恢复连接。
8. 任务心跳从 30 秒调整为 20 秒；临时失败 5 秒重试；401/403/409/426 会标记租约失效并禁止上传结果。
9. Worker 版本升级至 `0.3.14`。

## 已完成验证

```text
Python 相关回归：92 passed
Electron/Node：22 passed
npm run check：PASS
Python py_compile：PASS
overseas-labor.js node --check：PASS
git diff --check：PASS
Worker release gate：PASS
PyInstaller Worker 构建：PASS
macOS DMG 构建：PASS
```

本地构建物：

```text
labor-worker-desktop/release/Σ海外报账核对助手-0.3.14-arm64.dmg
大小：132,572,851 bytes（约 126.4 MiB）
SHA-256：fa3d7e0025538f94d963ee5bceda3c7c24d9aaaaba6b81310da2b1427516dd0f
```

应用内部 `codesign --verify --deep --strict` 通过，但当前没有 Developer ID 身份，`spctl` 拒绝；该 DMG 只能用于受控测试，不能作为正式生产签名包发布。

## 发布窗口执行顺序

1. 只集成本交接列出的连接稳定性文件，保留工作区其他脏改动。
2. 部署服务端和网页代码，但先不要发布 `0.3.14` 安装包。
3. 用 Apple Developer ID 对 `.app` 正式签名并完成 notarization；重新生成 DMG。
4. 复核 DMG 文件名必须是 `Σ海外报账核对助手-0.3.14-arm64.dmg`，重新计算 SHA-256。
5. 管理员通过海外劳务页面上传并 finalize；确认发布清单显示 `0.3.14` 后，旧 Worker 才会被要求升级。
6. 一台旧版机器升级后重新激活一次。旧的 8 小时凭据若已经过期，无法通过滑动续期复活；重新激活后将进入新的 30 天滑动续期机制。
7. 生产验证：
   - 代理正常：打开助手后 1—3 秒显示在线。
   - 停止代理监听：助手在一次连接尝试内显示“系统代理不可用”。
   - 恢复代理：无需重新激活，数秒内自动回到在线。
   - 睡眠再唤醒：自动恢复连接。
   - 杀死 Worker 子进程：1 秒左右自动拉起。
   - 制造服务端 503：显示“生产服务不可用”，恢复后自动在线。
   - 执行测试任务并短暂断网：心跳恢复后继续；租约失效时不得上传旧结果。
8. 对照 Worker 本地日志和 Vercel Production 日志，确认请求到达、状态码正常、无连续超时。

## 尚未验证

- 未在正式签名、公证后的 `0.3.14` 安装包上完成生产实机验收。
- 未部署服务端或网页代码。
- 未上传安装包或激活新的生产发布清单。
- Windows `0.3.14` 需要在 Windows 10/11 x64 单独构建和验证。
