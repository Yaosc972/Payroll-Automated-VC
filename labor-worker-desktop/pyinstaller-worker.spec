# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


DESKTOP_ROOT = Path(SPECPATH)
PROJECT_ROOT = DESKTOP_ROOT.parent
rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = collect_all("rapidocr")
onnxruntime_datas, onnxruntime_binaries, onnxruntime_hiddenimports = collect_all("onnxruntime")


a = Analysis(
    ["worker_entry.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[*rapidocr_binaries, *onnxruntime_binaries],
    datas=[
        (str(DESKTOP_ROOT / "worker-static-placeholder"), "bonus_platform/static"),
        *rapidocr_datas,
        *onnxruntime_datas,
    ],
    hiddenimports=[
        "tools.labor_ocr_worker_task",
        *rapidocr_hiddenimports,
        *onnxruntime_hiddenimports,
    ],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sigma-labor-worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="sigma-labor-worker",
)
