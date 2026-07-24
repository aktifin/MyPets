"""Concrete read-only MyReminder provider and daily/weekday recurrence expansion."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .reminder_provider import ProviderOccurrence, ReminderProvider


@dataclass(frozen=True)
class MyReminderRule:
    rule_id: str
    title: str
    content: str
    local_time: time
    timezone: str
    weekdays: tuple[int, ...]
    enabled: bool
    priority: str
    category: str
    version: int


class MyReminderRuleTransport(Protocol):
    def fetch_rules(
        self,
        *,
        base_url: str,
        integration_secret: str,
        username: str,
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


class UrllibMyReminderRuleTransport:
    """Small dependency-free HTTP transport for the MyReminder integration sidecar."""

    def fetch_rules(
        self,
        *,
        base_url: str,
        integration_secret: str,
        username: str,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        query = urlencode({"username": username})
        request = Request(
            f"{base_url.rstrip('/')}/api/v1/rules?{query}",
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "MyPets-Backend/0.2-alpha",
                "X-MyPets-Integration-Secret": integration_secret,
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise RuntimeError(f"MyReminder 返回 HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"无法连接 MyReminder：{exc.reason}") from exc
        if len(raw) > 2 * 1024 * 1024:
            raise RuntimeError("MyReminder 规则响应超过 2 MiB")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("MyReminder 返回了无效 JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError("MyReminder 响应必须是 JSON 对象")
        return value


def normalize_myreminder_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("MyReminder 服务地址必须是有效的 http/https URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("MyReminder 服务地址不能包含凭据、查询参数或片段")
    return normalized


def _required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()[:maximum]


def _parse_time(value: object) -> time:
    text = _required_text(value, "time", 5)
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise ValueError("time 必须使用 HH:MM") from exc
    return parsed.time()


def _parse_weekdays(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("weekdays 必须是非空数组")
    weekdays = tuple(sorted({int(item) for item in value}))
    if any(item < 1 or item > 7 for item in weekdays):
        raise ValueError("weekdays 只能包含 1 到 7")
    return weekdays


def parse_myreminder_rule(value: object) -> MyReminderRule:
    if not isinstance(value, dict):
        raise ValueError("MyReminder 规则必须是对象")
    timezone_name = _required_text(value.get("timezone"), "timezone", 64)
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"未知 IANA 时区：{timezone_name}") from exc
    version = value.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise ValueError("version 必须是正整数")
    return MyReminderRule(
        rule_id=_required_text(value.get("id"), "id", 120),
        title=_required_text(value.get("title"), "title", 160),
        content=str(value.get("content") or "").strip()[:4000],
        local_time=_parse_time(value.get("time")),
        timezone=timezone_name,
        weekdays=_parse_weekdays(value.get("weekdays")),
        enabled=bool(value.get("enabled")),
        priority=_required_text(value.get("priority") or "normal", "priority", 32),
        category=_required_text(value.get("category") or "general", "category", 64),
        version=version,
    )


class MyReminderHttpProvider(ReminderProvider):
    provider_id = "myreminder"

    def __init__(
        self,
        *,
        base_url: str,
        integration_secret: str,
        timeout_seconds: float = 5.0,
        transport: MyReminderRuleTransport | None = None,
    ) -> None:
        self.base_url = normalize_myreminder_base_url(base_url)
        if len(integration_secret) < 24:
            raise ValueError("MyReminder 集成密钥至少需要 24 个字符")
        if not 0.5 <= timeout_seconds <= 30:
            raise ValueError("MyReminder 超时时间必须位于 0.5 到 30 秒")
        self.integration_secret = integration_secret
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport or UrllibMyReminderRuleTransport()

    def pull_occurrences(
        self,
        *,
        account_external_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> Iterable[ProviderOccurrence]:
        if window_start.tzinfo is None or window_end.tzinfo is None:
            raise ValueError("同步窗口必须包含时区")
        if window_end <= window_start:
            raise ValueError("同步窗口结束时间必须晚于开始时间")
        username = account_external_id.strip().lower()
        if not username:
            raise ValueError("MyReminder 外部账户标识不能为空")

        payload = self.transport.fetch_rules(
            base_url=self.base_url,
            integration_secret=self.integration_secret,
            username=username,
            timeout_seconds=self.timeout_seconds,
        )
        if payload.get("success") is not True:
            raise RuntimeError(str(payload.get("message") or "MyReminder 同步失败"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("MyReminder data 必须是对象")
        user = data.get("user")
        if not isinstance(user, dict) or str(user.get("username") or "").strip().lower() != username:
            raise RuntimeError("MyReminder 返回了其他账户的数据")
        rule_values = data.get("rules")
        if not isinstance(rule_values, list):
            raise RuntimeError("MyReminder rules 必须是数组")

        occurrences: list[ProviderOccurrence] = []
        for raw_rule in rule_values:
            rule = parse_myreminder_rule(raw_rule)
            if not rule.enabled:
                continue
            occurrences.extend(self._expand_rule(rule, window_start, window_end))
        occurrences.sort(key=lambda item: (item.scheduled_at, item.source_reminder_id))
        return occurrences

    @staticmethod
    def _expand_rule(
        rule: MyReminderRule,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ProviderOccurrence]:
        zone = ZoneInfo(rule.timezone)
        start_utc = window_start.astimezone(UTC)
        end_utc = window_end.astimezone(UTC)
        local_start = start_utc.astimezone(zone).date()
        local_end = end_utc.astimezone(zone).date()
        current: date = local_start
        values: list[ProviderOccurrence] = []
        while current <= local_end:
            if current.isoweekday() in rule.weekdays:
                scheduled_local = datetime.combine(current, rule.local_time, tzinfo=zone)
                scheduled_utc = scheduled_local.astimezone(UTC)
                if start_utc <= scheduled_utc < end_utc:
                    values.append(
                        ProviderOccurrence(
                            source_reminder_id=f"{rule.rule_id}:{current.isoformat()}",
                            title=rule.title,
                            content=rule.content,
                            scheduled_at=scheduled_utc,
                            timezone=rule.timezone,
                            priority=rule.priority,
                            category=rule.category,
                            version=rule.version,
                        )
                    )
            current += timedelta(days=1)
        return values
