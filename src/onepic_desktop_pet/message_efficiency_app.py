"""Final desktop composition layer for message search, unread navigation, and quick replies."""

from __future__ import annotations

from .customer_history_app import CustomerHistoryApplication
from .message_efficiency_client import MessageEfficiencyClient
from .message_efficiency_drawer import MessageEfficiencyDrawer
from .messaging import parse_conversation, parse_message


class MessageEfficiencyApplication(CustomerHistoryApplication):
    """Improve message handling without introducing another local message store."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.message_efficiency_client = MessageEfficiencyClient(
            self.cloud_session,
            self.cloud_api,
            parent=self.qt_app,
        )
        self.message_efficiency_client.search_received.connect(self._message_search_received)
        self.message_efficiency_client.window_received.connect(self._message_window_received)
        self.message_efficiency_client.unread_received.connect(self._message_unread_received)
        self.message_efficiency_client.quick_replies_received.connect(
            self._message_quick_replies_received
        )
        self.message_efficiency_client.request_failed.connect(self._message_efficiency_failed)
        self.cloud_session.messages_changed.connect(self._refresh_open_message_efficiency)

    def open_message_drawer(self) -> None:
        if self._message_drawer is None:
            drawer = MessageEfficiencyDrawer(self.cloud_session.message_cache)
            drawer.refresh_requested.connect(self.cloud_session.refresh_conversations)
            drawer.create_conversation_requested.connect(self.cloud_session.create_conversation)
            drawer.send_requested.connect(self._send_message)
            drawer.read_requested.connect(self.cloud_session.mark_message_read)
            drawer.related_detail_requested.connect(
                self.customer_navigation_client.load_conversation_target
            )
            drawer.search_requested.connect(self.message_efficiency_client.search)
            drawer.window_requested.connect(self._load_message_window)
            drawer.unread_requested.connect(self._load_message_unread)
            drawer.quick_replies_requested.connect(
                self.message_efficiency_client.load_quick_replies
            )
            drawer.quick_replies_update_requested.connect(
                self.message_efficiency_client.update_quick_replies
            )
            drawer.quick_replies_reset_requested.connect(
                self.message_efficiency_client.reset_quick_replies
            )
            self._message_drawer = drawer
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
            self.message_efficiency_client.load_quick_replies()

    def _drawer(self) -> MessageEfficiencyDrawer | None:
        return (
            self._message_drawer
            if isinstance(self._message_drawer, MessageEfficiencyDrawer)
            else None
        )

    def _load_message_window(self, conversation_id: str, center_sequence: int) -> None:
        self.message_efficiency_client.load_window(
            conversation_id,
            center_sequence=center_sequence,
            before=45,
            after=45,
        )

    def _load_message_unread(self, conversation_id: str, current_sequence: int) -> None:
        self.message_efficiency_client.load_unread(
            conversation_id,
            current_sequence=current_sequence,
        )

    def _message_search_received(self, query: str, payload: object) -> None:
        drawer = self._drawer()
        identity = self.cloud_session.identity
        if drawer is None or identity is None or not isinstance(payload, dict):
            return
        items = payload.get("items")
        try:
            for raw in items if isinstance(items, list) else []:
                if not isinstance(raw, dict):
                    continue
                conversation_data = raw.get("conversation")
                if isinstance(conversation_data, dict):
                    self.cloud_session.message_cache.upsert_conversation(
                        parse_conversation(
                            conversation_data,
                            account_id=identity.account_id,
                        )
                    )
                message_data = raw.get("matched_message")
                if isinstance(message_data, dict):
                    self.cloud_session.message_cache.upsert_message(
                        parse_message(message_data, account_id=identity.account_id)
                    )
        except ValueError as exc:
            drawer.set_status(f"搜索结果无效：{exc}", error=True)
            return
        drawer.set_search_results(query, payload)

    def _message_window_received(self, conversation_id: str, payload: object) -> None:
        drawer = self._drawer()
        identity = self.cloud_session.identity
        if drawer is None or identity is None or not isinstance(payload, dict):
            return
        items = payload.get("items")
        try:
            for raw in items if isinstance(items, list) else []:
                self.cloud_session.message_cache.upsert_message(
                    parse_message(raw, account_id=identity.account_id)
                )
        except ValueError as exc:
            drawer.set_status(f"消息窗口无效：{exc}", error=True)
            return
        drawer.set_message_window(conversation_id, payload)

    def _message_unread_received(self, conversation_id: str, payload: object) -> None:
        drawer = self._drawer()
        if drawer is not None:
            drawer.set_unread_navigation(conversation_id, payload)

    def _message_quick_replies_received(self, payload: object) -> None:
        drawer = self._drawer()
        if drawer is not None:
            drawer.set_quick_reply_preferences(payload)
            drawer.set_status("快捷回复已同步。")

    def _message_efficiency_failed(self, operation: str, message: str) -> None:
        drawer = self._drawer()
        if drawer is None:
            return
        drawer.set_status(message, error=True)
        if operation.startswith(("message_quick_update:", "message_quick_reset:")):
            settings = drawer._settings_dialog
            if settings is not None:
                settings.set_busy(False)
                settings.set_status(message, error=True)

    def _refresh_open_message_efficiency(self) -> None:
        drawer = self._drawer()
        if drawer is None or not drawer.isVisible():
            return
        conversation_id = drawer._selected_conversation_id
        if not conversation_id:
            return
        self.message_efficiency_client.load_unread(
            conversation_id,
            current_sequence=drawer._anchor_sequence,
        )


def run(smoke_test_ms: int | None = None) -> int:
    return MessageEfficiencyApplication().start(smoke_test_ms=smoke_test_ms)
