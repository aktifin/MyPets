@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment .venv\Scripts\python.exe not found.
    echo Please run scripts\setup_environment.ps1 first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "tools\local_manager_gui.py" %*
