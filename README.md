# 西格玛工作台 / Σ-Workbench

本项目是招聘奖金与内推奖金的本地核算工作台。平台按规则库确定性计算，不依赖 AI 生成金额。

## 当前形态

- Web 开发版：FastAPI + 静态前端。
- 桌面封装版：Electron + 内置 Python/FastAPI 后端。
- 数据模式：完全本地单机，上传文件、结果文件、批次记录、SQLite 索引都保存在用户电脑。

## Web 开发启动

```bash
python3 -m pip install -r requirements.txt
python3 -m uvicorn bonus_platform.app:app --reload --port 8001
```

访问：

```text
http://127.0.0.1:8001/
```

## 桌面版开发启动

```bash
cd desktop
npm install
npm run dev
```

桌面版会自动启动本地后端服务，并把数据写入 Electron 的 `userData` 目录。规则库和导入模板会在首次启动时复制到用户数据目录。

## 桌面版打包

```bash
cd desktop
python3 -m pip install pyinstaller
npm install
npm run build:backend
npm run dist:mac
```

Windows 打包在 Windows 机器上执行：

```bash
cd desktop
npm run dist:win
```

详细说明见 `desktop/README.md`。

## GitHub Actions 自动打包

仓库包含 `.github/workflows/desktop-release.yml`。它会在两种情况下运行：

- 手动触发 `Desktop Release` workflow
- 推送版本 tag，例如 `v0.1.0`

发布正式版本时：

```bash
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions 会分别在 macOS 和 Windows runner 上构建：

- macOS: `.dmg`
- Windows: `.exe`

tag 构建完成后，安装包会自动上传到 GitHub Release。第一阶段未配置代码签名，企业推广前建议补 Windows 证书签名和 macOS notarization。
