@echo off
set QT_LOGGING_RULES=qt.qpa.fonts.warning=false
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 尚未创建虚拟环境 .venv\Scripts\python.exe
    echo 请先运行 scripts\setup_environment.ps1 初始化环境。
    pause
    exit /b 1
)

echo 正在启动 MyPets 本地服务与程序管理器 GUI...
".venv\Scripts\python.exe" "tools\local_manager_gui.py" %*
