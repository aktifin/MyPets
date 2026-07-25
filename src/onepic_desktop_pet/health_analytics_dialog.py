"""健康提醒与输入操作统计分析面板对话框。

本模块提供可视化的健康与键盘/鼠标操作频率分析界面，展示敲击数、久坐疲劳指数
以及健康打卡控制，提升桌面宠物的健康关怀属性。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .cute_style import apply_cute_style
from .health_scheduler import HealthScheduler
from .input_analytics import InputAnalytics


class HealthAnalyticsDialog(QDialog):
    """健康与操作统计分析面板对话框。"""

    checkin_requested = Signal(str)

    def __init__(
        self,
        analytics: InputAnalytics,
        scheduler: HealthScheduler,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.analytics = analytics
        self.scheduler = scheduler
        apply_cute_style(self)

        self.setWindowTitle("MyPets 桌面宠物 - 健康与操作分析")
        self.resize(600, 480)
        self.setModal(False)

        root = QVBoxLayout(self)

        # 头部统计卡片
        stats_group = QGroupBox("📊 键盘/鼠标操作与疲劳指数")
        stats_layout = QHBoxLayout(stats_group)

        self.keys_label = QLabel("键盘敲击: 0")
        self.clicks_label = QLabel("鼠标点击: 0")
        self.sedentary_label = QLabel("久坐时长: 0 分钟")

        stats_layout.addWidget(self.keys_label)
        stats_layout.addWidget(self.clicks_label)
        stats_layout.addWidget(self.sedentary_label)
        root.addWidget(stats_group)

        # 疲劳指数进度条
        fatigue_group = QGroupBox("🧠 当前久坐疲劳指数")
        fatigue_layout = QVBoxLayout(fatigue_group)
        self.fatigue_bar = QProgressBar()
        self.fatigue_bar.setRange(0, 100)
        self.fatigue_bar.setValue(0)
        self.fatigue_status = QLabel("状态: 轻松")
        fatigue_layout.addWidget(self.fatigue_bar)
        fatigue_layout.addWidget(self.fatigue_status)
        root.addWidget(fatigue_group)

        # 分钟分布表格
        table_group = QGroupBox("⏱️ 最近 60 分钟操作分布趋势")
        table_layout = QVBoxLayout(table_group)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["时间", "按键数", "点击数"])
        self.table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.table)
        root.addWidget(table_group)

        # 打卡控制
        checkin_group = QGroupBox("🍵 健康关怀打卡")
        checkin_layout = QHBoxLayout(checkin_group)

        self.water_btn = QPushButton("🍵 喝水打卡")
        self.water_btn.clicked.connect(lambda: self._do_checkin("water"))

        self.stand_btn = QPushButton("🏃 走动打卡")
        self.stand_btn.clicked.connect(lambda: self._do_checkin("stand"))

        self.rest_btn = QPushButton("👀 休息打卡")
        self.rest_btn.clicked.connect(lambda: self._do_checkin("rest"))

        checkin_layout.addWidget(self.water_btn)
        checkin_layout.addWidget(self.stand_btn)
        checkin_layout.addWidget(self.rest_btn)
        root.addWidget(checkin_group)

        self.refresh_data()

    def refresh_data(self) -> None:
        """刷新面板展示数据。"""
        total_keys, total_clicks = self.analytics.get_totals()
        sedentary = self.analytics.get_sedentary_minutes()
        fatigue = self.analytics.calculate_fatigue_score()

        self.keys_label.setText(f"键盘敲击: {total_keys}")
        self.clicks_label.setText(f"鼠标点击: {total_clicks}")
        self.sedentary_label.setText(f"久坐时长: {sedentary} 分钟")

        self.fatigue_bar.setValue(fatigue)
        if fatigue < 30:
            self.fatigue_status.setText("状态: 状态良好 🟢")
        elif fatigue < 70:
            self.fatigue_status.setText("状态: 轻度疲劳，建议休息 🟡")
        else:
            self.fatigue_status.setText("状态: 重度疲劳，请立即站立休息 🔴")

        # 填充表格
        summary = self.analytics.get_hourly_summary()
        # 仅显示有操作的记录
        active_summary = [s for s in summary if s["keys"] > 0 or s["clicks"] > 0]

        self.table.setRowCount(len(active_summary))
        for row, item in enumerate(active_summary):
            self.table.setItem(row, 0, QTableWidgetItem(str(item["time"])))
            self.table.setItem(row, 1, QTableWidgetItem(str(item["keys"])))
            self.table.setItem(row, 2, QTableWidgetItem(str(item["clicks"])))

        checkins = self.scheduler.get_checkin_counts()
        self.water_btn.setText(f"🍵 喝水打卡 ({checkins['water']})")
        self.stand_btn.setText(f"🏃 走动打卡 ({checkins['stand']})")
        self.rest_btn.setText(f"👀 休息打卡 ({checkins['rest']})")

    def _do_checkin(self, reminder_type: str) -> None:
        """执行打卡。"""
        self.scheduler.checkin(reminder_type)
        self.checkin_requested.emit(reminder_type)
        self.refresh_data()
