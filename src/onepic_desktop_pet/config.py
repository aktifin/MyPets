"""
本模块负责桌面宠物默认配置、用户配置、窗口状态和可选云端连接偏好的加载与保存。

设备密钥和访问令牌绝不写入该 JSON；长效设备密钥由操作系统凭据管理器保存。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any
from uuid import uuid4

from .cloud_types import normalize_base_url
from .resources import resource_path


@dataclass
class PetSettings:
    """保存桌面宠物功能参数和非敏感设备级状态。"""

    display_height: int = 220
    movement_interval_ms: int = 16
    movement_step: int = 1
    walk_frame_interval_ms: int = 90
    turn_pause_ms: int = 240
    idle_min_ms: int = 3000
    idle_max_ms: int = 7000
    action_min_ms: int = 3500
    action_max_ms: int = 7000
    inactive_sit_ms: int = 300000
    inactive_sleep_ms: int = 600000
    always_on_top: bool = True
    start_x: int | None = None
    start_y: int | None = None

    edge_dock_enabled: bool = True
    edge_snap_distance: int = 36
    edge_hide_delay_ms: int = 1400
    edge_animation_ms: int = 220
    edge_visible_ratio: float = 0.28
    edge_side: str | None = None
    edge_screen_name: str | None = None
    edge_offset_ratio: float | None = None

    cloud_base_url: str = "http://127.0.0.1:8000"
    cloud_sync_enabled: bool = False
    cloud_sync_interval_ms: int = 15000
    device_public_id: str = ""

    # Device-level fallback used for bundled local pets and before cloud preferences load.
    proactive_care_enabled: bool = True
    proactive_quiet_hours_enabled: bool = True
    proactive_quiet_start: str = "22:00"
    proactive_quiet_end: str = "08:00"
    proactive_min_interval_minutes: int = 120
    proactive_max_daily_notices: int = 3
    proactive_last_notice_at: str = ""
    proactive_notice_date: str = ""
    proactive_notice_count: int = 0
    proactive_suppressed_until: str = ""
    proactive_suppressed_notice_key: str = ""

    # Dual-pet layout is device-local and never changes cloud pet ownership or selection.
    multi_pet_layout_enabled: bool = False
    multi_pet_companion_pet_id: str = ""
    multi_pet_primary_x: int | None = None
    multi_pet_primary_y: int | None = None
    multi_pet_companion_x: int | None = None
    multi_pet_companion_y: int | None = None

    # Incremented only when a materially new customer onboarding flow is completed.
    desktop_experience_version: int = 0


def user_data_dir() -> Path:
    """返回当前用户的 MyPets 可写数据目录。"""

    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".desktop_pet"
    return root / "OnePicDesktopPet"


def user_settings_path() -> Path:
    """返回当前用户可写的设置文件路径。"""

    return user_data_dir() / "settings.json"


def _read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 对象；文件不存在时返回空对象。"""

    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取配置文件 {path}：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"配置文件必须包含 JSON 对象：{path}")
    return value


def _clock(value: object, fallback: str) -> str:
    try:
        hour_text, minute_text = str(value).strip().split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, AttributeError):
        hour_text, minute_text = fallback.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    return f"{max(0, min(23, hour)):02d}:{max(0, min(59, minute)):02d}"


