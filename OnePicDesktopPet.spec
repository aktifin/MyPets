# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path


datas = [("assets", "assets"), ("config", "config")]
private_assets = Path("user_assets")
if os.environ.get("ONEPIC_INCLUDE_USER_ASSETS") == "1" and private_assets.exists():
    # 个人版只携带运行时真正需要的私有文件。原始上传副本、候选图、
    # 生成提示词、审查 GIF 和备份均保留在本机项目中，不进入发布目录。
    private_pet = private_assets / "pet"
    private_selfie = private_assets / "selfie.png"
    private_workflow = private_assets / "workflow.json"
    if private_pet.is_dir():
        private_manifest = private_pet / "manifest.json"
        if private_manifest.is_file():
            datas.append((str(private_manifest), "user_assets/pet"))
        for private_png in private_pet.rglob("*.png"):
            relative_parent = private_png.relative_to(private_pet).parent
            destination = Path("user_assets/pet") / relative_parent
            datas.append((str(private_png), str(destination)))
    if private_selfie.is_file():
        datas.append((str(private_selfie), "user_assets"))
    if private_workflow.is_file():
        datas.append((str(private_workflow), "user_assets"))

a = Analysis(
    ["main.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OnePicDesktopPet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets\\icons\\pet.png"],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OnePicDesktopPet",
)
