"""边缘吸附几何逻辑测试，不创建 Qt 窗口。"""

from onepic_desktop_pet.edge_geometry import (
    EdgeSide,
    calculate_placement,
    choose_edge,
    x_from_offset_ratio,
    y_from_offset_ratio,
)


def test_choose_nearest_supported_edge() -> None:
    assert choose_edge(5, 500, 204, 720, 0, 0, 1919, 1079, 36) is EdgeSide.LEFT
    assert choose_edge(1700, 500, 1899, 720, 0, 0, 1919, 1079, 36) is EdgeSide.RIGHT
    assert choose_edge(500, 5, 700, 204, 0, 0, 1919, 1079, 36) is EdgeSide.TOP
    assert choose_edge(500, 900, 700, 1075, 0, 0, 1919, 1079, 36) is EdgeSide.BOTTOM
    assert choose_edge(600, 500, 799, 720, 0, 0, 1919, 1079, 36) is None


def test_left_edge_hides_window_but_keeps_visible_strip() -> None:
    placement = calculate_placement(
        EdgeSide.LEFT,
        area_left=0,
        area_top=0,
        area_right=1919,
        area_bottom=1079,
        window_width=200,
        window_height=220,
        current_x=5,
        current_y=500,
        visible_ratio=0.25,
    )

    assert placement.expanded_x == 0
    assert placement.visible_width == 50
    assert placement.hidden_x == -150
    assert placement.expanded_y == 500
    assert placement.hidden_y == 500
    assert 0.0 < placement.offset_ratio < 1.0


def test_top_and_bottom_edge_placements() -> None:
    top_placement = calculate_placement(
        EdgeSide.TOP,
        area_left=0,
        area_top=0,
        area_right=1919,
        area_bottom=1079,
        window_width=200,
        window_height=200,
        current_x=500,
        current_y=10,
        visible_ratio=0.20,
    )
    assert top_placement.expanded_y == 0
    assert top_placement.visible_height == 40
    assert top_placement.hidden_y == -160

    bottom_placement = calculate_placement(
        EdgeSide.BOTTOM,
        area_left=0,
        area_top=0,
        area_right=1919,
        area_bottom=1079,
        window_width=200,
        window_height=200,
        current_x=500,
        current_y=1000,
        visible_ratio=0.20,
    )
    assert bottom_placement.expanded_y == 880
    assert bottom_placement.hidden_y == 1040


def test_offset_ratio_restores_position_on_changed_resolution() -> None:
    assert y_from_offset_ratio(0, 1079, 220, 0.5) == 430
    assert x_from_offset_ratio(0, 1919, 200, 0.5) == 860
    assert y_from_offset_ratio(100, 999, 200, 0.0) == 100
    assert y_from_offset_ratio(100, 999, 200, 1.0) == 800

