"""屏幕边缘吸附的纯几何计算，支持上下左右四向吸附与低打扰隐藏。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EdgeSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


@dataclass(frozen=True)
class EdgePlacement:
    """宠物吸附后的展开位置、半隐藏位置和相对坐标比例。"""

    side: EdgeSide
    expanded_x: int
    expanded_y: int
    hidden_x: int
    hidden_y: int
    offset_ratio: float
    visible_width: int
    visible_height: int

    @property
    def y(self) -> int:
        return self.expanded_y



def clamp_ratio(value: float, minimum: float = 0.10, maximum: float = 0.80) -> float:
    return min(maximum, max(minimum, float(value)))


def choose_edge(
    window_left: int,
    window_top: int,
    window_right: int,
    window_bottom: int,
    area_left: int,
    area_top: int,
    area_right: int,
    area_bottom: int,
    threshold: int,
) -> EdgeSide | None:
    """当窗口距离屏幕上下左右边缘足够近时返回最近的一侧。"""

    threshold = max(0, int(threshold))
    left_dist = abs(window_left - area_left)
    right_dist = abs(area_right - window_right)
    top_dist = abs(window_top - area_top)
    bottom_dist = abs(area_bottom - window_bottom)

    distances = {
        EdgeSide.LEFT: left_dist,
        EdgeSide.RIGHT: right_dist,
        EdgeSide.TOP: top_dist,
        EdgeSide.BOTTOM: bottom_dist,
    }
    nearest_side, nearest_dist = min(distances.items(), key=lambda item: item[1])
    if nearest_dist > threshold:
        return None
    return nearest_side


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


def x_from_offset_ratio(
    area_left: int,
    area_right: int,
    window_width: int,
    offset_ratio: float,
) -> int:
    """根据屏幕可用宽度比例恢复横向位置。"""

    maximum_x = max(area_left, area_right - max(1, window_width) + 1)
    span = max(0, maximum_x - area_left)
    ratio = min(1.0, max(0.0, float(offset_ratio)))
    return area_left + round(span * ratio)


def calculate_placement(
    side: EdgeSide,
    *,
    area_left: int,
    area_top: int,
    area_right: int,
    area_bottom: int,
    window_width: int,
    window_height: int,
    current_x: int,
    current_y: int,
    visible_ratio: float,
    minimum_visible_size: int = 24,
) -> EdgePlacement:
    """计算上下左右四向边缘展开与半隐藏坐标。"""

    width = max(1, int(window_width))
    height = max(1, int(window_height))
    ratio = clamp_ratio(visible_ratio)

    if side in (EdgeSide.LEFT, EdgeSide.RIGHT):
        maximum_y = max(area_top, area_bottom - height + 1)
        y = min(max(int(current_y), area_top), maximum_y)
        vertical_span = max(1, maximum_y - area_top)
        offset_ratio = min(1.0, max(0.0, (y - area_top) / vertical_span))

        visible_width = min(width, max(int(minimum_visible_size), round(width * ratio)))
        visible_height = height
        expanded_y = y
        hidden_y = y

        if side is EdgeSide.LEFT:
            expanded_x = area_left
            hidden_x = area_left - width + visible_width
        else:
            expanded_x = area_right - width + 1
            hidden_x = area_right - visible_width + 1
    else:
        maximum_x = max(area_left, area_right - width + 1)
        x = min(max(int(current_x), area_left), maximum_x)
        horizontal_span = max(1, maximum_x - area_left)
        offset_ratio = min(1.0, max(0.0, (x - area_left) / horizontal_span))

        visible_height = min(height, max(int(minimum_visible_size), round(height * ratio)))
        visible_width = width
        expanded_x = x
        hidden_x = x

        if side is EdgeSide.TOP:
            expanded_y = area_top
            hidden_y = area_top - height + visible_height
        else:
            expanded_y = area_bottom - height + 1
            hidden_y = area_bottom - visible_height + 1

    return EdgePlacement(
        side=side,
        expanded_x=expanded_x,
        expanded_y=expanded_y,
        hidden_x=hidden_x,
        hidden_y=hidden_y,
        offset_ratio=offset_ratio,
        visible_width=visible_width,
        visible_height=visible_height,
    )

