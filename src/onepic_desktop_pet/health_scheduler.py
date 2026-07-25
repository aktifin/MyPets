"""健康提醒调度与智能打卡管理器模块。

本模块提供喝水提醒、久坐走动提醒以及护眼工作休息提醒的定时与智能触发能力，
支持与桌面桌宠的气泡与动作联动，关怀用户健康。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict

from PySide6.QtCore import QObject, QTimer, Signal

from .input_analytics import InputAnalytics


class HealthScheduler(QObject):
    """健康提醒调度器。"""

    # 信号：(提醒类型 'water'/'stand'/'rest', 标题, 消息内容)
    health_reminder_triggered = Signal(str, str, str)

    def __init__(
        self,
        analytics: InputAnalytics | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.analytics = analytics

        # 提醒配置（分钟间隔）
        self.water_interval_mins: int = 45
        self.stand_interval_mins: int = 45
        self.rest_interval_mins: int = 50

        # 今日已打卡次数
        self._water_checkins: int = 0
        self._stand_checkins: int = 0
        self._rest_checkins: int = 0

        # 定时器：喝水提醒
        self._water_timer = QTimer(self)
        self._water_timer.setInterval(self.water_interval_mins * 60_000)
        self._water_timer.timeout.connect(self._trigger_water_reminder)

        # 定时器：护眼休息提醒
        self._rest_timer = QTimer(self)
        self._rest_timer.setInterval(self.rest_interval_mins * 60_000)
        self._rest_timer.timeout.connect(self._trigger_rest_reminder)

        # 如果传入了 analytics，监听久坐预警
        if self.analytics is not None:
            self.analytics.sedentary_warning.connect(self._on_sedentary_warning)

    def start(self) -> None:
        """启动健康提醒调度器。"""
        self._water_timer.start()
        self._rest_timer.start()

    def stop(self) -> None:
        """停止提醒调度。"""
        self._water_timer.stop()
        self._rest_timer.stop()

    def checkin(self, reminder_type: str) -> None:
        """完成某项健康打卡。"""
        if reminder_type == "water":
            self._water_checkins += 1
        elif reminder_type == "stand":
            self._stand_checkins += 1
            if self.analytics is not None:
                self.analytics.reset_sedentary_timer()
        elif reminder_type == "rest":
            self._rest_checkins += 1

    def get_checkin_counts(self) -> Dict[str, int]:
        """获取今日健康打卡汇总。"""
        return {
            "water": self._water_checkins,
            "stand": self._stand_checkins,
            "rest": self._rest_checkins,
        }

    def _trigger_water_reminder(self) -> None:
        """触发喝水提醒。"""
        self.health_reminder_triggered.emit(
            "water",
            "🍵 补充水分提醒",
            "主人，你已经工作好一会儿啦！快喝一口水补充水分吧~",
        )

    def _trigger_rest_reminder(self) -> None:
        """触发护眼休息提醒。"""
        self.health_reminder_triggered.emit(
            "rest",
            "👀 护眼休息提醒",
            "连续专注工作 50 分钟了，转动一下眼球，休息 5 分钟吧！",
        )

    def _on_sedentary_warning(self, sedentary_mins: int) -> None:
        """久坐智能预警机制。"""
        self.health_reminder_triggered.emit(
            "stand",
            "🏃 久坐走动提醒",
            f"主人，你已经连续高强度操作 {sedentary_mins} 分钟了！站起来走动扭扭腰吧~",
        )
