"""
本模块验证用户私有动作图集的拆行和四足角色统一缩放逻辑。

测试只构造内存中的透明图像，不读取或写入用户私有素材。
"""

from PIL import Image, ImageDraw

from tools.prepare_user_pet import (
    find_transparent_row_split,
    shared_fitting_height,
)


def test_row_split_stops_before_thin_lower_row_pixels() -> None:
    """中央透明带应在下排行为的首个可见像素前结束。"""

    sheet = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((20, 30, 120, 100), fill=(255, 255, 255, 255))
    draw.point((30, 170), fill=(255, 255, 255, 255))
    draw.rectangle((20, 176, 120, 260), fill=(255, 255, 255, 255))

    assert find_transparent_row_split(sheet) == 170


def test_shared_fitting_height_uses_widest_quadruped_ratio() -> None:
    """横向四足帧应共用能容纳最宽步幅的安全可见高度。"""

    wide = Image.new("RGBA", (400, 200), (255, 255, 255, 255))
    narrow = Image.new("RGBA", (300, 200), (255, 255, 255, 255))

    assert shared_fitting_height([wide, narrow], 450) == 264
