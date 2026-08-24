# Windows 单用户社保 UAT 接入

## 架构

- Mac 仅在 `127.0.0.1:8001` 运行社保工作台，不开放局域网端口。
- Windows 通过 SSH 隧道把自己的 `127.0.0.1:8001` 转发到 Mac。
- 北森凭证继续保存在 Mac 当前用户的 Keychain，员工数据保存在权限为 `0700/0600` 的 UAT 目录。
- 运行副本由 `launchd` 自动启动并保活；应用升级后需要重新部署运行副本。

## Mac 端一次性设置

1. 系统设置 → 通用 → 共享 → 远程登录。
2. “允许访问”只选择指定的 UAT 接入账号，不选择“所有用户”。
3. 将 Windows 生成的 SSH 公钥加入允许列表，并限制为只能转发到 `127.0.0.1:8001`。
4. 保持 Mac 接电、开机、联网，并保持 UAT 所属的 Mac 用户处于登录状态。后台服务会在接电时阻止主机自动休眠，显示器仍可正常关闭。

不应把应用改成监听 `0.0.0.0`，也不应在路由器上开放 `8001`。

## Windows 端

先在 PowerShell 生成独立密钥：

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\sigma_social_uat
```

把 `sigma_social_uat.pub` 提供给 Mac 管理员。管理员完成公钥安装后，运行：

```powershell
ssh -N -i $env:USERPROFILE\.ssh\sigma_social_uat -L 8001:127.0.0.1:8001 <mac-uat-user>@10.80.9.253
```

其中 `10.80.9.253` 是部署当天的局域网地址，DHCP 重新分配后可能变化；长期试用应让 IT 为 Mac 固定地址或做 DHCP 保留。

隧道保持运行期间，浏览器访问：

```text
http://127.0.0.1:8001/social-insurance.html
```

## 运行数据

```text
/Users/zt27532/Library/Application Support/SigmaWorkbenchUAT/
```

该目录包含员工批次、审核导出、规则引擎、深圳模板和离职快照，不应通过普通共享盘同步。

运行代码位于同目录下的 `app`，日志位于 `logs`。项目源码仍在开发目录中，后台任务不会直接读取 macOS 受隐私保护的“文稿”目录。
