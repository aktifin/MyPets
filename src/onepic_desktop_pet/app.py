"""Desktop application lifecycle, cloud sync, pet care, messaging, and assets."""

from __future__ import annotations

import os
import sys

os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts.warning=false"

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .asset_download import AssetPackageDownloadController
from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController
from .config import PetSettings, load_settings, save_settings
from .credential_store import CredentialStore, default_credential_store
from .domain import AccountPetRelation, PetIdentity, PetProfile, PetRole
from .dynamic_window import DynamicPetWindow
from .edge_dock import EdgeDockController
from .edge_geometry import EdgeSide
from .local_store import LocalStateStore
from .login_dialog import CloudLoginDialog
from .bubble_menu import PetBubbleMenu
from .cute_style import apply_cute_style
from .health_analytics_dialog import HealthAnalyticsDialog
from .health_scheduler import HealthScheduler
from .input_analytics import InputAnalytics
from .message_drawer import MessageDrawer
from .personality_engine import PersonalityEngine
from .pet_assets import PetAssetCatalog
from .pet_care_panel import PetCarePanel
from .pet_chat_dialog import PetChatDialog
from .pet_create_dialog import PetCreateDialog
from .pet_registry import LOCAL_ACCOUNT_ID, PetRegistry
from .resources import resource_path


