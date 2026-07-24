"""Security validation for administrator-uploaded pet asset ZIP packages."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zipfile import BadZipFile, ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError

_REQUIRED_ACTIONS = {
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
}


@dataclass(frozen=True)
class ValidatedAssetPackage:
    manifest: dict[str, Any]
    package_sha256: str
    package_size: int

    @property
    def manifest_json(self) -> str:
        return json.dumps(self.manifest, ensure_ascii=False, separators=(",", ":"))


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _safe_name(value: Any, field: str) -> str:
    raw = _string(value, field).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} 必须是安全的包内相对路径")
    if ":" in path.parts[0]:
        raise ValueError(f"{field} 不得包含驱动器或 URL")
    return path.as_posix()


def _is_symlink(info: ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


def _referenced_paths(manifest: Mapping[str, Any]) -> set[str]:
    references: set[str] = set()
    renderer = manifest.get("renderer")
    renderer_kind = "frames"
    if renderer is not None:
        renderer_data = _object(renderer, "renderer")
        renderer_kind = _string(renderer_data.get("kind"), "renderer.kind")
        if renderer_kind not in {"frames", "spritesheet"}:
            raise ValueError("renderer.kind 只支持 frames 或 spritesheet")
        if renderer_kind == "spritesheet":
            references.add(_safe_name(renderer_data.get("path"), "renderer.path"))
            for field in ("columns", "rows", "cell_width", "cell_height"):
                value = renderer_data.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError(f"renderer.{field} 必须是正整数")

    animations = _object(manifest.get("animations"), "animations")
    fallbacks = _object(manifest.get("fallback_actions", {}), "fallback_actions")
    resolved: set[str] = set()

    def resolve(name: str, chain: tuple[str, ...] = ()) -> None:
        if name in resolved:
            return
        if name in chain:
            raise ValueError("动作降级配置存在循环")
        raw_frames = animations.get(name)
        if raw_frames is None:
            fallback = fallbacks.get(name)
            if fallback is None:
                raise ValueError(f"缺少必需动作且未配置降级：{name}")
            resolve(_string(fallback, f"fallback_actions.{name}"), (*chain, name))
            resolved.add(name)
            return
        if not isinstance(raw_frames, list) or not raw_frames:
            raise ValueError(f"animations.{name} 必须是非空数组")
        if renderer_kind == "frames":
            for index, item in enumerate(raw_frames):
                references.add(_safe_name(item, f"animations.{name}[{index}]"))
        else:
            renderer_data = _object(renderer, "renderer")
            rows = int(renderer_data["rows"])
            columns = int(renderer_data["columns"])
            for index, item in enumerate(raw_frames):
                frame = _object(item, f"animations.{name}[{index}]")
                row = frame.get("row")
                column = frame.get("column")
                if isinstance(row, bool) or not isinstance(row, int) or not 0 <= row < rows:
                    raise ValueError(f"animations.{name}[{index}].row 越界")
                if (
                    isinstance(column, bool)
                    or not isinstance(column, int)
                    or not 0 <= column < columns
                ):
                    raise ValueError(f"animations.{name}[{index}].column 越界")
        resolved.add(name)

    for action in _REQUIRED_ACTIONS | set(map(str, animations)) | set(map(str, fallbacks)):
        resolve(action)

    icon = manifest.get("icon")
    if icon is not None:
        references.add(_safe_name(icon, "icon"))
    return references


def validate_asset_package(
    data: bytes,
    *,
    expected_template_id: str,
    expected_identity_version: str,
    expected_asset_version: str,
    max_package_bytes: int,
    max_uncompressed_bytes: int,
    max_files: int,
) -> ValidatedAssetPackage:
    if not data:
        raise ValueError("素材包不能为空")
    if len(data) > max_package_bytes:
        raise ValueError("素材包压缩大小超过限制")
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise ValueError("素材包不是有效 ZIP 文件") from exc

    with archive:
        infos = archive.infolist()
        files = [info for info in infos if not info.is_dir()]
        if len(files) > max_files:
            raise ValueError("素材包文件数量超过限制")
        if sum(info.file_size for info in files) > max_uncompressed_bytes:
            raise ValueError("素材包解压大小超过限制")
        names: set[str] = set()
        for info in infos:
            name = _safe_name(info.filename, "ZIP 文件路径")
            if name in names:
                raise ValueError(f"素材包包含重复路径：{name}")
            names.add(name)
            if info.flag_bits & 0x1:
                raise ValueError("素材包不得包含加密文件")
            if _is_symlink(info):
                raise ValueError("素材包不得包含符号链接")
        if "manifest.json" not in names:
            raise ValueError("素材包根目录缺少 manifest.json")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manifest.json 不是有效 UTF-8 JSON") from exc
        manifest = dict(_object(manifest, "manifest"))
        schema_version = _string(manifest.get("schema_version"), "schema_version")
        if schema_version not in {"2.0", "2.1"}:
            raise ValueError("只支持素材 Manifest 2.0 或 2.1")
        template_id = _string(
            manifest.get("template_id", manifest.get("template_code")), "template_id"
        )
        identity_version = _string(manifest.get("identity_version"), "identity_version")
        asset_version = _string(manifest.get("asset_version"), "asset_version")
        if (
            template_id != expected_template_id
            or identity_version != expected_identity_version
            or asset_version != expected_asset_version
        ):
            raise ValueError("素材包身份或版本与模板版本不匹配")
        references = _referenced_paths(manifest)
        missing = sorted(references - names)
        if missing:
            raise ValueError(f"素材包缺少引用文件：{', '.join(missing[:5])}")

        metadata = manifest.get("files")
        if metadata is not None:
            if not isinstance(metadata, list):
                raise ValueError("files 必须是数组")
            seen_metadata: set[str] = set()
            for index, item in enumerate(metadata):
                entry = _object(item, f"files[{index}]")
                name = _safe_name(entry.get("path"), f"files[{index}].path")
                if name in seen_metadata:
                    raise ValueError(f"files 包含重复路径：{name}")
                seen_metadata.add(name)
                if name not in names:
                    raise ValueError(f"files 引用不存在的文件：{name}")
                payload = archive.read(name)
                expected_size = entry.get("size")
                if expected_size is not None and expected_size != len(payload):
                    raise ValueError(f"素材文件大小不匹配：{name}")
                expected_hash = entry.get("sha256")
                if expected_hash is not None:
                    expected_hash = _string(expected_hash, f"files[{index}].sha256").lower()
                    if len(expected_hash) != 64 or any(
                        char not in "0123456789abcdef" for char in expected_hash
                    ):
                        raise ValueError("素材文件 SHA-256 格式无效")
                    if hashlib.sha256(payload).hexdigest() != expected_hash:
                        raise ValueError(f"素材文件哈希不匹配：{name}")

        image_sizes: dict[str, tuple[int, int]] = {}
        for name in sorted(references):
            if Path(name).suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg"}:
                continue
            try:
                with Image.open(BytesIO(archive.read(name))) as image:
                    image.verify()
                with Image.open(BytesIO(archive.read(name))) as image:
                    image_sizes[name] = image.size
            except (OSError, UnidentifiedImageError) as exc:
                raise ValueError(f"素材图片无法解码：{name}") from exc

        renderer = manifest.get("renderer")
        if renderer is not None:
            renderer_data = _object(renderer, "renderer")
            if renderer_data.get("kind") == "spritesheet":
                sheet_name = _safe_name(renderer_data.get("path"), "renderer.path")
                expected_size = (
                    int(renderer_data["columns"]) * int(renderer_data["cell_width"]),
                    int(renderer_data["rows"]) * int(renderer_data["cell_height"]),
                )
                if image_sizes.get(sheet_name) != expected_size:
                    raise ValueError(
                        f"精灵表尺寸必须为 {expected_size[0]}×{expected_size[1]}"
                    )

    return ValidatedAssetPackage(
        manifest=manifest,
        package_sha256=hashlib.sha256(data).hexdigest(),
        package_size=len(data),
    )
