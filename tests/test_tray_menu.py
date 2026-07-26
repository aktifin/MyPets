from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.edge_geometry import EdgeSide
from onepic_desktop_pet.pet_registry import LOCAL_ACCOUNT_ID
from onepic_desktop_pet.tray_menu import install_system_tray_menu


@pytest.fixture(scope="module", autouse=True)
def _qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeTray:
    def __init__(self) -> None:
        self.menu = None

    def setContextMenu(self, menu) -> None:
        self.menu = menu


class FakeWindow:
    def __init__(self) -> None:
        self.visible = False
        self.paused = False
        self.calls: list[str] = []

    def isVisible(self) -> bool:
        return self.visible

    def hide(self) -> None:
        self.visible = False
        self.calls.append("hide")

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.calls.append(f"paused:{paused}")

    def trigger_interaction(self) -> None:
        self.calls.append("interaction")

    def trigger_selfie(self) -> None:
        self.calls.append("selfie")


class FakeEdgeDock:
    def __init__(self) -> None:
        self.side = EdgeSide.RIGHT
        self.attached = True
        self.hidden = True
        self.calls: list[str] = []

    def attach(self, side: EdgeSide) -> None:
        self.side = side
        self.attached = True
        self.calls.append(f"attach:{side.value}")

    def reveal_from_edge(self) -> None:
        self.hidden = False
        self.calls.append("reveal")

    def detach(self) -> None:
        self.side = None
        self.attached = False
        self.hidden = False
        self.calls.append("detach")


class FakeMessageCache:
    def __init__(self, unread: int) -> None:
        self.unread = unread

    def unread_count(self, _account_id: str) -> int:
        return self.unread


class FakeCloudSession:
    def __init__(self, *, connected: bool = True, unread: int = 3) -> None:
        self.state = SimpleNamespace(value="connected" if connected else "disabled")
        self.identity = (
            SimpleNamespace(account_id="account-1", display_name="测试用户")
            if connected
            else None
        )
        self.message_cache = FakeMessageCache(unread)
        self.calls: list[str] = []

    def sync_now(self) -> None:
        self.calls.append("sync")

    def sign_out(self) -> None:
        self.calls.append("sign_out")


class FakePetRegistry:
    def __init__(self, pets: list[SimpleNamespace]) -> None:
        self.pets = pets

    def list_pets(self) -> list[SimpleNamespace]:
        return list(self.pets)


class FakeLocalStore:
    def __init__(self, active_pet_id: str) -> None:
        self.active_pet_id = active_pet_id

    def get_active_pet_id(self) -> str:
        return self.active_pet_id


class FakeAssetCatalog:
    def selection_for(self, pet) -> SimpleNamespace:
        return SimpleNamespace(exact=not pet.identity.pet_id.endswith("fallback"))


def _pet(
    pet_id: str,
    name: str,
    owner_id: str,
    *,
    level: int,
    presence: str = "home",
) -> SimpleNamespace:
    return SimpleNamespace(
        identity=SimpleNamespace(
            pet_id=pet_id,
            name=name,
            primary_owner_account_id=owner_id,
        ),
        stats=SimpleNamespace(growth_level=level),
        presence=presence,
    )


class FakeApplication:
    def __init__(self, *, connected: bool = True) -> None:
        self.cloud_pet = _pet("cloud-pet", "云朵", "account-1", level=8)
        self.local_pet = _pet(
            "local-fallback",
            "小白",
            LOCAL_ACCOUNT_ID,
            level=2,
        )
        self.active_pet = self.cloud_pet if connected else self.local_pet
        self.window = FakeWindow()
        self.edge_dock = FakeEdgeDock()
        self.cloud_session = FakeCloudSession(connected=connected, unread=4)
        self.pet_registry = FakePetRegistry([self.local_pet, self.cloud_pet])
        self.local_store = FakeLocalStore(self.active_pet.identity.pet_id)
        self.asset_catalog = FakeAssetCatalog()
        self.tray = FakeTray()
        self.tray_menu = None
        self.switched: list[str] = []
        self.calls: list[str] = []

    def show_window(self) -> None:
        self.window.visible = True
        self.calls.append("show")

    def open_message_drawer(self) -> None:
        self.calls.append("messages")

    def open_pet_care_panel(self) -> None:
        self.calls.append("care")

    def open_pet_chat_dialog(self) -> None:
        self.calls.append("chat")

    def open_pet_create_dialog(self) -> None:
        self.calls.append("create")

    def open_health_analytics_dialog(self) -> None:
        self.calls.append("health")

    def open_reminder_manager(self) -> None:
        self.calls.append("reminders")

    def open_social_dialog(self) -> None:
        self.calls.append("social")

    def open_visit_dialog(self) -> None:
        self.calls.append("visits")

    def open_cloud_login(self) -> None:
        self.calls.append("login")

    def quit(self) -> None:
        self.calls.append("quit")

    def _switch_pet(self, pet_id: str) -> None:
        self.switched.append(pet_id)


