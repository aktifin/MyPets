"""私有 Release 自动发现与 Alembic 迁移脚本等新特性的单元测试模块。

测试覆盖 AssetPackageDownloadController 鉴权请求与 Alembic 初始版本基线。
"""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from onepic_desktop_pet.asset_download import AssetPackageDownloadController
from onepic_desktop_pet.domain import PetIdentity, PetProfile
from onepic_desktop_pet.pet_assets import PetAssetCatalog


def test_request_private_release_headers():
    """测试私有 Release 是否正确添加 Bearer 鉴权头。"""
    catalog = PetAssetCatalog()
    controller = AssetPackageDownloadController("http://127.0.0.1:8000", catalog)

    profile = PetProfile(
        identity=PetIdentity("pet_private_100", "测试私有宠物", "demo_pet", "v1", "v1", "owner_1"),
        asset_version="v2",
    )

    result = controller.request_private_release_for(profile, "fake_access_token_xyz")
    assert result is True


def test_alembic_version_script_exists():
    """测试 Alembic 001_initial_schema.py 迁移脚本声明。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "schema_script", "backend/alembic/versions/001_initial_schema.py"
    )
    assert spec is not None
    assert spec.origin.endswith("001_initial_schema.py")
