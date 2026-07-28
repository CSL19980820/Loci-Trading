# -*- mode: python ; coding: utf-8 -*-
# Loci desktop build（onedir：启动快；产物在仓库根 Loci/）
#   frontend already built → pyinstaller loci.spec
#
# 体积：排除 scipy（源码未用，却占 ~100MB）及测试/绘图等。
# 启动：onedir 不每次解压到临时目录（onefile 才慢）。

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

try:
    _dist = SPECPATH  # noqa: F821
except NameError:
    import os

    _dist = os.path.dirname(os.path.abspath(__file__))

try:
    import PyInstaller.config

    PyInstaller.config.CONF["distpath"] = _dist
except Exception:
    pass

datas = [
    ("frontend/dist", "frontend/dist"),
    ("assets/loci-icon.png", "assets"),
    ("assets/loci.ico", "assets"),
    ("使用说明.txt", "."),
]
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "multipart",
    "email.mime.text",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
]

# webview / pystray 需要平台资源；不要对 PIL 用 collect_all（会拖进整包编解码器）
for pkg in ("uvicorn", "fastapi", "starlette", "webview", "pystray"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

hiddenimports += collect_submodules("src")

# 业务未直接 import scipy；pandas 也不依赖它运行本仓路径
excludes = [
    "tkinter",
    "matplotlib",
    "IPython",
    "notebook",
    "jupyter",
    "pytest",
    "scipy",
    "scipy.libs",
    "torch",
    "tensorflow",
    "sklearn",
    "cv2",
]

a = Analysis(
    ["loci.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Loci",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/loci.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Loci",
)
