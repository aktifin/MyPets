"""Grouped, state-aware Windows system tray menu for the desktop pet application."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu

from .edge_geometry import EdgeSide
from .pet_registry import LOCAL_ACCOUNT_ID


_CLOUD_LABELS = {
    "disabled": "未启用",
    "offline": "离线",
    "authenticating": "正在认证",
    "binding": "正在绑定设备",
    "syncing": "正在同步",
    "connected": "已连接",
    "error": "连接异常",
}

_PRESENCE_LABELS = {
    "home": "在家",
    "visiting": "串门中",
    "away": "外出",
}

_EDGE_LABELS = {
    EdgeSide.LEFT: "左侧",
    EdgeSide.RIGHT: "右侧",
    EdgeSide.TOP: "顶部",
    EdgeSide.BOTTOM: "底部",
}


class SystemTrayMenuController:
    """Build and refresh a compact tray menu without coupling feature subclasses together."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.menu = QMenu()
        self._pet_action_group: QActionGroup | None = None
        self._edge_action_group: QActionGroup | None = None
        self.edge_actions: dict[EdgeSide, QAction] = {}
        self._build()
        self.app.tray.setContextMenu(self.menu)
        self.app.tray_menu = self.menu
        self.app._rebuild_pet_menu = self.rebuild_pet_menu
        self.menu.aboutToShow.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _disabled_action(text: str, parent: QMenu) -> QAction:
        action = QAction(text, parent)
        action.setEnabled(False)
        return action

    @staticmethod
    def _add_action(
        menu: QMenu,
        text: str,
        callback: Callable[..., object],
        *,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, menu)
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _build(self) -> None:
        self.summary_action = self._disabled_action("MyPets", self.menu)
        self.menu.addAction(self.summary_action)

        self.visibility_action = self._add_action(
            self.menu,
            "显示宠物",
            self._toggle_visibility,
            checkable=True,
        )
        self.message_action = self._add_action(
            self.menu,
            "消息",
            self.app.open_message_drawer,
        )
        self.app.message_action = self.message_action

        self.menu.addSeparator()

        interaction_menu = self.menu.addMenu("宠物互动")
        self._add_action(interaction_menu, "打招呼", self.app.window.trigger_interaction)
        self._add_action(interaction_menu, "自拍一下", self.app.window.trigger_selfie)
        self._add_action(interaction_menu, "状态与照料…", self.app.open_pet_care_panel)
        self._add_action(interaction_menu, "与宠物聊天…", self.app.open_pet_chat_dialog)

        self.pets_root_menu = self.menu.addMenu("宠物管理")
        self.pet_menu = self.pets_root_menu.addMenu("切换宠物")
        self.pet_menu.aboutToShow.connect(self.rebuild_pet_menu)
        self.create_pet_action = self._add_action(
            self.pets_root_menu,
            "创建新宠物…",
            self.app.open_pet_create_dialog,
        )
        self.app.pet_menu = self.pet_menu

        services_menu = self.menu.addMenu("社交、提醒与健康")
        self.reminder_action = self._optional_action(
            services_menu,
            "提醒管理…",
            "open_reminder_manager",
        )
        self.social_action = self._optional_action(
            services_menu,
            "好友与共同照料…",
            "open_social_dialog",
        )
        self.visit_action = self._optional_action(
            services_menu,
            "异步串门…",
            "open_visit_dialog",
        )
        services_menu.addSeparator()
        self.health_action = self._add_action(
            services_menu,
            "健康与操作分析…",
            self.app.open_health_analytics_dialog,
        )
        self._replace_optional_alias("reminder_manager_action", self.reminder_action)
        self._replace_optional_alias("social_action", self.social_action)
        self._replace_optional_alias("visit_action", self.visit_action)

        self.proactive_menu = self.menu.addMenu("主动关怀")
        self.proactive_status_action = self._disabled_action(
            "状态：读取中", self.proactive_menu
        )
        self.proactive_menu.addAction(self.proactive_status_action)
        self.proactive_enabled_action = self._add_action(
            self.proactive_menu,
            "启用主动关怀",
            self._set_proactive_enabled,
            checkable=True,
        )
        self.proactive_menu.addSeparator()
        self.proactive_open_action = self._optional_action(
            self.proactive_menu,
            "处理当前提示",
            "open_current_proactive_notice",
        )
        self.proactive_snooze_action = self._optional_action(
            self.proactive_menu,
            "稍后 2 小时再提示",
            "snooze_current_proactive_notice",
        )
        self.proactive_dismiss_action = self._optional_action(
            self.proactive_menu,
            "今天不再提示此条",
            "dismiss_current_proactive_notice_today",
        )
        self.proactive_menu.addSeparator()
        self.proactive_settings_action = self._optional_action(
            self.proactive_menu,
            "主动关怀设置…",
            "open_proactive_care_settings",
        )

        desktop_menu = self.menu.addMenu("桌面行为")
        self.pause_action = self._add_action(
            desktop_menu,
            "暂停自主跑动",
            self._set_paused,
            checkable=True,
        )
        edge_menu = desktop_menu.addMenu("边缘吸附")
        self._edge_action_group = QActionGroup(edge_menu)
        self._edge_action_group.setExclusive(True)
        for side in (EdgeSide.LEFT, EdgeSide.RIGHT, EdgeSide.TOP, EdgeSide.BOTTOM):
            action = self._add_action(
                edge_menu,
                f"吸附到{_EDGE_LABELS[side]}",
                lambda _checked=False, side=side: self._attach(side),
                checkable=True,
            )
            self._edge_action_group.addAction(action)
            self.edge_actions[side] = action
        edge_menu.addSeparator()
        self.reveal_action = self._add_action(
            edge_menu,
            "暂时展开",
            self.app.edge_dock.reveal_from_edge,
        )
        self.detach_action = self._add_action(
            edge_menu,
            "解除吸附",
            self.app.edge_dock.detach,
        )

        self.cloud_menu = self.menu.addMenu("云端账户")
        self.cloud_status_action = self._disabled_action("状态：未启用", self.cloud_menu)
        self.cloud_menu.addAction(self.cloud_status_action)
        self.login_action = self._add_action(
            self.cloud_menu,
            "登录或注册…",
            self.app.open_cloud_login,
        )
        self.sync_action = self._add_action(
            self.cloud_menu,
            "立即同步",
            self.app.cloud_session.sync_now,
        )
        self.sign_out_action = self._add_action(
            self.cloud_menu,
            "退出云端账户",
            self.app.cloud_session.sign_out,
        )
        self.app.cloud_status_action = self.cloud_status_action

        self.menu.addSeparator()
        self.quit_action = self._add_action(self.menu, "退出 MyPets", self.app.quit)

    def _optional_action(self, menu: QMenu, text: str, method_name: str) -> QAction:
        method = getattr(self.app, method_name, None)
        action = QAction(text, menu)
        action.setEnabled(callable(method))
        if callable(method):
            action.triggered.connect(method)
        menu.addAction(action)
        return action

    def _replace_optional_alias(self, name: str, action: QAction) -> None:
        if hasattr(self.app, name):
            setattr(self.app, name, action)

    def refresh(self) -> None:
        pet = self.app.active_pet
        identity = pet.identity
        stats = getattr(pet, "stats", None)
        level = getattr(stats, "growth_level", None)
        owner_label = (
            "本地宠物"
            if identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
            else "云端宠物"
        )
        presence = getattr(pet, "presence", "home")
        presence_value = getattr(presence, "value", presence)
        presence_label = _PRESENCE_LABELS.get(str(presence_value), str(presence_value))
        level_text = f" · Lv.{level}" if isinstance(level, int) else ""
        self.summary_action.setText(
            f"{identity.name}{level_text} · {owner_label} · {presence_label}"
        )

        visible = bool(self.app.window.isVisible())
        self.visibility_action.setChecked(visible)
        self.visibility_action.setText("隐藏宠物" if visible else "显示宠物")

        paused = bool(getattr(self.app.window, "paused", False))
        self.pause_action.setChecked(paused)
        self.pause_action.setText("恢复自主跑动" if paused else "暂停自主跑动")

        attached = bool(self.app.edge_dock.attached)
        side = self.app.edge_dock.side
        for edge_side, action in self.edge_actions.items():
            action.setChecked(attached and side is edge_side)
        self.reveal_action.setEnabled(attached)
        self.detach_action.setEnabled(attached)

        state = getattr(self.app.cloud_session, "state", "disabled")
        state_value = getattr(state, "value", state)
        state_value = str(state_value)
        state_label = _CLOUD_LABELS.get(state_value, state_value)
        identity_value = getattr(self.app.cloud_session, "identity", None)
        account_name = getattr(identity_value, "display_name", "") if identity_value else ""
        self.cloud_status_action.setText(
            f"状态：{state_label}" + (f" · {account_name}" if account_name else "")
        )
        self.cloud_menu.setTitle(f"云端账户（{state_label}）")
        self.login_action.setText("切换账户或服务器…" if identity_value else "登录或注册…")
        self.sync_action.setEnabled(
            identity_value is not None
            and state_value not in {"authenticating", "binding", "disabled"}
        )
        self.sign_out_action.setEnabled(identity_value is not None)

        unread = 0
        if identity_value is not None:
            try:
                unread = int(
                    self.app.cloud_session.message_cache.unread_count(
                        identity_value.account_id
                    )
                )
            except (AttributeError, TypeError, ValueError):
                unread = 0
        self.message_action.setText(f"消息（{unread} 未读）" if unread else "消息")
        self.message_action.setEnabled(identity_value is not None)

        cloud_pet = identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
        for action in (self.social_action, self.visit_action):
            action.setEnabled(identity_value is not None and cloud_pet)
        self.reminder_action.setEnabled(identity_value is not None)

        enabled_method = getattr(self.app, "proactive_care_is_enabled", None)
        proactive_enabled = bool(enabled_method()) if callable(enabled_method) else False
        notice_method = getattr(self.app, "proactive_notice", None)
        notice = notice_method() if callable(notice_method) else None
        self.proactive_enabled_action.setChecked(proactive_enabled)
        self.proactive_status_action.setText(
            f"当前：{notice.get('title')}" if isinstance(notice, dict) else (
                "状态：已开启，暂无提示" if proactive_enabled else "状态：已关闭"
            )
        )
        self.proactive_menu.setTitle(
            "主动关怀（有新提示）" if isinstance(notice, dict) else "主动关怀"
        )
        has_notice = isinstance(notice, dict)
        for action in (
            self.proactive_open_action,
            self.proactive_snooze_action,
            self.proactive_dismiss_action,
        ):
            action.setEnabled(has_notice)
        if has_notice:
            label = str(notice.get("action_label") or "处理")
            self.proactive_open_action.setText(label)
        else:
            self.proactive_open_action.setText("处理当前提示")

        self.rebuild_pet_menu()

    def rebuild_pet_menu(self) -> None:
        self.pet_menu.clear()
        pets = list(self.app.pet_registry.list_pets())
        active_id = self.app.local_store.get_active_pet_id()
        self.pets_root_menu.setTitle(f"宠物管理（{len(pets)}）")
        if not pets:
            self.pet_menu.addAction(self._disabled_action("没有可用宠物", self.pet_menu))
            return

        self._pet_action_group = QActionGroup(self.pet_menu)
        self._pet_action_group.setExclusive(True)
        local_pets = [
            pet
            for pet in pets
            if pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
        ]
        cloud_pets = [
            pet
            for pet in pets
            if pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
        ]
        first_section = True
        for section_name, section_pets in (
            ("云端宠物", cloud_pets),
            ("本地宠物", local_pets),
        ):
            if not section_pets:
                continue
            if not first_section:
                self.pet_menu.addSeparator()
            first_section = False
            self.pet_menu.addAction(self._disabled_action(section_name, self.pet_menu))
            for pet in sorted(
                section_pets,
                key=lambda item: (
                    item.identity.pet_id != active_id,
                    item.identity.name.casefold(),
                ),
            ):
                selection = self.app.asset_catalog.selection_for(pet)
                label = pet.identity.name
                if not selection.exact:
                    label += "（兼容形象）"
                action = QAction(label, self.pet_menu)
                action.setCheckable(True)
                action.setChecked(pet.identity.pet_id == active_id)
                action.triggered.connect(
                    lambda _checked=False, pet_id=pet.identity.pet_id: self.app._switch_pet(
                        pet_id
                    )
                )
                self._pet_action_group.addAction(action)
                self.pet_menu.addAction(action)
        self.app._pet_action_group = self._pet_action_group

    def _toggle_visibility(self, checked: bool) -> None:
        if checked:
            self.app.show_window()
        else:
            self.app.window.hide()
        self.refresh()

    def _set_paused(self, checked: bool) -> None:
        self.app.window.set_paused(bool(checked))
        self.refresh()

    def _set_proactive_enabled(self, checked: bool) -> None:
        method = getattr(self.app, "set_proactive_care_enabled", None)
        if callable(method):
            method(bool(checked))
        self.refresh()

    def _attach(self, side: EdgeSide) -> None:
        self.app.edge_dock.attach(side)
        self.refresh()


def install_system_tray_menu(app: Any) -> SystemTrayMenuController:
    """Install once and retain the controller for the lifetime of the Qt application."""

    existing = getattr(app, "system_tray_menu", None)
    if isinstance(existing, SystemTrayMenuController):
        return existing
    controller = SystemTrayMenuController(app)
    app.system_tray_menu = controller
    return controller
