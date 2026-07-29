"""
本模块是 Windows 桌面宠物应用的命令行启动入口。

职责范围：
- 解析可选的 `--smoke-test-ms` 自动退出参数；
- 输出统一发布版本；
- 启动包含首次运行引导、点击宠物快捷养宠面板、成长目标与纪念册、统一待处理事项、
  多宠状态总览、照料后下一宠提示、双宠并排布局、主动关怀、串门时间线、消息搜索、
  未读定位、可配置快捷回复、待办直达详情、客户处理记录、好友、共同照料、提醒、
  单窗口多宠物聚会场景以及帮助与诊断入口的 Qt 应用；
- 聚会场景只使用一个管理对话框，不创建额外宠物运行时，桌面常驻宠物仍最多两只；
- 诊断包不包含密码、访问令牌、设备密钥、消息正文、本地数据库或宠物原图；
- 不包含窗口、行为或配置业务逻辑。

使用示例：
    py main.py
    py main.py --version
    py main.py --smoke-test-ms 1500
"""

from __future__ import annotations

import argparse

from onepic_desktop_pet.diagnostics_app import run
from onepic_desktop_pet.release import APP_NAME, APP_VERSION


def parse_args() -> argparse.Namespace:
    """解析启动参数。"""

    parser = argparse.ArgumentParser(description="启动 Windows 桌面宠物")
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION}",
    )
    parser.add_argument(
        "--smoke-test-ms",
        type=int,
        default=None,
        help="在指定毫秒后自动退出，仅用于启动验证",
    )
    return parser.parse_args()


def main() -> int:
    """启动应用并返回 Qt 事件循环退出码。"""

    args = parse_args()
    return run(smoke_test_ms=args.smoke_test_ms)


if __name__ == "__main__":
    raise SystemExit(main())
