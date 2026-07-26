"""First-run guidance for the Windows desktop pet experience."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class FirstRunDialog(QDialog):
    """A short three-step guide focused on the actions people use every day."""

    login_requested = Signal()
    completed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("firstRunDialog")
        self.setWindowTitle("欢迎使用 MyPets")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setMinimumSize(520, 390)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        self.step_label = QLabel("第 1 步，共 3 步")
        self.step_label.setObjectName("firstRunStep")
        self.step_label.setStyleSheet("color: #667085; font-weight: 600;")
        root.addWidget(self.step_label)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._welcome_page())
        self.pages.addWidget(self._mode_page())
        self.pages.addWidget(self._controls_page())
        self.pages.currentChanged.connect(self._page_changed)
        root.addWidget(self.pages, 1)

        footer = QHBoxLayout()
        self.back_button = QPushButton("上一步")
        self.back_button.setObjectName("firstRunBack")
        self.back_button.clicked.connect(self._back)
        self.back_button.setVisible(False)
        self.later_button = QPushButton("以后再看")
        self.later_button.setObjectName("firstRunLater")
        self.later_button.clicked.connect(self._complete)
        footer.addWidget(self.back_button)
        footer.addStretch(1)
        footer.addWidget(self.later_button)
        root.addLayout(footer)

        self.setStyleSheet(
            "QDialog#firstRunDialog { background: #fffaf6; }"
            "QLabel#firstRunTitle { font-size: 24px; font-weight: 800; color: #263238; }"
            "QLabel#firstRunLead { font-size: 14px; color: #475467; }"
            "QPushButton { min-height: 36px; padding: 0 14px; border-radius: 10px; }"
            "QPushButton#firstRunPrimary { background: #e66b84; color: white; font-weight: 700; }"
            "QPushButton#firstRunChoice { text-align: left; padding: 12px 16px; min-height: 58px; }"
        )

    @staticmethod
    def _copy_label(text: str, *, title: bool = False) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("firstRunTitle" if title else "firstRunLead")
        return label

    def _welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        layout.addWidget(self._copy_label("让桌面宠物真正陪你生活", title=True))
        layout.addWidget(
            self._copy_label(
                "MyPets 会在桌面上活动。点击它可以查看当前最需要的照料，拖动可以调整位置，托盘菜单用于切换宠物和管理更多功能。"
            )
        )
        highlights = QLabel("• 点击宠物：打开快捷养宠面板\n• 拖动宠物：移动到喜欢的位置\n• 双击宠物：立即互动\n• 右键或托盘：进入完整功能")
        highlights.setWordWrap(True)
        highlights.setStyleSheet(
            "background: white; border: 1px solid #f0d8dd; border-radius: 14px; "
            "padding: 16px; color: #344054; line-height: 1.5;"
        )
        layout.addWidget(highlights)
        layout.addStretch(1)
        start = QPushButton("开始设置")
        start.setObjectName("firstRunPrimary")
        start.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        layout.addWidget(start, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _mode_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.addWidget(self._copy_label("选择使用方式", title=True))
        layout.addWidget(self._copy_label("可先体验本地宠物，也可以登录同步 Web 端的宠物、消息和提醒。"))

        local_button = QPushButton("先体验本地宠物\n无需登录，照料只保存在这台电脑")
        local_button.setObjectName("firstRunChoice")
        local_button.clicked.connect(lambda: self.pages.setCurrentIndex(2))
        layout.addWidget(local_button)

        cloud_button = QPushButton("登录并同步我的宠物\n同步多宠物、成长、好友、消息、提醒和串门状态")
        cloud_button.setObjectName("firstRunChoice")
        cloud_button.clicked.connect(self._login)
        layout.addWidget(cloud_button)
        layout.addStretch(1)
        return page

    def _controls_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(13)
        layout.addWidget(self._copy_label("准备完成", title=True))
        self.pet_label = self._copy_label("当前宠物：我的宠物")
        self.pet_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #344054;")
        layout.addWidget(self.pet_label)
        layout.addWidget(
            self._copy_label(
                "接下来点击桌面宠物，会看到状态解释、今日照料进度和系统推荐的下一步。常用照料可以直接完成，不必先打开复杂窗口。"
            )
        )
        tip = QLabel("建议先完成 3 次不同的日常互动，熟悉投喂、玩耍、清洁、摸摸和休息。")
        tip.setWordWrap(True)
        tip.setStyleSheet(
            "background: #edf8f1; border-radius: 12px; padding: 14px; color: #256447;"
        )
        layout.addWidget(tip)
        layout.addStretch(1)
        done = QPushButton("开始养宠")
        done.setObjectName("firstRunPrimary")
        done.clicked.connect(self._complete)
        layout.addWidget(done, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def set_pet_name(self, pet_name: str) -> None:
        self.pet_label.setText(f"当前宠物：{pet_name or '我的宠物'}")

    def restart(self) -> None:
        self.pages.setCurrentIndex(0)
        self.show()
        self.raise_()
        self.activateWindow()

    def _page_changed(self, index: int) -> None:
        self.step_label.setText(f"第 {index + 1} 步，共 3 步")
        self.back_button.setVisible(index > 0)

    def _back(self) -> None:
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))

    def _login(self) -> None:
        self.completed.emit()
        self.accept()
        self.login_requested.emit()

    def _complete(self) -> None:
        self.completed.emit()
        self.accept()
