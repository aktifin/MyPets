"""Reminder HTTP reconciliation and durable command retry using the shared device session."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController
from .reminder_cache import ReminderCache, ReminderCommand
from .reminders import parse_reminder_occurrence


class ReminderCloudController(QObject):
    reminders_changed = Signal()
    status_message = Signal(str)
    action_synced = Signal(str, str)
    action_failed = Signal(str, str, str)
    account_changed = Signal(str)

    def __init__(
        self,
        api: CloudApiClient,
        session: CloudSessionController,
        cache: ReminderCache,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.api = api
        self.session = session
        self.cache = cache
        self._refresh_in_flight = False
        self._command_in_flight: ReminderCommand | None = None
        self.api.operation_succeeded.connect(self._on_success)
        self.api.operation_failed.connect(self._on_failure)
        self.session.state_changed.connect(self._on_session_state)

    @property
    def account_id(self) -> str:
        if self.session.identity is not None:
            return self.session.identity.account_id
        credentials = getattr(self.session, "_credentials", None)
        return credentials.account_id if credentials is not None else ""

    def refresh(self) -> None:
        if not self.session.connected or self._refresh_in_flight:
            return
        try:
            token = self.api._require_device_token()
            self._refresh_in_flight = True
            self.api._request(
                "reminders",
                "GET",
                "/api/v1/reminders/occurrences",
                token=token,
                query={"limit": 500},
            )
        except (RuntimeError, ValueError) as exc:
            self._refresh_in_flight = False
            self.status_message.emit(str(exc))

    def deliver(self, occurrence_id: str) -> bool:
        return self._queue_action(occurrence_id, "delivered")

    def complete(self, occurrence_id: str) -> bool:
        return self._queue_action(occurrence_id, "completed")

    def snooze(self, occurrence_id: str, minutes: int) -> bool:
        return self._queue_action(
            occurrence_id,
            "snoozed",
            snooze_minutes=minutes,
        )

    def dismiss(self, occurrence_id: str) -> bool:
        return self._queue_action(occurrence_id, "dismissed")

    def _queue_action(
        self,
        occurrence_id: str,
        action: str,
        *,
        snooze_minutes: int | None = None,
    ) -> bool:
        account_id = self.account_id
        if not account_id:
            self.action_failed.emit(action, occurrence_id, "没有可用账户身份")
            return False
        try:
            occurrence = self.cache.get(occurrence_id)
            if occurrence is None or occurrence.account_id != account_id:
                raise KeyError("本地不存在当前账户的提醒实例")
            if action == "completed":
                self.cache.complete_locally(occurrence_id)
            elif action == "snoozed":
                self.cache.snooze_locally(
                    occurrence_id,
                    int(snooze_minutes or 0),
                    now=datetime.now().astimezone(),
                )
            elif action == "dismissed":
                self.cache.dismiss_locally(occurrence_id)
            self.cache.enqueue(
                account_id=account_id,
                occurrence_id=occurrence_id,
                action=action,
                snooze_minutes=snooze_minutes,
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            self.action_failed.emit(action, occurrence_id, str(exc))
            return False
        self.reminders_changed.emit()
        self.status_message.emit(
            "提醒操作正在同步"
            if self.session.connected
            else "提醒操作已保存在本机，联网后自动同步"
        )
        self._flush_commands()
        return True

    def _flush_commands(self) -> None:
        account_id = self.account_id
        if (
            not account_id
            or not self.session.connected
            or self._command_in_flight is not None
        ):
            return
        pending = self.cache.pending_commands(account_id, limit=1)
        if not pending:
            return
        command = pending[0]
        try:
            token = self.api._require_device_token()
            operation = (
                f"reminder_command:{command.command_id}:"
                f"{command.action}:{command.occurrence_id}"
            )
            path_suffix = {
                "delivered": "delivered",
                "completed": "complete",
                "snoozed": "snooze",
                "dismissed": "dismiss",
            }[command.action]
            payload: dict[str, Any] = {}
            if command.action == "snoozed":
                payload["minutes"] = command.snooze_minutes
            self._command_in_flight = command
            self.api._json_request(
                operation,
                "POST",
                f"/api/v1/reminders/occurrences/{command.occurrence_id}/{path_suffix}",
                payload,
                token=token,
                headers={"Idempotency-Key": command.idempotency_key},
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            self._command_in_flight = None
            self.action_failed.emit(command.action, command.occurrence_id, str(exc))

    def _on_session_state(self, state: str) -> None:
        self.account_changed.emit(self.account_id)
        if state == "connected":
            self.refresh()
            self._flush_commands()

    def _on_success(self, operation: str, payload: object) -> None:
        if operation == "events":
            self.refresh()
            return
        if operation == "reminders":
            self._refresh_in_flight = False
            if not isinstance(payload, list):
                self.status_message.emit("提醒列表响应必须是数组")
                return
            account_id = self.account_id
            try:
                for item in payload:
                    self.cache.put(
                        parse_reminder_occurrence(item, account_id=account_id)
                    )
            except ValueError as exc:
                self.status_message.emit(f"提醒列表响应无效：{exc}")
                return
            self.reminders_changed.emit()
            self._flush_commands()
            return
        if not operation.startswith("reminder_command:"):
            return
        command = self._command_in_flight
        self._command_in_flight = None
        if command is None or not isinstance(payload, dict):
            self.status_message.emit("提醒命令响应无效")
            return
        try:
            occurrence = parse_reminder_occurrence(
                payload.get("occurrence"),
                account_id=command.account_id,
            )
            self.cache.put(occurrence)
            if command.action in {"completed", "snoozed", "dismissed"}:
                self.cache.archive_notification(
                    command.account_id,
                    command.occurrence_id,
                )
            self.cache.acknowledge(command.command_id)
        except (KeyError, ValueError) as exc:
            self.action_failed.emit(command.action, command.occurrence_id, str(exc))
            return
        self.action_synced.emit(command.action, command.occurrence_id)
        self.reminders_changed.emit()
        self._flush_commands()

    def _on_failure(self, operation: str, status: int, detail: str) -> None:
        if operation == "reminders":
            self._refresh_in_flight = False
            self.status_message.emit(detail)
            return
        if not operation.startswith("reminder_command:"):
            return
        command = self._command_in_flight
        self._command_in_flight = None
        if command is None:
            return
        transient = status in {0, 401, 503}
        if not transient:
            self.cache.acknowledge(command.command_id)
            self.refresh()
        self.action_failed.emit(command.action, command.occurrence_id, detail)
        if status == 401:
            QTimer.singleShot(0, self._restart_session)

    def _restart_session(self) -> None:
        self.session.stop()
        self.session.start()
