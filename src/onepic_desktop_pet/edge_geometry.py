"""屏幕边缘吸附的纯几何计算，便于在无 GUI 环境中测试。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EdgeSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class EdgePlacement:
    """宠物吸附后的展开位置、半隐藏位置和纵向比例。"""

    side: EdgeSide
    expanded_x: int
    hidden_x: int
    y: int
    offset_ratio: float
    visible_width: int


def clamp_ratio(value: float, minimum: float = 0.10, maximum: float = 0.80) -> float:
    return min(maximum, max(minimum, float(value)))


def choose_edge(
    window_left: int,
    window_right: int,
    area_left: int,
    area_right: int,
    threshold: int,
) -> EdgeSide | None:
    """当窗口距离左右边缘足够近时返回最近的一侧。"""

    threshold = max(0, int(threshold))
    left_distance = abs(window_left - area_left)
    right_distance = abs(area_right - window_right)
    nearest = min(left_distance, right_distance)
    if nearest > threshold:
        return None
    return EdgeSide.LEFT if left_distance <= right_distance else EdgeSide.RIGHT


def y_from_offset_ratio(
    area_top: int,
    area_bottom: int,
    window_height: int,
    offset_ratio: float,
) -> int:
    """根据屏幕可用高度比例恢复纵向位置。"""

    maximum_y = max(area_top, area_bottom - max(1, window_height) + 1)
    span = max(0, maximum_y - area_top)
    ratio = min(1.0, max(0.0, float(offset_ratio)))
    return area_top + round(span * ratio)


def calculate_placement(
    side: EdgeSide,
    *,
    area_left: int,
    area_top: int,
    area_right: int,
    area_bottom: int,
    window_width: int,
    window_height: int,
    current_y: int,
    visible_ratio: float,
    minimum_visible_width: int = 24,
) -> EdgePlacement:
    """计算左右边缘展开与半隐藏坐标。"""

    width = max(1, int(window_width))
    height = max(1, int(window_height))
    maximum_y = max(area_top, area_bottom - height + 1)
    y = min(max(int(current_y), area_top), maximum_y)
    vertical_span = max(1, maximum_y - area_top)
    offset_ratio = min(1.0, max(0.0, (y - area_top) / vertical_span))

    ratio = clamp_ratio(visible_ratio)
    visible_width = min(width, max(int(minimum_visible_width), round(width * ratio)))
    if side is EdgeSide.LEFT:
        expanded_x = area_left
        hidden_x = area_left - width + visible_width
    else:
        expanded_x = area_right - width + 1
        hidden_x = area_right - visible_width + 1

    return EdgePlacement(
        side=side,
        expanded_x=expanded_x,
        hidden_x=hidden_x,
        y=y,
        offset_ratio=offset_ratio,
        visible_width=visible_width,
    )
