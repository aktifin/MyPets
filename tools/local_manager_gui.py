"""一图桌宠与云养宠本地服务与程序管理器 GUI 工具。

本模块提供可交互的 PySide6 图形化控制台，用于一键启动、停止、监控和调试
后端 API 服务、Web 管理台、桌宠客户端程序、流程确认门禁及自动化测试。
"""

from __future__ import annotations

import os
import sys

os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts.warning=false"

import webbrowser
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON_EXE.exists():
    PYTHON_EXE = Path(sys.executable)


class LocalManagerWindow(QMainWindow):
    """本地服务与程序管理器主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MyPets 本地服务与程序管理器")
        self.resize(1020, 680)

        self.processes: dict[str, QProcess] = {}

        self._setup_ui()
        self._apply_stylesheet()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # 头部说明
        header = QHBoxLayout()
        header_text = QVBoxLayout()
        title = QLabel("MyPets 本地服务与程序管理器")
        title.setObjectName("appTitle")
        subtitle = QLabel("统一管控桌宠客户端、FastAPI 后端 API、Web 控制台及门禁测试工具")
        subtitle.setObjectName("appSubtitle")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header.addLayout(header_text)
        header.addStretch()

        main_layout.addLayout(header)

        # 主分割区域 (上下分割: 上为功能区，下为日志控制台)
        splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(splitter)

        # 上半部分：控制卡片网格
        cards_widget = QWidget()
        cards_layout = QVBoxLayout(cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(12)

        # 1. 后端 API 与 Web 管理台卡片
        backend_card = self._create_card(
            title="1. 云养宠后端 API 与 Web 管理台",
            desc="FastAPI 模块化单体服务，提供账号认证、设备秘钥、同步及 Web 控制台 (/admin)。",
            btn_start_text="启动后端服务",
            btn_stop_text="停止后端",
            on_start=self._start_backend,
            on_stop=lambda: self._stop_process("backend"),
            extra_buttons=[
                ("打开 Web 控制台 (/admin)", lambda: webbrowser.open("http://127.0.0.1:8000/admin")),
                ("打开 Swagger 文档 (/docs)", lambda: webbrowser.open("http://127.0.0.1:8000/docs")),
            ],
            key="backend",
        )
        cards_layout.addWidget(backend_card)

        # 2. 桌宠桌面客户端卡片
        client_card = self._create_card(
            title="2. 一图桌宠桌面客户端",
            desc="基于 PySide6 的桌面透明交互桌宠程序 (main.py)。",
            btn_start_text="启动桌宠程序",
            btn_stop_text="关闭桌宠",
            on_start=self._start_client,
            on_stop=lambda: self._stop_process("client"),
            key="client",
        )
        cards_layout.addWidget(client_card)

        # 3. 门禁与确认工具卡片
        workflow_card = self._create_card(
            title="3. 制作流程与人工确认门禁",
            desc="标准角色确认窗口与八相位走路 GIF 动态人工门禁。",
            btn_start_text="打开标准角色确认窗口",
            btn_stop_text=None,
            on_start=self._approve_character,
            on_stop=None,
            extra_buttons=[
                ("登记演示角色候选", self._init_demo_candidate),
                ("查看流程状态", self._check_workflow_status),
            ],
            key="workflow",
        )
        cards_layout.addWidget(workflow_card)

        # 4. 素材校验与测试卡片
        test_card = self._create_card(
            title="4. 素材校验与单元测试",
            desc="校验动画帧 Manifest 清单并运行 PyTest 测试套件。",
            btn_start_text="运行 Manifest 校验",
            btn_stop_text=None,
            on_start=self._run_manifest_validation,
            on_stop=None,
            extra_buttons=[
                ("运行后端 PyTest 测试", self._run_pytest),
            ],
            key="test",
        )
        cards_layout.addWidget(test_card)

        cards_layout.addStretch()
        splitter.addWidget(cards_widget)

        # 下半部分：日志控制台
        console_widget = QWidget()
        console_layout = QVBoxLayout(console_widget)
        console_layout.setContentsMargins(0, 8, 0, 0)
        console_layout.setSpacing(6)

        console_header = QHBoxLayout()
        console_label = QLabel("控制台日志输出")
        console_label.setObjectName("consoleLabel")
        btn_clear = QPushButton("清空日志")
        btn_clear.clicked.connect(self._clear_log)
        console_header.addWidget(console_label)
        console_header.addStretch()
        console_header.addWidget(btn_clear)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("logConsole")

        console_layout.addLayout(console_header)
        console_layout.addWidget(self.log_text)

        splitter.addWidget(console_widget)
        splitter.setSizes([380, 240])

        self._log("管理器启动完成。就绪。")

    def _create_card(
        self,
        title: str,
        desc: str,
        btn_start_text: str | None,
        btn_stop_text: str | None,
        on_start,
        on_stop,
        extra_buttons: list[tuple[str, any]] | None = None,
        key: str = "",
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("cardFrame")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("cardTitle")
        lbl_desc = QLabel(desc)
        lbl_desc.setObjectName("cardDesc")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if btn_start_text:
            btn_start = QPushButton(btn_start_text)
            btn_start.setObjectName("btnPrimary")
            btn_start.clicked.connect(on_start)
            btn_row.addWidget(btn_start)

        if btn_stop_text:
            btn_stop = QPushButton(btn_stop_text)
            btn_stop.setObjectName("btnDanger")
            btn_stop.clicked.connect(on_stop)
            btn_row.addWidget(btn_stop)

        if extra_buttons:
            for text, handler in extra_buttons:
                btn_extra = QPushButton(text)
                btn_extra.setObjectName("btnSecondary")
                btn_extra.clicked.connect(handler)
                btn_row.addWidget(btn_extra)

        btn_row.addStretch()

        lbl_status = QLabel("状态: 离线")
        lbl_status.setObjectName("cardStatus")
        setattr(self, f"lbl_status_{key}", lbl_status)
        btn_row.addWidget(lbl_status)

        layout.addLayout(btn_row)
        return card

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
            }
            QMainWindow {
                background-color: #0f172a;
            }
            #appTitle {
                color: #f8fafc;
                font-size: 20px;
                font-weight: bold;
            }
            #appSubtitle {
                color: #94a3b8;
                font-size: 12px;
            }
            #cardFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            #cardTitle {
                color: #38bdf8;
                font-size: 14px;
                font-weight: bold;
            }
            #cardDesc {
                color: #cbd5e1;
                font-size: 12px;
            }
            #cardStatus {
                color: #64748b;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton {
                border: none;
                border-radius: 5px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
            }
            #btnPrimary {
                background-color: #0284c7;
                color: #ffffff;
            }
            #btnPrimary:hover {
                background-color: #0369a1;
            }
            #btnSecondary {
                background-color: #334155;
                color: #f1f5f9;
            }
            #btnSecondary:hover {
                background-color: #475569;
            }
            #btnDanger {
                background-color: #be123c;
                color: #ffffff;
            }
            #btnDanger:hover {
                background-color: #9f1239;
            }
            #consoleLabel {
                color: #e2e8f0;
                font-weight: bold;
                font-size: 13px;
            }
            #logConsole {
                background-color: #020617;
                color: #38bdf8;
                border: 1px solid #1e293b;
                border-radius: 6px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
            }
        """
        )

    def _log(self, text: str) -> None:
        self.log_text.append(text)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)

    def _clear_log(self) -> None:
        self.log_text.clear()

    def _start_process(
        self,
        key: str,
        program: str,
        args: list[str],
        cwd: Path,
        env_vars: dict[str, str] | None = None,
    ) -> None:
        if key in self.processes and self.processes[key].state() != QProcess.ProcessState.NotRunning:
            self._log(f"[{key}] 进程已经在运行中。")
            return

        process = QProcess(self)
        process.setWorkingDirectory(str(cwd))

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        # 设置环境变量
        from PySide6.QtCore import QProcessEnvironment

        qenv = QProcessEnvironment.systemEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)
        process.setProcessEnvironment(qenv)

        process.readyReadStandardOutput.connect(
            lambda: self._handle_output(key, self._decode_bytes(process.readAllStandardOutput().data()))
        )
        process.readyReadStandardError.connect(
            lambda: self._handle_output(key, self._decode_bytes(process.readAllStandardError().data()))
        )
        process.finished.connect(lambda exit_code, status: self._handle_finished(key, exit_code))

        process.start(program, args)
        self.processes[key] = process

        lbl = getattr(self, f"lbl_status_{key}", None)
        if lbl:
            lbl.setText("状态: 运行中")
            lbl.setStyleSheet("color: #4ade80;")

        self._log(f"[{key}] 已启动: {program} {' '.join(args)}")

    @staticmethod
    def _decode_bytes(data: bytes) -> str:
        if not data:
            return ""
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return data.decode("gbk")
            except UnicodeDecodeError:
                return data.decode("utf-8", errors="replace")

    def _stop_process(self, key: str) -> None:
        if key in self.processes:
            proc = self.processes[key]
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.terminate()
                QTimer.singleShot(2000, lambda: proc.kill() if proc.state() != QProcess.ProcessState.NotRunning else None)
                self._log(f"[{key}] 已请求停止进程。")

    def _handle_output(self, key: str, text: str) -> None:
        for line in text.splitlines():
            line_str = line.strip()
            if line_str:
                self._log(f"[{key}] {line_str}")

    def _handle_finished(self, key: str, exit_code: int) -> None:
        self._log(f"[{key}] 进程退出 (代码: {exit_code})")
        if key == "workflow" and exit_code == 2:
            self._log("💡【流程指引】暂无等待确认的标准角色候选图。请点击下方卡片中的【登记演示角色候选】按钮，登记成功后再点击【打开标准角色确认窗口】进行预览！")
        lbl = getattr(self, f"lbl_status_{key}", None)
        if lbl:
            lbl.setText("状态: 离线")
            lbl.setStyleSheet("color: #64748b;")

    # ---- 快捷管理行为 ----

    def _start_backend(self) -> None:
        env_vars = {
            "MYPETS_JWT_SECRET": "mypets-secret-key-for-local-dev-test-123456789",
            "MYPETS_ADMIN_USERNAMES": "pet_editor,pet_reviewer",
        }
        self._start_process(
            key="backend",
            program=str(PYTHON_EXE),
            args=["-m", "uvicorn", "mypets_backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
            cwd=PROJECT_ROOT / "backend",
            env_vars=env_vars,
        )

    def _start_client(self) -> None:
        self._start_process(
            key="client",
            program=str(PYTHON_EXE),
            args=["main.py"],
            cwd=PROJECT_ROOT,
        )

    def _init_demo_candidate(self) -> None:
        demo_img = "assets/pet/idle/idle_01.png"
        self._log("[workflow] 正在初始化演示测试原图与标准角色候选...")
        self._start_process(
            key="workflow",
            program=str(PYTHON_EXE),
            args=["tools/onepic_workflow.py", "init", "--source", demo_img],
            cwd=PROJECT_ROOT,
        )
        QTimer.singleShot(
            1500,
            lambda: self._start_process(
                key="workflow",
                program=str(PYTHON_EXE),
                args=[
                    "tools/onepic_workflow.py",
                    "character-candidate",
                    "--image",
                    demo_img,
                    "--style",
                    "original_preserved",
                    "--feature",
                    "演示角色",
                ],
                cwd=PROJECT_ROOT,
            ),
        )

    def _approve_character(self) -> None:
        self._start_process(
            key="workflow",
            program=str(PYTHON_EXE),
            args=["tools/onepic_workflow.py", "approve-character"],
            cwd=PROJECT_ROOT,
        )

    def _check_workflow_status(self) -> None:
        self._start_process(
            key="workflow",
            program=str(PYTHON_EXE),
            args=["tools/onepic_workflow.py", "status"],
            cwd=PROJECT_ROOT,
        )

    def _run_manifest_validation(self) -> None:
        self._start_process(
            key="test",
            program=str(PYTHON_EXE),
            args=["tools/validate_pet_manifest.py", "outputs/sun-sun/manifest.json"],
            cwd=PROJECT_ROOT,
        )

    def _run_pytest(self) -> None:
        self._start_process(
            key="test",
            program=str(PYTHON_EXE),
            args=["-m", "pytest", "backend/tests"],
            cwd=PROJECT_ROOT,
        )

    def closeEvent(self, event) -> None:
        for key, proc in list(self.processes.items()):
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    default_font = QFont("Microsoft YaHei", 9)
    default_font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(default_font)
    window = LocalManagerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
