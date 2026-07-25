"""新建宠物与形象模板选择对话框模块。

本模块提供桌宠创建与形象模板选择 GUI，支持用户自定义宠物昵称、选择角色外观
并初始化宠物数据。
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


from .cute_style import apply_cute_style


class PetCreateDialog(QDialog):
    """创建新宠物对话框。"""

    # 信号：(宠物名字, 模板ID)
    pet_created = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_cute_style(self)
        self.setWindowTitle("创建新的 MyPets 桌面宠物")
        self.resize(380, 220)
        self.setModal(True)

        root = QVBoxLayout(self)

        # 名字输入
        name_layout = QHBoxLayout()
        name_label = QLabel("宠物昵称:")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("给你的小桌宠起个好听的名字吧")
        self.name_edit.setText("小宝贝")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        root.addLayout(name_layout)

        # 模板选择
        template_layout = QHBoxLayout()
        template_label = QLabel("形象模板:")
        self.template_combo = QComboBox()
        self.template_combo.addItem("官方默认角色 (Default Pet)", "demo_pet")
        self.template_combo.addItem("榫榫 (Sun-Sun 精灵表)", "sun-sun")
        template_layout.addWidget(template_label)
        template_layout.addWidget(self.template_combo)
        root.addLayout(template_layout)

        # 提示标签
        self.status_label = QLabel("新的桌宠将继承成长评估与全套互动体验。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        # 按钮
        btn_layout = QHBoxLayout()
        self.create_btn = QPushButton("立即创建并切换")
        self.create_btn.clicked.connect(self._on_create)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.create_btn)
        btn_layout.addWidget(self.cancel_btn)
        root.addLayout(btn_layout)

    def _on_create(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.status_label.setText("请输入有效的宠物昵称！")
            return
        template_id = self.template_combo.currentData()
        self.pet_created.emit(name, template_id)
        self.accept()
