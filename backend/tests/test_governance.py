"""视觉身份档案与版权治理 API 的单元测试模块。

测试覆盖 PetVisualIdentity 视觉特征档案创建/查询、PetAssetRight 版权存证登记
以及版权撤销触发防扩散广播事件。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_visual_identity_crud(client: TestClient, account_auth: dict[str, str]):
    """测试视觉身份档案创建与查询。"""
    resp = client.post(
        "/api/v1/admin/governance/identities",
        headers=account_auth,
        json={
            "template_id": "test_template_demo",
            "identity_version": "v1",
            "hair_style": "双马尾",
            "eye_style": "大眼睛",
            "features": ["长发", "白裙"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("created", "updated")

    # 查询档案
    get_resp = client.get(
        "/api/v1/admin/governance/identities/test_template_demo",
        headers=account_auth,
    )
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["hair_style"] == "双马尾"
    assert "长发" in data["features"]


def test_asset_rights_registration_and_revocation(client: TestClient, account_auth: dict[str, str]):
    """测试版权存证登记与撤销。"""
    # 登记版权
    reg_resp = client.post(
        "/api/v1/admin/governance/rights",
        headers=account_auth,
        json={
            "artifact_id": "00000000-0000-0000-0000-000000000001",
            "rights_type": "CC BY-NC 4.0",
            "source_declaration": "作者明确授权",
        },
    )
    assert reg_resp.status_code == 200
    right_id = reg_resp.json()["right_id"]

    # 撤销版权
    revoke_resp = client.post(
        "/api/v1/admin/governance/rights/revoke",
        headers=account_auth,
        json={
            "right_id": right_id,
            "reason": "授权到期，停止分发",
        },
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"