def _top_level_titles(controller) -> list[str]:
    return [
        action.text()
        for action in controller.menu.actions()
        if not action.isSeparator()
    ]


def test_tray_menu_is_grouped_and_keeps_primary_actions_visible() -> None:
    app = FakeApplication()
    controller = install_system_tray_menu(app)

    titles = _top_level_titles(controller)

    assert titles[0] == "云朵 · Lv.8 · 云端宠物 · 在家"
    assert titles[1:3] == ["显示宠物", "消息（4 未读）"]
    assert "宠物互动" in titles
    assert "宠物管理（2）" in titles
    assert "社交、提醒与健康" in titles
    assert "桌面行为" in titles
    assert "云端账户（已连接）" in titles
    assert titles[-1] == "退出 MyPets"
    assert app.tray.menu is controller.menu
    assert app.message_action is controller.message_action
    assert app.pet_menu is controller.pet_menu
    assert app.cloud_status_action is controller.cloud_status_action


def test_tray_menu_refreshes_visibility_pause_edge_cloud_and_unread_state() -> None:
    app = FakeApplication()
    controller = install_system_tray_menu(app)

    assert controller.edge_actions[EdgeSide.RIGHT].isChecked()
    assert controller.reveal_action.isEnabled()
    assert controller.detach_action.isEnabled()
    assert controller.sync_action.isEnabled()
    assert controller.sign_out_action.isEnabled()

    controller.visibility_action.trigger()
    assert app.window.visible is True
    assert controller.visibility_action.text() == "隐藏宠物"

    controller.pause_action.trigger()
    assert app.window.paused is True
    assert controller.pause_action.text() == "恢复自主跑动"

    controller.edge_actions[EdgeSide.TOP].trigger()
    assert app.edge_dock.side is EdgeSide.TOP
    assert controller.edge_actions[EdgeSide.TOP].isChecked()

    app.cloud_session.message_cache.unread = 0
    app.cloud_session.state = SimpleNamespace(value="offline")
    controller.refresh()
    assert controller.message_action.text() == "消息"
    assert controller.cloud_menu.title() == "云端账户（离线）"
    assert controller.cloud_status_action.text() == "状态：离线 · 测试用户"


def test_pet_switch_menu_groups_cloud_and_local_pets_and_marks_fallback() -> None:
    app = FakeApplication()
    controller = install_system_tray_menu(app)
    controller.rebuild_pet_menu()

    actions = [action for action in controller.pet_menu.actions() if not action.isSeparator()]
    texts = [action.text() for action in actions]

    assert texts == ["云端宠物", "云朵", "本地宠物", "小白（兼容形象）"]
    cloud_action = next(action for action in actions if action.text() == "云朵")
    local_action = next(action for action in actions if action.text().startswith("小白"))
    assert cloud_action.isChecked()
    assert not local_action.isChecked()

    local_action.trigger()
    assert app.switched == ["local-fallback"]


def test_signed_out_local_mode_disables_account_dependent_entries() -> None:
    app = FakeApplication(connected=False)
    controller = install_system_tray_menu(app)

    assert controller.cloud_menu.title() == "云端账户（未启用）"
    assert controller.login_action.text() == "登录或注册…"
    assert not controller.sync_action.isEnabled()
    assert not controller.sign_out_action.isEnabled()
    assert not controller.message_action.isEnabled()
    assert not controller.reminder_action.isEnabled()
    assert not controller.social_action.isEnabled()
    assert not controller.visit_action.isEnabled()
