"""边缘吸附几何逻辑测试，不创建 Qt 窗口。"""

from onepic_desktop_pet.edge_geometry import (
    EdgeSide,
    calculate_placement,
    choose_edge,
    y_from_offset_ratio,
)


def test_choose_nearest_supported_edge() -> None:
    assert choose_edge(5, 204, 0, 1919, 36) is EdgeSide.LEFT
    assert choose_edge(1700, 1899, 0, 1919, 36) is EdgeSide.RIGHT
    assert choose_edge(600, 799, 0, 1919, 36) is None


def test_left_edge_hides_window_but_keeps_visible_strip() -> None:
    placement = calculate_placement(
        EdgeSide.LEFT,
        area_left=0,
        area_top=0,
        area_right=1919,
        area_bottom=1079,
        window_width=200,
        window_height=220,
        current_y=500,
        visible_ratio=0.25,
    )

    assert placement.expanded_x == 0
    assert placement.visible_width == 50
    assert placement.hidden_x == -150
    assert placement.y == 500
    assert 0.0 < placement.offset_ratio < 1.0


def test_right_edge_uses_inclusive_screen_coordinates() -> None:
    placement = calculate_placement(
        EdgeSide.RIGHT,
        area_left=0,
        area_top=0,
        area_right=1919,
        area_bottom=1079,
        window_width=200,
        window_height=220,
        current_y=900,
        visible_ratio=0.30,
    )

    assert placement.expanded_x == 1720
    assert placement.hidden_x == 1860
    assert placement.y == 860


def test_offset_ratio_restores_position_on_changed_resolution() -> None:
    assert y_from_offset_ratio(0, 1079, 220, 0.5) == 430
    assert y_from_offset_ratio(100, 999, 200, 0.0) == 100
    assert y_from_offset_ratio(100, 999, 200, 1.0) == 800
