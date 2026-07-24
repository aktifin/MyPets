"""Validated pet asset manifests, bundled discovery, cache installation, and Qt loading."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap

from .behavior import PetState
from .config import user_data_dir
from .domain import PetProfile
from .resources import resource_root

SUPPORTED_SCHEMA_VERSIONS = {"2.0", "2.1"}
DEFAULT_WALK_MOTION_FACTORS = (0.45, 0.7, 1.2, 1.65, 0.45, 0.7, 1.2, 1.65)

_STATE_NAMES: dict[PetState, str] = {
    PetState.IDLE: "idle",
    PetState.WALK: "walk",
    PetState.SIT: "sit",
    PetState.SLEEP: "sleep",
    PetState.WAVE: "wave",
    PetState.HAPPY: "happy",
    PetState.SHY: "shy",
    PetState.SURPRISED: "surprised",
    PetState.ANNOYED: "annoyed",
    PetState.SLEEPY: "sleepy",
    PetState.CURIOUS: "curious",
    PetState.SELFIE: "selfie",
    PetState.DRAG: "drag",
}


@dataclass(frozen=True)
class FileFrame:
    path: str


@dataclass(frozen=True)
class SheetFrame:
    row: int
    column: int


FrameReference = FileFrame | SheetFrame


@dataclass(frozen=True)
class PetAssetIdentity:
    template_id: str
    identity_version: str
    asset_version: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.template_id, self.identity_version, self.asset_version


@dataclass(frozen=True)
class SpritesheetLayout:
    path: str
    columns: int
    rows: int
    cell_width: int
    cell_height: int


@dataclass(frozen=True)
class BundledPetDefinition:
    pet_id: str
    name: str
    identity: PetAssetIdentity


@dataclass(frozen=True)
class PetAssetManifest:
    path: Path
    identity: PetAssetIdentity
    display_name: str
    animations: Mapping[str, tuple[FrameReference, ...]]
    walk_motion_factors: tuple[float, ...]
    spritesheet: SpritesheetLayout | None
    icon_path: str | None
    local_pet: BundledPetDefinition | None
    file_metadata: Mapping[str, tuple[str | None, int | None]]

    def referenced_paths(self) -> tuple[str, ...]:
        values: set[str] = set()
        if self.spritesheet is not None:
            values.add(self.spritesheet.path)
        else:
            for frames in self.animations.values():
                for frame in frames:
                    if isinstance(frame, FileFrame):
                        values.add(frame.path)
        if self.icon_path:
            values.add(self.icon_path)
        return tuple(sorted(values))


@dataclass(frozen=True)
class PetAssetSelection:
    manifest_path: Path | None
    identity: PetAssetIdentity | None
    source: str
    exact: bool

    @property
    def cache_key(self) -> tuple[str, str, str, str]:
        if self.identity is None:
            return "legacy-local", "", "", str(self.manifest_path or "")
        return (*self.identity.key, str(self.manifest_path or ""))


@dataclass(frozen=True)
class PetAssetBundle:
    manifest: PetAssetManifest
    pixmaps: Mapping[PetState, list[QPixmap]]


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} 必须是正整数")
    return value


def _safe_relative(value: Any, field: str) -> str:
    raw = _string(value, field).replace("\\", "/")
    path = Path(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} 必须是安全的包内相对路径")
    if ":" in path.parts[0]:
        raise ValueError(f"{field} 不得包含驱动器或 URL")
    return path.as_posix()


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取宠物素材清单 {path}：{exc}") from exc
    return _object(value, "manifest")


def _parse_file_metadata(value: Any) -> dict[str, tuple[str | None, int | None]]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ValueError("files 必须是数组")
    result: dict[str, tuple[str | None, int | None]] = {}
    for index, item in enumerate(value):
        data = _object(item, f"files[{index}]")
        path = _safe_relative(data.get("path"), f"files[{index}].path")
        checksum = data.get("sha256")
        if checksum is not None:
            checksum = _string(checksum, f"files[{index}].sha256").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError(f"files[{index}].sha256 必须是64位十六进制")
        size = data.get("size")
        if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
            raise ValueError(f"files[{index}].size 必须是非负整数")
        if path in result:
            raise ValueError(f"files 包含重复路径：{path}")
        result[path] = checksum, size
    return result


def _parse_frame(value: Any, field: str, *, renderer_kind: str) -> FrameReference:
    if renderer_kind == "frames":
        return FileFrame(_safe_relative(value, field))
    data = _object(value, field)
    row = data.get("row")
    column = data.get("column")
    if isinstance(row, bool) or not isinstance(row, int) or row < 0:
        raise ValueError(f"{field}.row 必须是非负整数")
    if isinstance(column, bool) or not isinstance(column, int) or column < 0:
        raise ValueError(f"{field}.column 必须是非负整数")
    return SheetFrame(row, column)


def load_pet_asset_manifest(path: Path | str) -> PetAssetManifest:
    manifest_path = Path(path).resolve()
    data = _read_json(manifest_path)
    schema_version = _string(data.get("schema_version"), "schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"不支持的宠物素材清单版本：{schema_version}")

    identity = PetAssetIdentity(
        template_id=_string(data.get("template_id", data.get("template_code")), "template_id"),
        identity_version=_string(data.get("identity_version"), "identity_version"),
        asset_version=_string(data.get("asset_version"), "asset_version"),
    )
    display_name = str(data.get("display_name") or data.get("name") or identity.template_id).strip()

    renderer_data = data.get("renderer")
    renderer_kind = "frames"
    spritesheet: SpritesheetLayout | None = None
    if renderer_data is not None:
        renderer = _object(renderer_data, "renderer")
        renderer_kind = _string(renderer.get("kind"), "renderer.kind")
        if renderer_kind not in {"frames", "spritesheet"}:
            raise ValueError("renderer.kind 仅支持 frames 或 spritesheet")
        if renderer_kind == "spritesheet":
            spritesheet = SpritesheetLayout(
                path=_safe_relative(renderer.get("path"), "renderer.path"),
                columns=_positive_int(renderer.get("columns"), "renderer.columns"),
                rows=_positive_int(renderer.get("rows"), "renderer.rows"),
                cell_width=_positive_int(renderer.get("cell_width"), "renderer.cell_width"),
                cell_height=_positive_int(renderer.get("cell_height"), "renderer.cell_height"),
            )

    raw_animations = _object(data.get("animations"), "animations")
    fallback_actions = data.get("fallback_actions", {})
    fallback_actions = _object(fallback_actions, "fallback_actions")
    parsed: dict[str, tuple[FrameReference, ...]] = {}

    def resolve_animation(name: str, chain: tuple[str, ...] = ()) -> tuple[FrameReference, ...]:
        if name in parsed:
            return parsed[name]
        if name in chain:
            raise ValueError(f"动作降级形成循环：{' -> '.join((*chain, name))}")
        raw_frames = raw_animations.get(name)
        if raw_frames is None:
            fallback = fallback_actions.get(name)
            if fallback is None:
                raise ValueError(f"缺少必需动作且未配置降级：{name}")
            frames = resolve_animation(_string(fallback, f"fallback_actions.{name}"), (*chain, name))
            parsed[name] = frames
            return frames
        if not isinstance(raw_frames, list) or not raw_frames:
            raise ValueError(f"animations.{name} 必须是非空数组")
        frames = tuple(
            _parse_frame(item, f"animations.{name}[{index}]", renderer_kind=renderer_kind)
            for index, item in enumerate(raw_frames)
        )
        if spritesheet is not None:
            for frame in frames:
                assert isinstance(frame, SheetFrame)
                if frame.row >= spritesheet.rows or frame.column >= spritesheet.columns:
                    raise ValueError(f"animations.{name} 的精灵表坐标越界")
        parsed[name] = frames
        return frames

    for name in set(raw_animations) | set(fallback_actions):
        resolve_animation(_string(name, "animation name"))
    for name in _STATE_NAMES.values():
        resolve_animation(name)

    raw_motion = data.get("walk_motion_factors")
    walk_count = len(parsed["walk"])
    if raw_motion is None:
        motion = DEFAULT_WALK_MOTION_FACTORS if walk_count == 8 else (1.0,) * walk_count
    else:
        if not isinstance(raw_motion, list) or len(raw_motion) != walk_count:
            raise ValueError("走路位移曲线必须与走路动画帧数一致")
        try:
            motion = tuple(float(item) for item in raw_motion)
        except (TypeError, ValueError) as exc:
            raise ValueError("walk_motion_factors 必须全部是数字") from exc
        if any(item <= 0 or item > 4 for item in motion):
            raise ValueError("walk_motion_factors 必须位于 (0, 4] 区间")

    icon_path = data.get("icon")
    if icon_path is not None:
        icon_path = _safe_relative(icon_path, "icon")

    local_pet = None
    if data.get("local_pet") is not None:
        local_data = _object(data.get("local_pet"), "local_pet")
        local_pet = BundledPetDefinition(
            pet_id=_string(local_data.get("pet_id"), "local_pet.pet_id"),
            name=_string(local_data.get("name"), "local_pet.name"),
            identity=identity,
        )

    manifest = PetAssetManifest(
        path=manifest_path,
        identity=identity,
        display_name=display_name,
        animations=parsed,
        walk_motion_factors=motion,
        spritesheet=spritesheet,
        icon_path=icon_path,
        local_pet=local_pet,
        file_metadata=_parse_file_metadata(data.get("files")),
    )
    validate_package_files(manifest)
    return manifest


def validate_package_files(manifest: PetAssetManifest) -> None:
    root = manifest.path.parent.resolve()
    for relative in manifest.referenced_paths():
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError(f"素材路径逃逸包目录：{relative}")
        if not path.is_file():
            raise FileNotFoundError(f"缺少宠物素材：{path}")
        checksum, expected_size = manifest.file_metadata.get(relative, (None, None))
        if expected_size is not None and path.stat().st_size != expected_size:
            raise ValueError(f"宠物素材大小不匹配：{relative}")
        if checksum is not None:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != checksum:
                raise ValueError(f"宠物素材哈希不匹配：{relative}")


def load_pet_asset_bundle(path: Path | str) -> PetAssetBundle:
    manifest = load_pet_asset_manifest(path)
    pixmaps: dict[PetState, list[QPixmap]] = {}
    sheet: QPixmap | None = None
    if manifest.spritesheet is not None:
        sheet_path = manifest.path.parent / manifest.spritesheet.path
        sheet = QPixmap(str(sheet_path))
        if sheet.isNull():
            raise ValueError(f"无法加载宠物精灵表：{sheet_path}")
        expected_width = manifest.spritesheet.columns * manifest.spritesheet.cell_width
        expected_height = manifest.spritesheet.rows * manifest.spritesheet.cell_height
        if sheet.width() != expected_width or sheet.height() != expected_height:
            raise ValueError(
                f"精灵表尺寸必须为 {expected_width}×{expected_height}，实际为 {sheet.width()}×{sheet.height()}"
            )

    for state, name in _STATE_NAMES.items():
        frames: list[QPixmap] = []
        for reference in manifest.animations[name]:
            if isinstance(reference, FileFrame):
                frame_path = manifest.path.parent / reference.path
                pixmap = QPixmap(str(frame_path))
            else:
                assert sheet is not None and manifest.spritesheet is not None
                pixmap = sheet.copy(
                    QRect(
                        reference.column * manifest.spritesheet.cell_width,
                        reference.row * manifest.spritesheet.cell_height,
                        manifest.spritesheet.cell_width,
                        manifest.spritesheet.cell_height,
                    )
                )
            if pixmap.isNull():
                raise ValueError(f"无法加载动作 {name} 的宠物素材帧")
            frames.append(pixmap)
        pixmaps[state] = frames
    return PetAssetBundle(manifest=manifest, pixmaps=pixmaps)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class PetAssetCatalog:
    """Resolve exact cached or bundled packages, with the public demo as a safe fallback."""

    def __init__(
        self,
        cache_root: Path | None = None,
        bundled_manifest_paths: list[Path] | None = None,
    ) -> None:
        self.cache_root = cache_root or user_data_dir() / "pet-assets"
        root = resource_root()
        if bundled_manifest_paths is None:
            paths = [root / "assets" / "pet" / "manifest.json"]
            outputs = root / "outputs"
            if outputs.is_dir():
                paths.extend(sorted(outputs.glob("*/manifest.json")))
        else:
            paths = bundled_manifest_paths
        self.validation_errors: dict[Path, str] = {}
        self._bundled: dict[tuple[str, str, str], PetAssetManifest] = {}
        for path in paths:
            if not path.is_file():
                continue
            try:
                manifest = load_pet_asset_manifest(path)
            except (OSError, ValueError) as exc:
                self.validation_errors[path] = str(exc)
                continue
            self._bundled[manifest.identity.key] = manifest
        self._demo = next(
            (
                manifest
                for manifest in self._bundled.values()
                if manifest.identity.template_id == "official.onepic.demo"
            ),
            None,
        )

    def bundled_local_pets(self) -> list[BundledPetDefinition]:
        return sorted(
            [manifest.local_pet for manifest in self._bundled.values() if manifest.local_pet],
            key=lambda item: (item.name, item.pet_id),
        )

    def cache_manifest_path(self, identity: PetAssetIdentity) -> Path:
        return (
            self.cache_root
            / _slug(identity.template_id)
            / _slug(identity.identity_version)
            / _slug(identity.asset_version)
            / "manifest.json"
        )

    def selection_for(self, profile: PetProfile) -> PetAssetSelection:
        identity = PetAssetIdentity(
            profile.identity.template_id,
            profile.identity.identity_version,
            profile.asset_version,
        )
        if identity.template_id == "local.default":
            return PetAssetSelection(None, identity, "legacy-local", True)
        cached_path = self.cache_manifest_path(identity)
        if cached_path.is_file():
            try:
                cached = load_pet_asset_manifest(cached_path)
            except (OSError, ValueError):
                pass
            else:
                if cached.identity == identity:
                    return PetAssetSelection(cached.path, identity, "cache", True)
        bundled = self._bundled.get(identity.key)
        if bundled is not None:
            return PetAssetSelection(bundled.path, identity, "bundled", True)
        if self._demo is None:
            raise FileNotFoundError("没有可用的默认宠物形象包")
        return PetAssetSelection(self._demo.path, self._demo.identity, "fallback", False)

    def install_package(
        self,
        source_manifest_path: Path | str,
        *,
        expected: PetAssetIdentity | None = None,
    ) -> Path:
        source = load_pet_asset_manifest(source_manifest_path)
        if expected is not None and source.identity != expected:
            raise ValueError("下载的宠物形象包身份或版本与请求不匹配")
        destination = self.cache_manifest_path(source.identity).parent
        temporary = destination.with_name(destination.name + ".installing")
        backup = destination.with_name(destination.name + ".previous")
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        temporary.mkdir(parents=True, exist_ok=True)
        for relative in ("manifest.json", *source.referenced_paths()):
            source_path = source.path if relative == "manifest.json" else source.path.parent / relative
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
        installed = load_pet_asset_manifest(temporary / "manifest.json")
        if installed.identity != source.identity:
            raise ValueError("缓存安装后的宠物形象身份发生变化")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.replace(backup)
        try:
            temporary.replace(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return destination / "manifest.json"
