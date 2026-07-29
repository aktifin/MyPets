"""Privacy-safe diagnostics and rotating desktop logs for MyPets."""

from __future__ import annotations

import json
import logging
import platform
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6 import __version__ as pyside_version

from .config import user_data_dir
from .release import APP_NAME, APP_VERSION, RELEASE_CHANNEL

_LOG_HANDLER_NAME = "mypets-diagnostic-file"


def diagnostics_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def desktop_log_path() -> Path:
    return diagnostics_dir() / "mypets.log"


def configure_logging() -> Path:
    """Configure one bounded UTF-8 application log and an uncaught-exception hook."""

    path = desktop_log_path()
    root = logging.getLogger()
    existing = next(
        (
            handler
            for handler in root.handlers
            if getattr(handler, "name", "") == _LOG_HANDLER_NAME
        ),
        None,
    )
    if existing is None:
        handler = RotatingFileHandler(
            path,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.name = _LOG_HANDLER_NAME
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)

    if not getattr(sys.excepthook, "_mypets_diagnostics", False):
        previous = sys.excepthook

        def _log_uncaught(exc_type, exc_value, traceback) -> None:
            logging.getLogger("mypets.crash").critical(
                "Uncaught desktop exception",
                exc_info=(exc_type, exc_value, traceback),
            )
            previous(exc_type, exc_value, traceback)

        setattr(_log_uncaught, "_mypets_diagnostics", True)
        sys.excepthook = _log_uncaught

    logging.getLogger("mypets.startup").info(
        "%s %s (%s) logging initialized",
        APP_NAME,
        APP_VERSION,
        RELEASE_CHANNEL,
    )
    return path


def _plain_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


def _settings_snapshot(settings: object | None) -> dict[str, object]:
    if settings is None:
        return {}
    allowed = (
        "display_height",
        "always_on_top",
        "edge_dock_enabled",
        "edge_side",
        "cloud_base_url",
        "cloud_sync_enabled",
        "cloud_sync_interval_ms",
        "proactive_care_enabled",
        "proactive_quiet_hours_enabled",
        "proactive_quiet_start",
        "proactive_quiet_end",
        "multi_pet_layout_enabled",
        "desktop_experience_version",
    )
    return {name: getattr(settings, name, None) for name in allowed}


def build_diagnostic_snapshot(app: Any | None = None) -> dict[str, object]:
    """Create a support snapshot without credentials, tokens, messages, or local database rows."""

    cloud_state = "unavailable"
    account: dict[str, str] | None = None
    pet: dict[str, object] | None = None
    pet_count = 0
    settings = None
    if app is not None:
        settings = getattr(app, "settings", None)
        session = getattr(app, "cloud_session", None)
        if session is not None:
            cloud_state = _plain_value(getattr(session, "state", "unknown")) or "unknown"
            identity = getattr(session, "identity", None)
            if identity is not None:
                account = {
                    "username": str(getattr(identity, "username", "")),
                    "display_name": str(getattr(identity, "display_name", "")),
                }
        active_pet = getattr(app, "active_pet", None)
        if active_pet is not None:
            identity = getattr(active_pet, "identity", None)
            presence = getattr(active_pet, "presence", "")
            pet = {
                "name": str(getattr(identity, "name", "")),
                "presence": _plain_value(presence),
                "growth_level": getattr(getattr(active_pet, "stats", None), "growth_level", None),
            }
        registry = getattr(app, "pet_registry", None)
        if registry is not None:
            try:
                pet_count = len(list(registry.list_pets()))
            except (AttributeError, TypeError):
                pet_count = 0

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "application": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "channel": RELEASE_CHANNEL,
        },
        "runtime": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pyside": pyside_version,
            "executable": Path(sys.executable).name,
        },
        "cloud": {
            "state": cloud_state,
            "account": account,
        },
        "desktop": {
            "pet_count": pet_count,
            "active_pet": pet,
            "settings": _settings_snapshot(settings),
            "user_data_directory": str(user_data_dir()),
            "log_file": str(desktop_log_path()),
        },
        "privacy": (
            "This report excludes passwords, access tokens, device secrets, credential-manager "
            "entries, message bodies, reminder text, pet database rows, and asset source images."
        ),
    }


def diagnostic_summary_text(app: Any | None = None) -> str:
    snapshot = build_diagnostic_snapshot(app)
    application = snapshot["application"]
    runtime = snapshot["runtime"]
    cloud = snapshot["cloud"]
    desktop = snapshot["desktop"]
    account = cloud.get("account") if isinstance(cloud, dict) else None
    account_text = "未登录"
    if isinstance(account, dict):
        account_text = str(account.get("display_name") or account.get("username") or "已登录")
    active_pet = desktop.get("active_pet") if isinstance(desktop, dict) else None
    pet_text = "无"
    if isinstance(active_pet, dict):
        pet_text = str(active_pet.get("name") or "当前宠物")
    return "\n".join(
        (
            f"应用：{application['name']} {application['version']} ({application['channel']})",
            f"系统：{runtime['platform']}",
            f"Python / PySide：{runtime['python']} / {runtime['pyside']}",
            f"云端状态：{cloud['state']} · 账户：{account_text}",
            f"宠物：{desktop['pet_count']} 只 · 当前：{pet_text}",
            f"用户数据：{desktop['user_data_directory']}",
            f"日志文件：{desktop['log_file']}",
            "诊断包不包含密码、令牌、设备密钥、消息正文和本地数据库内容。",
        )
    )


def export_diagnostic_bundle(app: Any | None, destination: Path) -> Path:
    """Write a bounded ZIP containing the JSON snapshot and current rotated text logs."""

    target = destination.expanduser()
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_diagnostic_snapshot(app)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr(
            "README.txt",
            "MyPets 诊断包\n\n"
            "该文件由用户主动导出，用于问题排查。\n"
            "不包含密码、访问令牌、设备密钥、消息正文、本地数据库或宠物原图。\n",
        )
        for log_file in sorted(diagnostics_dir().glob("mypets.log*")):
            if log_file.is_file() and log_file.stat().st_size <= 3 * 1024 * 1024:
                archive.write(log_file, f"logs/{log_file.name}")
    return target
