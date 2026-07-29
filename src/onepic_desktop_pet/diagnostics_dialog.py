"""User-facing diagnostics dialog for the final MyPets desktop composition."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class DiagnosticsDialog(QDialog):
    refresh_requested = Signal()
    export_requested = Signal()
    open_folder_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("diagnosticsDialog")
        self.setWindowTitle("MyPets 帮助与诊断")
        self.setMinimumSize(620, 430)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("帮助与诊断")
        title.setObjectName("diagnosticsTitle")
        root.addWidget(title)

        description = QLabel(
            "查看当前运行环境并导出诊断包。诊断包不包含密码、访问令牌、设备密钥、消息正文、本地数据库或宠物原图。"
        )
        description.setWordWrap(True)
        description.setObjectName("diagnosticsDescription")
        root.addWidget(description)

        self.summary = QTextEdit()
        self.summary.setObjectName("diagnosticsSummary")
        self.summary.setReadOnly(True)
        self.summary.setAcceptRichText(False)
        root.addWidget(self.summary, 1)

        self.status = QLabel("")
        self.status.setObjectName("diagnosticsStatus")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        actions = QHBoxLayout()
        refresh = QPushButton("刷新信息")
        refresh.clicked.connect(self.refresh_requested.emit)
        open_folder = QPushButton("打开数据目录")
        open_folder.clicked.connect(self.open_folder_requested.emit)
        export = QPushButton("导出诊断包…")
        export.setObjectName("diagnosticsPrimary")
        export.clicked.connect(self.export_requested.emit)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        actions.addWidget(refresh)
        actions.addWidget(open_folder)
        actions.addStretch(1)
        actions.addWidget(export)
        actions.addWidget(close)
        root.addLayout(actions)

        self.setStyleSheet(
            "QDialog#diagnosticsDialog { background: #fffaf6; }"
            "QLabel#diagnosticsTitle { font-size: 22px; font-weight: 800; color: #263238; }"
            "QLabel#diagnosticsDescription { color: #667085; }"
            "QTextEdit#diagnosticsSummary { background: white; border: 1px solid #eadde0; "
            "border-radius: 12px; padding: 12px; font-family: Consolas, 'Microsoft YaHei UI'; }"
            "QLabel#diagnosticsStatus { color: #475467; }"
            "QPushButton { min-height: 34px; padding: 0 13px; border-radius: 9px; }"
            "QPushButton#diagnosticsPrimary { background: #e66b84; color: white; font-weight: 700; }"
        )

    def set_summary(self, text: str) -> None:
        self.summary.setPlainText(text)

    def set_status(self, text: str, *, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet("color: #b42318;" if error else "color: #256447;")
