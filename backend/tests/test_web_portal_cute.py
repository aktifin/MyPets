"""Web 端页面逻辑与卡哇伊 UI 视效重构单元测试模块。

测试覆盖 /portal 用户门户静态资源响应、portal_cute.css 样式表加载、
/admin 控制台路由以及页面 5 大板块结构。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mypets_backend.main import create_app


@pytest.fixture
def client(tmp_path):
    from mypets_backend.config import Settings
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'backend.sqlite3'}",
        jwt_secret="test-secret-with-more-than-24-characters",
        environment="test",
        admin_usernames=("admin_editor",),
        asset_storage_dir=str(tmp_path / "assets"),
    )
    app = create_app(settings)
    with TestClient(app) as tc:
        yield tc
    app.state.engine.dispose()


def test_user_portal_html_response(client: TestClient):
    """测试 Web 用户门户 HTML 响应与卡片板块结构。"""
    resp = client.get("/portal")
    assert resp.status_code == 200
    assert "MyPets 用户中心" in resp.text
    assert "portal_cute.css" in resp.text
    assert "section-pet-status" in resp.text
    assert "section-personality" in resp.text


def test_portal_cute_css_static_route(client: TestClient):
    """测试 portal_cute.css 静态资源服务是否正常。"""
    resp = client.get("/portal/css/portal_cute.css")
    assert resp.status_code == 200
    assert "--cute-bg-pink" in resp.text
    assert "backdrop-filter" in resp.text


def test_admin_console_html_response(client: TestClient):
    """测试 Web 管理控制台 HTML 响应与萌系仪表盘结构。"""
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "MyPets Web 管理控制台" in resp.text
    assert "admin_cute.css" in resp.text
