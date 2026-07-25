"""卡哇伊视觉主题与 QSS 萌化样式表系统模块。

本模块提供统一的马卡龙浅色渐变主题、圆角卡片、柔和阴影与可爱按钮样式，
提升桌面宠物全部 GUI 窗口的颜值、易用性与卡哇伊美学表现。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

CUTE_QSS_STYLE = """
/* 全局基础字体与背景 */
QWidget {
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    color: #4A4A6A;
}

QDialog, QFrame {
    background-color: #FFF9FC;
    border-radius: 16px;
}

/* QGroupBox 卡片美化 */
QGroupBox {
    font-size: 13px;
    font-weight: bold;
    color: #8A5A83;
    border: 2px solid #FFE4F0;
    border-radius: 14px;
    margin-top: 10px;
    padding-top: 14px;
    background-color: #FFFFFF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    background-color: #FFFFFF;
    color: #FF6584;
}

/* 可爱按钮 QPushbutton */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF9EAA, stop:1 #FF708A);
    color: #FFFFFF;
    font-size: 13px;
    font-weight: bold;
    border: none;
    border-radius: 12px;
    padding: 6px 14px;
    min-height: 28px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFAEBA, stop:1 #FF809A);
}

QPushButton:pressed {
    background-color: #E65570;
}

/* 动感 QProgressBar */
QProgressBar {
    border: 1px solid #FFD0E0;
    border-radius: 10px;
    background-color: #FFF0F5;
    text-align: center;
    color: #6B4E71;
    font-size: 11px;
    font-weight: bold;
    height: 18px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #A8EDEA, stop:1 #FED6E3);
    border-radius: 9px;
}

/* 输入框 QLineEdit */
QLineEdit {
    border: 2px solid #FFE0EC;
    border-radius: 12px;
    padding: 4px 10px;
    background-color: #FFFFFF;
    selection-background-color: #FFB6C1;
}

QLineEdit:focus {
    border: 2px solid #FF85A1;
}

/* 列表框 QListWidget & QTableWidget */
QListWidget, QTableWidget {
    border: 1.5px solid #FFECF3;
    border-radius: 12px;
    background-color: #FFFFFF;
}

QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #FFE4EC;
    color: #FF4081;
    border-radius: 8px;
}
"""


def apply_cute_style(widget: QWidget) -> None:
    """为指定 Qt 窗口或控件应用全套萌化 QSS 样式。"""
    widget.setStyleSheet(CUTE_QSS_STYLE)
