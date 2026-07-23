"""
宠物视觉身份与跨端素材 Manifest 校验。

兼容当前 1.0 动画清单，同时为成长阶段、能力声明、边缘探头、素材版本和动作
降级建立统一入口。管理员后台和桌面客户端应复用本模块，避免各自解释 JSON。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


LEGACY_REQUIRED_ACTIONS = frozenset(
    {
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
)


@dataclass(frozen=True)
class EdgePeekProfile:
    """边缘半隐藏时的形象可见比例和视觉锚点。"""

    left_visible_ratio: float = 0.28
    right_visible_ratio: float = 0.28
    anchor: str = "face"

    def __post_init__(self) -> None:
        for value in (self.left_visible_ratio, self.right_visible_ratio):
            if not 0.10 <= value <= 0.80:
                raise ValueError("边缘可见比例必须在 0.10 到 0.80 之间")
        if not self.anchor.strip():
            raise ValueError("edge_peek.anchor 不能为空")


@dataclass(frozen=True)
class VisualBounds:
    """标准化视觉边界，用于点击、吸附和多宠物场景排布。"""

    left: float = 0.0
    top: float = 0.0
    right: float = 1.0
    bottom: float = 1.0

    def __post_init__(self) -> None:
        values = (self.left, self.top, self.right, self.bottom)
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError("visual_bounds 必须使用 0 到 1 的归一化坐标")
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("visual_bounds 的右下坐标必须大于左上坐标")


@dataclass(frozen=True)
class PetManifest:
    """桌面端可消费的宠物素材清单。"""

    schema_version: str
    template_code: str | None
    identity_version: str
    asset_version: str
    animations: Mapping[str, tuple[str, ...]]
    walk_motion_factors: tuple[float, ...]
    fallback_actions: Mapping[str, str] = field(default_factory=dict)
    capabilities: Mapping[str, bool] = field(default_factory=dict)
    edge_peek: EdgePeekProfile = field(default_factory=EdgePeekProfile)
    visual_bounds: VisualBounds = field(default_factory=VisualBounds)
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def animation_paths(self, action: str) -> tuple[str, ...]:
        """返回动作素材；缺失时按声明的降级链解析。"""

        current = action
        visited: set[str] = set()
        while current not in self.animations:
            if current in visited:
                raise ValueError(f"动作降级配置存在循环：{action}")
            visited.add(current)
            fallback = self.fallback_actions.get(current)
            if fallback is None:
                raise KeyError(f"Manifest 缺少动作：{action}")
            current = fallback
        return self.animations[current]


def _as_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是 JSON 对象")
    return value


def _parse_animations(value: Any) -> dict[str, tuple[str, ...]]:
    source = _as_mapping(value, "animations")
    animations: dict[str, tuple[str, ...]] = {}
    for action, paths in source.items():
        if not isinstance(action, str) or not action.strip():
            raise ValueError("animations 的动作名称必须是非空字符串")
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"动作 {action} 必须包含至少一个素材路径")
        normalized: list[str] = []
        for path in paths:
            if not isinstance(path, str) or not path.strip():
                raise ValueError(f"动作 {action} 包含无效素材路径")
            normalized.append(path.replace("\\", "/"))
        animations[action] = tuple(normalized)
    return animations


def _parse_edge_peek(data: Mapping[str, Any]) -> EdgePeekProfile:
    appearance = data.get("appearance", {})
    if appearance and not isinstance(appearance, dict):
        raise ValueError("appearance 必须是 JSON 对象")
    raw = data.get("edge_peek") or appearance.get("edge_peek") or {}
    raw = _as_mapping(raw, "edge_peek")
    return EdgePeekProfile(
        left_visible_ratio=float(raw.get("left_visible_ratio", 0.28)),
        right_visible_ratio=float(raw.get("right_visible_ratio", 0.28)),
        anchor=str(raw.get("anchor", "face")),
    )


def _parse_visual_bounds(data: Mapping[str, Any]) -> VisualBounds:
    appearance = data.get("appearance", {})
    if appearance and not isinstance(appearance, dict):
        raise ValueError("appearance 必须是 JSON 对象")
    raw = data.get("visual_bounds") or appearance.get("visual_bounds") or {}
    raw = _as_mapping(raw, "visual_bounds")
    return VisualBounds(
        left=float(raw.get("left", 0.0)),
        top=float(raw.get("top", 0.0)),
        right=float(raw.get("right", 1.0)),
        bottom=float(raw.get("bottom", 1.0)),
    )


def parse_pet_manifest(data: Mapping[str, Any]) -> PetManifest:
    """解析并校验 Manifest；旧格式会自动补齐版本和形象字段。"""

    animations = _parse_animations(data.get("animations"))
    fallback_actions = {
        str(action): str(fallback)
        for action, fallback in _as_mapping(
            data.get("fallback_actions", {}),
            "fallback_actions",
        ).items()
    }
    missing = sorted(
        action
        for action in LEGACY_REQUIRED_ACTIONS
        if action not in animations and action not in fallback_actions
    )
    if missing:
        raise ValueError("Manifest 缺少基础动作或降级配置：" + ", ".join(missing))

    walk_paths = PetManifest(
        schema_version="temporary",
        template_code=None,
        identity_version="temporary",
        asset_version="temporary",
        animations=animations,
        walk_motion_factors=(),
        fallback_actions=fallback_actions,
    ).animation_paths("walk")
    factors_value = data.get("walk_motion_factors")
    if factors_value is None:
        factors = tuple(1.0 for _ in walk_paths)
    else:
        if not isinstance(factors_value, list):
            raise ValueError("walk_motion_factors 必须是数组")
        factors = tuple(float(value) for value in factors_value)
    if len(factors) != len(walk_paths):
        raise ValueError("走路位移曲线必须与走路动画帧数一致")
    if any(value <= 0 for value in factors):
        raise ValueError("walk_motion_factors 必须全部大于 0")

    capabilities_source = _as_mapping(data.get("capabilities", {}), "capabilities")
    capabilities = {str(key): bool(value) for key, value in capabilities_source.items()}
    template_code = data.get("template_code")
    if template_code is not None and not str(template_code).strip():
        raise ValueError("template_code 不能是空字符串")

    return PetManifest(
        schema_version=str(data.get("schema_version", "1.0")),
        template_code=str(template_code) if template_code is not None else None,
        identity_version=str(data.get("identity_version", "1.0.0")),
        asset_version=str(data.get("asset_version", "1.0.0")),
        animations=animations,
        walk_motion_factors=factors,
        fallback_actions=fallback_actions,
        capabilities=capabilities,
        edge_peek=_parse_edge_peek(data),
        visual_bounds=_parse_visual_bounds(data),
        raw=dict(data),
    )


def load_pet_manifest(path: Path) -> PetManifest:
    """读取指定 JSON 文件并返回统一 Manifest。"""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取宠物 Manifest {path}：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"宠物 Manifest 必须包含 JSON 对象：{path}")
    return parse_pet_manifest(data)


def validate_manifest_assets(path: Path, manifest: PetManifest) -> list[str]:
    """返回缺失或越界的素材问题列表，不负责加载图像。"""

    problems: list[str] = []
    root = path.parent
    for action, relative_paths in manifest.animations.items():
        for relative in relative_paths:
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                problems.append(f"动作 {action} 的素材路径越出 Manifest 目录：{relative}")
                continue
            if not candidate.is_file():
                problems.append(f"动作 {action} 缺少素材：{relative}")
    return problems
