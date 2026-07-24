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

    settings.edge_dock_enabled = bool(settings.edge_dock_enabled)
    settings.edge_snap_distance = min(120, max(8, int(settings.edge_snap_distance)))
    settings.edge_hide_delay_ms = min(10000, max(100, int(settings.edge_hide_delay_ms)))
    settings.edge_animation_ms = min(2000, max(0, int(settings.edge_animation_ms)))
    settings.edge_visible_ratio = min(0.80, max(0.10, float(settings.edge_visible_ratio)))
    if settings.edge_side not in {None, "left", "right"}:
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
    }
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
