"""
本模块是 Windows 桌面宠物应用的命令行启动入口。

职责范围：
- 解析可选的 `--smoke-test-ms` 自动退出参数；
- 调用 visit_app.run() 启动包含串门、好友、共同照料、提醒和消息功能的 Qt 应用；
- 不包含窗口、行为或配置业务逻辑。

使用示例：
    py main.py
    py main.py --smoke-test-ms 1500
"""

from __future__ import annotations

import argparse

from onepic_desktop_pet.visit_app import run


def parse_args() -> argparse.Namespace:
    """解析启动参数。"""

    parser = argparse.ArgumentParser(description="启动 Windows 桌面宠物")
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
