"""Account login and registration dialog for optional MyPets cloud synchronization."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .cloud_session import CloudSessionController
from .cloud_types import normalize_base_url


class CloudLoginDialog(QDialog):
    """Explicit account entry point; passwords never leave widget memory except for login."""

    def __init__(
        self,
        session: CloudSessionController,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("连接 MyPets 云端")
        self.setModal(False)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        description = QLabel(
            "登录后会将宠物资料同步到本机。账户密码不会保存；设备密钥仅写入系统凭据管理器。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        server_form = QFormLayout()
        self.server_url = QLineEdit(session.settings.cloud_base_url)
        self.server_url.setPlaceholderText("https://pets.example.com")
        server_form.addRow("服务地址", self.server_url)
        layout.addLayout(server_form)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_login_tab(), "登录")
        self.tabs.addTab(self._build_register_tab(), "注册")
        layout.addWidget(self.tabs)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        session.status_message.connect(self._set_status)
        session.login_failed.connect(self._login_failed)
        session.login_succeeded.connect(self._login_succeeded)

    def _build_login_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.login_username = QLineEdit()
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_password.returnPressed.connect(self._submit_login)
        submit = QPushButton("登录并绑定此电脑")
        submit.clicked.connect(self._submit_login)
        form.addRow("用户名", self.login_username)
        form.addRow("密码", self.login_password)
        form.addRow(submit)
        return page

    def _build_register_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.register_username = QLineEdit()
        self.register_display_name = QLineEdit()
        self.register_password = QLineEdit()
        self.register_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.register_confirm = QLineEdit()
        self.register_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.register_confirm.returnPressed.connect(self._submit_register)
        submit = QPushButton("创建账户并绑定此电脑")
        submit.clicked.connect(self._submit_register)
        form.addRow("用户名", self.register_username)
        form.addRow("显示名称", self.register_display_name)
        form.addRow("密码", self.register_password)
        form.addRow("确认密码", self.register_confirm)
        form.addRow(submit)
        return page

    def _apply_server_url(self) -> bool:
        try:
            normalized = normalize_base_url(self.server_url.text())
            self.session.configure_server(normalized)
            self.server_url.setText(normalized)
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "服务地址无效", str(exc))
            return False

    def _submit_login(self) -> None:
        if not self._apply_server_url():
            return
        self.status_label.setText("正在登录……")
        self.session.login(
            self.login_username.text(),
            self.login_password.text(),
        )

    def _submit_register(self) -> None:
        if not self._apply_server_url():
            return
        password = self.register_password.text()
        if password != self.register_confirm.text():
            QMessageBox.warning(self, "密码不一致", "两次输入的密码不一致")
            return
        self.status_label.setText("正在创建账户……")
        self.session.login(
            self.register_username.text(),
            password,
            register=True,
            display_name=self.register_display_name.text(),
        )

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _login_failed(self, message: str) -> None:
        self.status_label.setText(message)

    def _login_succeeded(self, display_name: str) -> None:
        self.login_password.clear()
        self.register_password.clear()
        self.register_confirm.clear()
        self.status_label.setText(f"已连接：{display_name}")
        self.accept()

    def reject(self) -> None:
        self.login_password.clear()
        self.register_password.clear()
        self.register_confirm.clear()
        super().reject()
