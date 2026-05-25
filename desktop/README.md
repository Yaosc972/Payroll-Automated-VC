# 西格玛工作台桌面版

桌面版采用 Electron 外壳 + Python/FastAPI 后端。应用启动时会自动启动本地后端服务，并把所有数据写入用户本机应用数据目录。

## 开发启动

先确保项目根目录的 Python 依赖已安装：

```bash
python3 -m pip install -r ../requirements.txt
```

在 `desktop/` 目录安装前端依赖并启动：

```bash
npm install
npm run dev
```

开发模式下，Electron 会使用本机 `python3` 运行 `desktop/backend_entry.py`。

## 本地数据目录

桌面版会设置：

```text
SIGMA_WORKBENCH_HOME = Electron userData
SIGMA_WORKBENCH_SEED_DIR = 应用内置 seed-data
```

首次启动时，后端会把规则库和导入模板复制到用户数据目录。后续规则更新优先使用用户数据目录中的文件，不会因为覆盖安装而丢失历史批次。

## 打包后端

需要先安装 PyInstaller：

```bash
python3 -m pip install pyinstaller
```

然后在 `desktop/` 目录执行：

```bash
npm run build:backend
```

生成目录：

```text
desktop/backend-dist/sigma-backend/
```

## 打包安装包

macOS：

```bash
npm run dist:mac
```

Windows：

```bash
npm run dist:win
```

第一阶段未做代码签名。macOS 首次打开可能需要在系统安全设置中允许；Windows 企业环境可能需要白名单或签名后再推广。

## GitHub Actions 自动构建

项目根目录的 `.github/workflows/desktop-release.yml` 会在 GitHub runner 上分别构建 macOS 和 Windows 安装包。

手动测试：

1. 打开 GitHub 仓库。
2. 进入 `Actions`。
3. 选择 `Desktop Release`。
4. 点击 `Run workflow`。
5. 构建完成后，在 workflow artifacts 下载安装包。

正式发版：

```bash
git tag v0.1.0
git push origin v0.1.0
```

tag 构建会自动创建 GitHub Release，并上传 `.dmg` 和 `.exe`。
