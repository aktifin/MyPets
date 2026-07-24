"""Read-only preview helpers for validated pet asset packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zipfile import BadZipFile, ZipFile

from PIL import Image, UnidentifiedImageError

REQUIRED_ACTIONS = (
    "idle",
    "walk",
    "sit",
    "sleep",
    "wave",
    "happy",
    "shy",
    "surprised",
    "annoyed",
    "sleepy",
    "curious",
    "selfie",
    "drag",
)


@dataclass(frozen=True)
class ActionPreview:
    name: str
    source_action: str
    frame_count: int
    fallback_to: str | None


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    return value


def _safe_name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    path = PurePosixPath(value.strip().replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} 必须是安全的包内相对路径")
    if ":" in path.parts[0]:
        raise ValueError(f"{field} 不得包含驱动器或 URL")
    return path.as_posix()


def load_manifest(package_path: Path) -> dict[str, Any]:
    try:
        with ZipFile(package_path) as archive:
            return dict(json.loads(archive.read("manifest.json").decode("utf-8")))
    except (BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("素材包中的 manifest.json 无法读取") from exc


def summarize_actions(manifest: Mapping[str, Any]) -> tuple[ActionPreview, ...]:
    animations = _object(manifest.get("animations"), "animations")
    fallbacks = _object(manifest.get("fallback_actions", {}), "fallback_actions")
    names = sorted(set(REQUIRED_ACTIONS) | {str(name) for name in animations} | {str(name) for name in fallbacks})

    def resolve(name: str, chain: tuple[str, ...] = ()) -> tuple[str, int, str | None]:
        if name in chain:
            raise ValueError("动作降级配置存在循环")
        frames = animations.get(name)
        if frames is not None:
            if not isinstance(frames, list) or not frames:
                raise ValueError(f"animations.{name} 必须是非空数组")
            return name, len(frames), None
        fallback = fallbacks.get(name)
        if not isinstance(fallback, str) or not fallback.strip():
            raise ValueError(f"动作 {name} 缺少素材和降级配置")
        source, frame_count, _ = resolve(fallback.strip(), (*chain, name))
        return source, frame_count, fallback.strip()

    return tuple(
        ActionPreview(name=name, source_action=source, frame_count=count, fallback_to=fallback)
        for name in names
        for source, count, fallback in [resolve(name)]
    )


def _resolved_frames(manifest: Mapping[str, Any], action: str) -> tuple[str, list[Any]]:
    animations = _object(manifest.get("animations"), "animations")
    fallbacks = _object(manifest.get("fallback_actions", {}), "fallback_actions")
    current = action
    seen: set[str] = set()
    while current not in animations:
        if current in seen:
            raise ValueError("动作降级配置存在循环")
        seen.add(current)
        fallback = fallbacks.get(current)
        if not isinstance(fallback, str) or not fallback.strip():
            raise ValueError(f"动作 {action} 不可预览")
        current = fallback.strip()
    frames = animations[current]
    if not isinstance(frames, list) or not frames:
        raise ValueError(f"动作 {current} 没有可预览帧")
    return current, frames


def render_preview_png(
    package_path: Path,
    manifest: Mapping[str, Any],
    *,
    action: str = "idle",
    frame_index: int = 0,
) -> bytes:
    _source_action, frames = _resolved_frames(manifest, action)
    if frame_index < 0 or frame_index >= len(frames):
        raise ValueError("预览帧序号越界")
    renderer = manifest.get("renderer")
    renderer_kind = "frames"
    renderer_data: Mapping[str, Any] = {}
    if renderer is not None:
        renderer_data = _object(renderer, "renderer")
        renderer_kind = str(renderer_data.get("kind", "frames"))

    try:
        with ZipFile(package_path) as archive:
            if renderer_kind == "spritesheet":
                sheet_path = _safe_name(renderer_data.get("path"), "renderer.path")
                frame = _object(frames[frame_index], f"animations.{action}[{frame_index}]")
                row = int(frame.get("row"))
                column = int(frame.get("column"))
                width = int(renderer_data.get("cell_width"))
                height = int(renderer_data.get("cell_height"))
                with Image.open(BytesIO(archive.read(sheet_path))) as sheet:
                    image = sheet.convert("RGBA").crop(
                        (column * width, row * height, (column + 1) * width, (row + 1) * height)
                    )
            else:
                frame_path = _safe_name(frames[frame_index], f"animations.{action}[{frame_index}]")
                with Image.open(BytesIO(archive.read(frame_path))) as source:
                    image = source.convert("RGBA")
    except (BadZipFile, KeyError, OSError, UnidentifiedImageError, TypeError, ValueError) as exc:
        raise ValueError("无法生成宠物素材预览") from exc

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
