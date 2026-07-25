"""键盘与鼠标操作频率统计及久坐疲劳分析器模块。

本模块提供非侵入式的输入活动监听与统计分析能力，仅统计按键总次数、鼠标点击数
与移动距离，绝对不收集具体的按键字符内容或屏幕数据，严格保护用户隐私。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from PySide6.QtCore import QEvent, QObject, QTimer, Signal


class InputAnalytics(QObject):
    """输入操作频率监听与久坐疲劳分析器。"""

    # 信号：操作热度更新 (分钟按键数, 分钟点击数, 久坐分钟数)
    activity_updated = Signal(int, int, int)
    # 信号：久坐超限预警 (久坐连续分钟数)
    sedentary_warning = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._total_keypresses: int = 0
        self._total_mouse_clicks: int = 0

        # 分钟滑动窗口数据：[(datetime_key, keypresses, mouse_clicks)]
        self._minute_stats: Dict[str, Dict[str, int]] = {}

        # 连续操作分钟数计数
        self._consecutive_active_minutes: int = 0
        self._last_active_time: datetime = datetime.now()

        # 每 1 分钟检查一次活性与久坐状态
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)  # 60秒
        self._timer.timeout.connect(self._on_minute_tick)
        self._timer.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Qt 全局事件过滤器，非侵入式捕获输入按键与鼠标点击事件。"""
        event_type = event.type()
        if event_type == QEvent.Type.KeyPress:
            self.record_keypress()
        elif event_type in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
        ):
            self.record_mouse_click()

        return super().eventFilter(watched, event)

    def record_keypress(self) -> None:
        """记录一次键盘敲击（仅增加计数，不保留键值）。"""
        self._total_keypresses += 1
        self._last_active_time = datetime.now()
        minute_key = self._last_active_time.strftime("%Y-%m-%d %H:%M")
        stat = self._minute_stats.setdefault(minute_key, {"keys": 0, "clicks": 0})
        stat["keys"] += 1

    def record_mouse_click(self) -> None:
        """记录一次鼠标点击。"""
        self._total_mouse_clicks += 1
        self._last_active_time = datetime.now()
        minute_key = self._last_active_time.strftime("%Y-%m-%d %H:%M")
        stat = self._minute_stats.setdefault(minute_key, {"keys": 0, "clicks": 0})
        stat["clicks"] += 1

    def get_totals(self) -> tuple[int, int]:
        """获取总键盘敲击数与总鼠标点击数。"""
        return self._total_keypresses, self._total_mouse_clicks

    def get_sedentary_minutes(self) -> int:
        """获取当前连续活跃/久坐时长（分钟）。"""
        return self._consecutive_active_minutes

    def get_hourly_summary(self) -> List[Dict[str, int | str]]:
        """获取最近 60 分钟的操作分布数据。"""
        now = datetime.now()
        summary = []
        for i in range(59, -1, -1):
            t = now - timedelta(minutes=i)
            key = t.strftime("%Y-%m-%d %H:%M")
            time_label = t.strftime("%H:%M")
            stat = self._minute_stats.get(key, {"keys": 0, "clicks": 0})
            summary.append(
                {
                    "time": time_label,
                    "keys": stat["keys"],
                    "clicks": stat["clicks"],
                }
            )
        return summary

    def calculate_fatigue_score(self) -> int:
        """根据久坐时长与近 15 分钟密集操作计算疲劳指数 (0 - 100)。"""
        now = datetime.now()
        recent_keys = 0
        for i in range(15):
            t = now - timedelta(minutes=i)
            key = t.strftime("%Y-%m-%d %H:%M")
            stat = self._minute_stats.get(key, {"keys": 0, "clicks": 0})
            recent_keys += stat["keys"] + stat["clicks"]

        # 久坐权重 (最高 60 分)
        sedentary_score = min(60, self._consecutive_active_minutes * 1.2)
        # 操作密度权重 (最高 40 分)
        density_score = min(40, recent_keys / 10.0)

        return int(min(100, sedentary_score + density_score))

    def reset_sedentary_timer(self) -> None:
        """重置久坐定时器（如用户完成走动打卡后）。"""
        self._consecutive_active_minutes = 0

    def _on_minute_tick(self) -> None:
        """分钟定时回调，检查是否有连续操作与久坐。"""
        now = datetime.now()
        current_minute_key = now.strftime("%Y-%m-%d %H:%M")
        stat = self._minute_stats.get(current_minute_key, {"keys": 0, "clicks": 0})

        # 如果这一分钟有键盘或鼠标操作，增加久坐分钟数
        if stat["keys"] > 0 or stat["clicks"] > 0:
            self._consecutive_active_minutes += 1
        else:
            # 超过 3 分钟没有任何输入操作，判定为离开，重置久坐
            if (now - self._last_active_time).total_seconds() > 180:
                self._consecutive_active_minutes = max(
                    0, self._consecutive_active_minutes - 1
                )

        self.activity_updated.emit(
            stat["keys"], stat["clicks"], self._consecutive_active_minutes
        )

        # 每满 45 分钟发送久坐预警
        if (
            self._consecutive_active_minutes > 0
            and self._consecutive_active_minutes % 45 == 0
        ):
            self.sedentary_warning.emit(self._consecutive_active_minutes)