class DesktopPetApplication:
    """Own the Qt app, desktop window, caches, cloud session, and user panels."""

    def __init__(
        self,
        settings: PetSettings | None = None,
        local_store: LocalStateStore | None = None,
        credential_store: CredentialStore | None = None,
        cloud_api: CloudApiClient | None = None,
        asset_catalog: PetAssetCatalog | None = None,
        asset_downloader: AssetPackageDownloadController | None = None,
    ) -> None:
        if QApplication.instance() is None:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        default_font = QFont("Microsoft YaHei", 9)
        default_font.setStyleHint(QFont.StyleHint.SansSerif)
        self.qt_app.setFont(default_font)
        self.qt_app.setApplicationName("OnePic Desktop Pet")
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.settings = settings or load_settings()

        self.local_store = local_store or LocalStateStore.open_default()
        self.pet_registry = PetRegistry(self.local_store)
        self.active_pet = self.pet_registry.bootstrap_local_pet()
        self.asset_catalog = asset_catalog or PetAssetCatalog()
        self._register_bundled_pets()
        self.active_pet = self.pet_registry.active_pet() or self.active_pet
        self._asset_selection = self.asset_catalog.selection_for(self.active_pet)

        self.window = DynamicPetWindow(
            self.settings,
            self._asset_selection.manifest_path,
        )
        self.bubble_menu = PetBubbleMenu()
        self.bubble_menu.action_triggered.connect(self._on_bubble_action)
        self.window.bubble_menu = self.bubble_menu
        self.edge_dock = EdgeDockController(self.window, self.settings)
        self.window.quit_requested.connect(self.quit)
        self.window.message_badge_clicked.connect(self.open_message_drawer)

        self.credential_store = credential_store or default_credential_store()
        self.cloud_api = cloud_api or CloudApiClient(self.settings.cloud_base_url)
        self.cloud_session = CloudSessionController(
            self.cloud_api,
            self.local_store,
            self.pet_registry,
            self.credential_store,
            self.settings,
        )
        self.cloud_session.state_changed.connect(self._cloud_state_changed)
        self.cloud_session.status_message.connect(self._cloud_status_message)
        self.cloud_session.pets_changed.connect(self._pets_changed)
        self.cloud_session.pet_care_succeeded.connect(self._pet_care_succeeded)
        self.cloud_session.pet_care_failed.connect(self._pet_care_failed)
        self.cloud_session.messages_changed.connect(self._messages_changed)
        self.cloud_session.message_status.connect(self._message_status)
        self.cloud_session.message_failed.connect(self._message_failed)
        self.cloud_api.operation_succeeded.connect(self._cloud_operation_succeeded)
        self.asset_downloader = asset_downloader or AssetPackageDownloadController(
            self.settings.cloud_base_url,
            self.asset_catalog,
        )
        self.asset_downloader.package_installed.connect(self._asset_package_installed)
        self.asset_downloader.download_failed.connect(self._asset_download_failed)
        self.asset_downloader.status_message.connect(self._asset_download_status)
        self.input_analytics = InputAnalytics()
        self.qt_app.installEventFilter(self.input_analytics)

        self.personality_engine = PersonalityEngine()
        self.health_scheduler = HealthScheduler(self.input_analytics)
        self.health_scheduler.health_reminder_triggered.connect(self._on_health_reminder)
        self.health_scheduler.start()

        self._login_dialog: CloudLoginDialog | None = None
        self._care_panel: PetCarePanel | None = None
        self._message_drawer: MessageDrawer | None = None
        self._health_dialog: HealthAnalyticsDialog | None = None
        self._chat_dialog: PetChatDialog | None = None
        self._create_dialog: PetCreateDialog | None = None
        self._quitting = False
        self._asset_status = ""

        self.tray = self._create_tray()
        self._refresh_active_pet_ui()
        self._messages_changed()

    def _register_bundled_pets(self) -> None:
        """Expose bundled runtime packages as local pet instances without changing current choice."""

        for definition in self.asset_catalog.bundled_local_pets():
            if self.local_store.get_pet(definition.pet_id) is not None:
                continue
            profile = PetProfile(
                identity=PetIdentity(
                    pet_id=definition.pet_id,
                    name=definition.name,
                    template_id=definition.identity.template_id,
                    template_version="1.0.0",
                    identity_version=definition.identity.identity_version,
                    primary_owner_account_id=LOCAL_ACCOUNT_ID,
                ),
                asset_version=definition.identity.asset_version,
                updated_at=datetime.now().astimezone(),
            )
            self.pet_registry.register_pet(
                profile,
                AccountPetRelation(
                    account_id=LOCAL_ACCOUNT_ID,
                    pet_id=definition.pet_id,
                    role=PetRole.OWNER,
                    affinity=50,
                ),
                make_active=False,
            )

    def _create_tray(self) -> QSystemTrayIcon:
        icon = QIcon(str(resource_path("assets/icons/pet.png")))
        tray = QSystemTrayIcon(icon, self.qt_app)
        menu = QMenu()

        show_action = QAction("显示宠物", menu)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)

        interact_action = QAction("和她打招呼", menu)
        interact_action.triggered.connect(self.window.trigger_interaction)
        menu.addAction(interact_action)

        selfie_action = QAction("自拍一下", menu)
        selfie_action.triggered.connect(self.window.trigger_selfie)
        menu.addAction(selfie_action)

        care_action = QAction("宠物状态与照料…", menu)
        care_action.triggered.connect(self.open_pet_care_panel)
        menu.addAction(care_action)

        chat_action = QAction("💬 与宠物聊天…", menu)
        chat_action.triggered.connect(self.open_pet_chat_dialog)
        menu.addAction(chat_action)

        health_action = QAction("📊 健康与操作分析…", menu)
        health_action.triggered.connect(self.open_health_analytics_dialog)
        menu.addAction(health_action)

        create_pet_action = QAction("✨ 创建新宠物…", menu)
        create_pet_action.triggered.connect(self.open_pet_create_dialog)
        menu.addAction(create_pet_action)

        self.message_action = QAction("💬 消息", menu)
        self.message_action.triggered.connect(self.open_message_drawer)
        menu.addAction(self.message_action)

        pause_action = QAction("暂停/恢复跑动", menu)
        pause_action.triggered.connect(
            lambda: self.window.set_paused(not self.window.paused)
        )
        menu.addAction(pause_action)

        self.pet_menu = menu.addMenu("切换宠物")
        self.pet_menu.aboutToShow.connect(self._rebuild_pet_menu)

        edge_menu = menu.addMenu("边缘吸附")
        attach_left = QAction("吸附到左侧", edge_menu)
        attach_left.triggered.connect(
            lambda _checked=False: self.edge_dock.attach(EdgeSide.LEFT)
        )
        edge_menu.addAction(attach_left)

        attach_right = QAction("吸附到右侧", edge_menu)
        attach_right.triggered.connect(
            lambda _checked=False: self.edge_dock.attach(EdgeSide.RIGHT)
        )
        edge_menu.addAction(attach_right)

        reveal_action = QAction("暂时展开", edge_menu)
        reveal_action.triggered.connect(self.edge_dock.reveal_from_edge)
        edge_menu.addAction(reveal_action)

        detach_action = QAction("解除吸附", edge_menu)
        detach_action.triggered.connect(self.edge_dock.detach)
        edge_menu.addAction(detach_action)

        cloud_menu = menu.addMenu("云端账户")
        self.cloud_status_action = QAction("未连接", cloud_menu)
        self.cloud_status_action.setEnabled(False)
        cloud_menu.addAction(self.cloud_status_action)

        login_action = QAction("登录或注册…", cloud_menu)
        login_action.triggered.connect(self.open_cloud_login)
        cloud_menu.addAction(login_action)

        sync_action = QAction("立即同步", cloud_menu)
        sync_action.triggered.connect(self.cloud_session.sync_now)
        cloud_menu.addAction(sync_action)

        sign_out_action = QAction("退出云端账户", cloud_menu)
        sign_out_action.triggered.connect(
            lambda _checked=False: self.cloud_session.sign_out()
        )
        cloud_menu.addAction(sign_out_action)

        hide_action = QAction("隐藏宠物", menu)
        hide_action.triggered.connect(self.window.hide)
        menu.addAction(hide_action)
        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        self.tray_menu = menu
        tray.activated.connect(self._tray_activated)
        return tray

    def _rebuild_pet_menu(self) -> None:
        self.pet_menu.clear()
        pets = self.pet_registry.list_pets()
        active_id = self.local_store.get_active_pet_id()
        if not pets:
            empty = QAction("没有可用宠物", self.pet_menu)
            empty.setEnabled(False)
            self.pet_menu.addAction(empty)
            return
        group = QActionGroup(self.pet_menu)
        group.setExclusive(True)
        for pet in pets:
            pet_id = pet.identity.pet_id
            selection = self.asset_catalog.selection_for(pet)
            label = pet.identity.name
            if not selection.exact:
                label += "（兼容形象）"
            action = QAction(label, self.pet_menu)
            action.setCheckable(True)
            action.setChecked(pet_id == active_id)
            action.triggered.connect(
                lambda _checked=False, pet_id=pet_id: self._switch_pet(pet_id)
            )
            group.addAction(action)
            self.pet_menu.addAction(action)
        self._pet_action_group = group

    def _switch_pet(self, pet_id: str) -> None:
        """Keep bundled/local pets local even when a cloud account is connected."""

        pet = self.local_store.get_pet(pet_id)
        if pet is None:
            return
        if pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID:
            self.pet_registry.switch_active_pet(pet_id)
            self._pets_changed()
            self.cloud_session.status_message.emit("已切换本地宠物")
            return
        self.cloud_session.switch_active_pet(pet_id)

    def open_cloud_login(self) -> None:
        if self._login_dialog is None:
            self._login_dialog = CloudLoginDialog(self.cloud_session)
            self._login_dialog.finished.connect(self._clear_login_dialog)
        self._login_dialog.show()
        self._login_dialog.raise_()
        self._login_dialog.activateWindow()

    def _clear_login_dialog(self, _result: int) -> None:
        if self._login_dialog is not None:
            self._login_dialog.deleteLater()
            self._login_dialog = None

    def open_pet_care_panel(self) -> None:
        if self._care_panel is None:
            self._care_panel = PetCarePanel()
            self._care_panel.action_requested.connect(self._request_pet_care)
        self._care_panel.set_pet(self.active_pet)
        self._care_panel.show()
        self._care_panel.raise_()
        self._care_panel.activateWindow()

    def open_message_drawer(self) -> None:
        """Open messages only after explicit user action; incoming messages never call this."""

        if self._message_drawer is None:
            self._message_drawer = MessageDrawer(self.cloud_session.message_cache)
            self._message_drawer.refresh_requested.connect(
                self.cloud_session.refresh_conversations
            )
            self._message_drawer.create_conversation_requested.connect(
                self.cloud_session.create_conversation
            )
            self._message_drawer.conversation_selected.connect(
                self.cloud_session.fetch_messages
            )
            self._message_drawer.send_requested.connect(self._send_message)
            self._message_drawer.read_requested.connect(
                self.cloud_session.mark_message_read
            )
        identity = self.cloud_session.identity
        self._message_drawer.set_account(
            identity.account_id if identity else None,
            identity.display_name if identity else "",
        )
        self._message_drawer.show()
        self._message_drawer.raise_()
        self._message_drawer.activateWindow()
        if identity is not None:
            self.cloud_session.refresh_conversations()

    def _send_message(self, conversation_id: str, content: str) -> None:
        identity = self.cloud_session.identity
        sender_pet_id: str | None = None
        if (
            identity is not None
            and self.active_pet.identity.primary_owner_account_id != LOCAL_ACCOUNT_ID
        ):
            sender_pet_id = self.active_pet.identity.pet_id
        self.cloud_session.send_message(
            conversation_id,
            content,
            sender_pet_id=sender_pet_id,
        )

    def _messages_changed(self) -> None:
        identity = self.cloud_session.identity
        unread = (
            self.cloud_session.message_cache.unread_count(identity.account_id)
            if identity is not None
            else 0
        )
        self.window.set_message_badge(unread)
        self.message_action.setText(f"💬 消息 ({unread})" if unread else "💬 消息")
        if self._message_drawer is not None:
            self._message_drawer.set_account(
                identity.account_id if identity else None,
                identity.display_name if identity else "",
            )
            if self._message_drawer.isVisible():
                self._message_drawer.refresh_from_cache()

    def _message_status(self, message: str) -> None:
        if self._message_drawer is None:
            return
        self._message_drawer.set_status(
            message,
            clear_message_input=message == "消息已发送",
            clear_recipient_input=message == "会话已创建",
        )

    def _message_failed(self, message: str) -> None:
        if self._message_drawer is not None:
            self._message_drawer.set_status(message, error=True)
        self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")

    def _request_pet_care(self, action: str) -> None:
        if self._care_panel is not None:
            self._care_panel.set_busy(True, f"正在提交{self._care_action_label(action)}…")
        if self.active_pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID:
            self._pet_care_failed(action, "本地演示宠物不写入云端状态")
            return
        self.cloud_session.care_for_pet(self.active_pet.identity.pet_id, action)

    @staticmethod
    def _care_action_label(action: str) -> str:
        return {
            "feed": "投喂",
            "play": "玩耍",
            "clean": "清洁",
            "pet": "摸摸",
            "rest": "休息",
        }.get(action, "照料")

    def _pet_care_succeeded(self, action: str, _payload: object) -> None:
        active = self.pet_registry.active_pet()
        if active is not None:
            self.active_pet = active
        self.window.show_care_feedback(action)
        label = self._care_action_label(action)
        if self._care_panel is not None:
            self._care_panel.set_pet(self.active_pet)
            self._care_panel.show_result(f"{label}完成，宠物状态已同步。")
        self.tray.showMessage(
            self.active_pet.identity.name,
            f"{label}完成",
            QSystemTrayIcon.MessageIcon.Information,
            1800,
        )

    def _pet_care_failed(self, action: str, message: str) -> None:
        label = self._care_action_label(action)
        if self._care_panel is not None:
            self._care_panel.show_result(f"{label}失败：{message}", error=True)
        self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")

    def _cloud_operation_succeeded(self, operation: str, payload: object) -> None:
        """Present confirmed growth events after CloudSession has applied them to SQLite."""

        if operation != "events" or not isinstance(payload, dict):
            return
        values = payload.get("events")
        if not isinstance(values, list):
            return
        priorities = {
            "bond_level_up": 1,
            "growth_level_up": 2,
            "growth_stage_changed": 3,
        }
        selected: tuple[int, str, str, str] | None = None
        active_id = self.active_pet.identity.pet_id
        for item in values:
            if not isinstance(item, dict):
                continue
            event_type = item.get("event_type")
            if event_type not in priorities:
                continue
            event_payload = item.get("payload")
            if not isinstance(event_payload, dict):
                continue
            pet_id = event_payload.get("pet_id")
            if pet_id != active_id:
                continue
            transition = event_payload.get("transition")
            if not isinstance(transition, dict):
                continue
            candidate = (
                priorities[event_type],
                str(event_type),
                str(transition.get("previous_value", "")),
                str(transition.get("current_value", "")),
            )
            if selected is None or candidate[0] > selected[0]:
                selected = candidate
        if selected is not None:
            _, event_type, previous_value, current_value = selected
            self._present_growth_event(event_type, previous_value, current_value)

    def _present_growth_event(
        self,
        event_type: str,
        previous_value: str,
        current_value: str,
    ) -> None:
        active = self.pet_registry.active_pet()
        if active is not None:
            self.active_pet = active
        self._refresh_active_pet_ui()
        self.window.trigger_growth_feedback(event_type)
        if event_type == "growth_stage_changed":
            message = f"成长阶段：{previous_value} → {current_value}"
        elif event_type == "growth_level_up":
            message = f"成长等级提升：{previous_value} → {current_value}"
        else:
            message = f"羁绊等级提升：{previous_value} → {current_value}"
        if self._care_panel is not None:
            self._care_panel.set_pet(self.active_pet)
            self._care_panel.show_result(message)
        self.tray.showMessage(
            self.active_pet.identity.name,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            2600,
        )

    def _cloud_state_changed(self, state: str) -> None:
        self.asset_downloader.set_base_url(self.cloud_api.base_url)
        if state == "connected":
            self._request_active_pet_assets()
        labels = {
            "disabled": "云端同步未启用",
            "offline": "云端离线",
            "authenticating": "正在认证",
            "binding": "正在绑定设备",
            "syncing": "正在同步",
            "connected": "云端已连接",
            "error": "云端连接异常",
        }
        self.cloud_status_action.setText(labels.get(state, state))
        self._messages_changed()

    def _cloud_status_message(self, message: str) -> None:
        if message:
            suffix = f" · {self._asset_status}" if self._asset_status else ""
            self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}{suffix}")

    def _pets_changed(self) -> None:
        active = self.pet_registry.active_pet()
        if active is None:
            pets = self.pet_registry.list_pets()
            if pets:
                active = self.pet_registry.switch_active_pet(pets[0].identity.pet_id)
        if active is not None:
            self.active_pet = active
            self._refresh_active_pet_ui()
        if self._care_panel is not None:
            self._care_panel.set_pet(self.active_pet)
        self._rebuild_pet_menu()

    def _refresh_active_pet_ui(self) -> None:
        selection = self.asset_catalog.selection_for(self.active_pet)
        self._asset_status = ""
        if selection.cache_key != self._asset_selection.cache_key:
            try:
                self.window.load_pet_assets(selection.manifest_path)
            except (OSError, ValueError) as exc:
                self._asset_status = f"形象加载失败：{exc}"
            else:
                self._asset_selection = selection
                if self.edge_dock.attached:
                    QTimer.singleShot(0, self.edge_dock.restore)
        if not selection.exact and not self._asset_status:
            if self._request_active_pet_assets():
                self._asset_status = "正在下载形象"
            else:
                self._asset_status = "使用兼容形象"
        title = f"{self.active_pet.identity.name} · MyPets"
        self.window.setWindowTitle(title)
        tooltip = f"{title} · {self._asset_status}" if self._asset_status else title
        self.tray.setToolTip(tooltip)
        if self._care_panel is not None:
            self._care_panel.set_pet(self.active_pet)

    def _request_active_pet_assets(self) -> bool:
        if (
            not self.settings.cloud_sync_enabled
            or self.active_pet.identity.primary_owner_account_id == LOCAL_ACCOUNT_ID
        ):
            return False
        try:
            return self.asset_downloader.request_for(self.active_pet)
        except (OSError, RuntimeError, ValueError) as exc:
            self._asset_status = f"形象下载失败：{exc}"
            return False

    def _asset_package_installed(
        self,
        template_id: str,
        identity_version: str,
        asset_version: str,
        _manifest_path: str,
    ) -> None:
        identity = self.active_pet.identity
        if (
            identity.template_id == template_id
            and identity.identity_version == identity_version
            and self.active_pet.asset_version == asset_version
        ):
            self._asset_status = "形象已更新"
            self._refresh_active_pet_ui()
        self._rebuild_pet_menu()

    def _asset_download_failed(self, template_id: str, message: str) -> None:
        if self.active_pet.identity.template_id == template_id:
            self._asset_status = f"形象下载失败：{message}"
            self.tray.setToolTip(f"{self.active_pet.identity.name} · {self._asset_status}")

    def _asset_download_status(self, message: str) -> None:
        if message:
            self._asset_status = message
            self.tray.setToolTip(f"{self.active_pet.identity.name} · {message}")

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_window(self) -> None:
        self.window.show()
        if self.edge_dock.attached:
            self.edge_dock.reveal_from_edge()
        self.window.raise_()
        self.window.activateWindow()

    def start(self, smoke_test_ms: int | None = None) -> int:
        self.window.place_at_start()
        self.show_window()
        QTimer.singleShot(0, self.edge_dock.restore)
        QTimer.singleShot(0, self.cloud_session.start)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if smoke_test_ms is not None:
            QTimer.singleShot(max(1, smoke_test_ms), self.quit)
        return self.qt_app.exec()

    def _on_bubble_action(self, action_code: str) -> None:
        if action_code == "touch":
            self.window.trigger_interaction()
        elif action_code == "feed":
            self.open_pet_care_panel()
        elif action_code == "chat":
            self.open_pet_chat_dialog()
        elif action_code == "checkin":
            self.open_health_analytics_dialog()
        elif action_code == "stats":
            self.open_pet_care_panel()

    def open_health_analytics_dialog(self) -> None:
        if self._health_dialog is None:
            self._health_dialog = HealthAnalyticsDialog(self.input_analytics, self.health_scheduler)
            self._health_dialog.checkin_requested.connect(self._on_health_checkin)
        self._health_dialog.refresh_data()
        self._health_dialog.show()
        self._health_dialog.raise_()
        self._health_dialog.activateWindow()

    def open_pet_chat_dialog(self) -> None:
        pet_name = self.active_pet.identity.name
        if self._chat_dialog is None:
            self._chat_dialog = PetChatDialog(pet_name=pet_name, engine=self.personality_engine)
            self._chat_dialog.pet_replied.connect(self._on_pet_chat_replied)
        self._chat_dialog.show()
        self._chat_dialog.raise_()
        self._chat_dialog.activateWindow()

    def open_pet_create_dialog(self) -> None:
        if self._create_dialog is None:
            self._create_dialog = PetCreateDialog()
            self._create_dialog.pet_created.connect(self._on_pet_created)
        self._create_dialog.show()
        self._create_dialog.raise_()
        self._create_dialog.activateWindow()

    def _on_health_reminder(self, reminder_type: str, title: str, message: str) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)
        self.window.trigger_interaction()

    def _on_health_checkin(self, reminder_type: str) -> None:
        self.window.trigger_interaction()

    def _on_pet_chat_replied(self, text: str, emotion: str) -> None:
        self.window.trigger_interaction()

    def _on_pet_created(self, name: str, template_id: str) -> None:
        pet_id = f"local_pet_{int(datetime.now().timestamp())}"
        identity = PetIdentity(
            template_id=template_id,
            identity_version="v1",
            name=name,
            primary_owner_account_id=LOCAL_ACCOUNT_ID,
        )
        profile = PetProfile(identity=identity, pet_id=pet_id, asset_version="v1")
        self.local_store.save_pet(profile)
        self.local_store.save_account_relation(
            AccountPetRelation(
                account_id=LOCAL_ACCOUNT_ID,
                pet_id=pet_id,
                role=PetRole.OWNER,
                affinity=50,
            ),
            make_active=True,
        )
        self.active_pet = profile
        self._refresh_active_pet_ui()
        self._rebuild_pet_menu()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        position = self.edge_dock.persistence_position()
        self.settings.start_x = position.x()
        self.settings.start_y = position.y()
        self.health_scheduler.stop()
        self.cloud_session.stop()
        try:
            save_settings(self.settings)
        finally:
            try:
                self.local_store.close()
            finally:
                self.tray.hide()
                if self._care_panel is not None:
                    self._care_panel.close()
                if self._message_drawer is not None:
                    self._message_drawer.close()
                if self._health_dialog is not None:
                    self._health_dialog.close()
                if self._chat_dialog is not None:
                    self._chat_dialog.close()
                if self._create_dialog is not None:
                    self._create_dialog.close()
                self.window.close()
                self.qt_app.quit()


def run(smoke_test_ms: int | None = None) -> int:
    return DesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