def _optional_coordinate(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validated(data: dict[str, Any]) -> PetSettings:
    """过滤未知字段并对关键数值执行安全范围校验。"""

    allowed = {field.name for field in fields(PetSettings)}
    clean = {key: value for key, value in data.items() if key in allowed}
    settings = PetSettings(**clean)
    settings.display_height = min(600, max(120, int(settings.display_height)))
    settings.movement_interval_ms = min(100, max(16, int(settings.movement_interval_ms)))
    settings.movement_step = min(12, max(1, int(settings.movement_step)))
    settings.walk_frame_interval_ms = min(500, max(50, int(settings.walk_frame_interval_ms)))
    settings.turn_pause_ms = min(1200, max(0, int(settings.turn_pause_ms)))
    settings.idle_min_ms = max(500, int(settings.idle_min_ms))
    settings.idle_max_ms = max(settings.idle_min_ms, int(settings.idle_max_ms))
    settings.action_min_ms = max(1000, int(settings.action_min_ms))
    settings.action_max_ms = max(settings.action_min_ms, int(settings.action_max_ms))
    settings.inactive_sit_ms = max(5000, int(settings.inactive_sit_ms))
    settings.inactive_sleep_ms = max(
        settings.inactive_sit_ms + 5000,
        int(settings.inactive_sleep_ms),
    )

    settings.start_x = _optional_coordinate(settings.start_x)
    settings.start_y = _optional_coordinate(settings.start_y)
    settings.edge_dock_enabled = bool(settings.edge_dock_enabled)
    settings.edge_snap_distance = min(120, max(8, int(settings.edge_snap_distance)))
    settings.edge_hide_delay_ms = min(10000, max(100, int(settings.edge_hide_delay_ms)))
    settings.edge_animation_ms = min(2000, max(0, int(settings.edge_animation_ms)))
    settings.edge_visible_ratio = min(0.80, max(0.10, float(settings.edge_visible_ratio)))
    if settings.edge_side not in {None, "left", "right", "top", "bottom"}:
        settings.edge_side = None
    if settings.edge_screen_name is not None:
        settings.edge_screen_name = str(settings.edge_screen_name).strip() or None
    if settings.edge_offset_ratio is not None:
        settings.edge_offset_ratio = min(1.0, max(0.0, float(settings.edge_offset_ratio)))

    try:
        settings.cloud_base_url = normalize_base_url(str(settings.cloud_base_url))
    except ValueError:
        settings.cloud_base_url = PetSettings.cloud_base_url
    settings.cloud_sync_enabled = bool(settings.cloud_sync_enabled)
    settings.cloud_sync_interval_ms = min(
        300000,
        max(5000, int(settings.cloud_sync_interval_ms)),
    )
    device_public_id = str(settings.device_public_id).strip()
    settings.device_public_id = device_public_id if len(device_public_id) >= 8 else str(uuid4())

    settings.proactive_care_enabled = bool(settings.proactive_care_enabled)
    settings.proactive_quiet_hours_enabled = bool(settings.proactive_quiet_hours_enabled)
    settings.proactive_quiet_start = _clock(settings.proactive_quiet_start, "22:00")
    settings.proactive_quiet_end = _clock(settings.proactive_quiet_end, "08:00")
    settings.proactive_min_interval_minutes = min(
        1440, max(15, int(settings.proactive_min_interval_minutes))
    )
    settings.proactive_max_daily_notices = min(
        12, max(1, int(settings.proactive_max_daily_notices))
    )
    settings.proactive_notice_count = max(0, int(settings.proactive_notice_count))
    settings.proactive_last_notice_at = str(settings.proactive_last_notice_at or "")[:64]
    settings.proactive_notice_date = str(settings.proactive_notice_date or "")[:16]
    settings.proactive_suppressed_until = str(settings.proactive_suppressed_until or "")[:64]
    settings.proactive_suppressed_notice_key = str(
        settings.proactive_suppressed_notice_key or ""
    )[:200]

    settings.multi_pet_layout_enabled = bool(settings.multi_pet_layout_enabled)
    settings.multi_pet_companion_pet_id = str(
        settings.multi_pet_companion_pet_id or ""
    )[:64]
    settings.multi_pet_primary_x = _optional_coordinate(settings.multi_pet_primary_x)
    settings.multi_pet_primary_y = _optional_coordinate(settings.multi_pet_primary_y)
    settings.multi_pet_companion_x = _optional_coordinate(settings.multi_pet_companion_x)
    settings.multi_pet_companion_y = _optional_coordinate(settings.multi_pet_companion_y)

    settings.desktop_experience_version = max(0, int(settings.desktop_experience_version))
    return settings


_PERSISTED_FIELDS = {
    "display_height",
    "start_x",
    "start_y",
    "edge_dock_enabled",
    "edge_side",
    "edge_screen_name",
    "edge_offset_ratio",
    "cloud_base_url",
    "cloud_sync_enabled",
    "cloud_sync_interval_ms",
    "device_public_id",
    "proactive_care_enabled",
    "proactive_quiet_hours_enabled",
    "proactive_quiet_start",
    "proactive_quiet_end",
    "proactive_min_interval_minutes",
    "proactive_max_daily_notices",
    "proactive_last_notice_at",
    "proactive_notice_date",
    "proactive_notice_count",
    "proactive_suppressed_until",
    "proactive_suppressed_notice_key",
    "multi_pet_layout_enabled",
    "multi_pet_companion_pet_id",
    "multi_pet_primary_x",
    "multi_pet_primary_y",
    "multi_pet_companion_x",
    "multi_pet_companion_y",
    "desktop_experience_version",
}


def load_settings(
    default_path: Path | None = None,
    override_path: Path | None = None,
) -> PetSettings:
    """合并默认与用户配置；损坏的用户配置回退为默认配置。"""

    default_file = default_path or resource_path("config/settings.json")
    user_file = override_path or user_settings_path()
    base = _read_json(default_file)
    try:
        override = _read_json(user_file)
    except ValueError:
        override = {}
    base.update({key: value for key, value in override.items() if key in _PERSISTED_FIELDS})
    return _validated(base)


def save_settings(settings: PetSettings, path: Path | None = None) -> Path:
    """将非敏感设备设置原子写入用户目录并返回最终路径。"""

    target = path or user_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    state = {
        "display_height": settings.display_height,
        "start_x": settings.start_x,
        "start_y": settings.start_y,
        "edge_dock_enabled": settings.edge_dock_enabled,
        "edge_side": settings.edge_side,
        "edge_screen_name": settings.edge_screen_name,
        "edge_offset_ratio": settings.edge_offset_ratio,
        "cloud_base_url": settings.cloud_base_url,
        "cloud_sync_enabled": settings.cloud_sync_enabled,
        "cloud_sync_interval_ms": settings.cloud_sync_interval_ms,
        "device_public_id": settings.device_public_id,
        "proactive_care_enabled": settings.proactive_care_enabled,
        "proactive_quiet_hours_enabled": settings.proactive_quiet_hours_enabled,
        "proactive_quiet_start": settings.proactive_quiet_start,
        "proactive_quiet_end": settings.proactive_quiet_end,
        "proactive_min_interval_minutes": settings.proactive_min_interval_minutes,
        "proactive_max_daily_notices": settings.proactive_max_daily_notices,
        "proactive_last_notice_at": settings.proactive_last_notice_at,
        "proactive_notice_date": settings.proactive_notice_date,
        "proactive_notice_count": settings.proactive_notice_count,
        "proactive_suppressed_until": settings.proactive_suppressed_until,
        "proactive_suppressed_notice_key": settings.proactive_suppressed_notice_key,
        "multi_pet_layout_enabled": settings.multi_pet_layout_enabled,
        "multi_pet_companion_pet_id": settings.multi_pet_companion_pet_id,
        "multi_pet_primary_x": settings.multi_pet_primary_x,
        "multi_pet_primary_y": settings.multi_pet_primary_y,
        "multi_pet_companion_x": settings.multi_pet_companion_x,
        "multi_pet_companion_y": settings.multi_pet_companion_y,
        "desktop_experience_version": settings.desktop_experience_version,
    }
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
