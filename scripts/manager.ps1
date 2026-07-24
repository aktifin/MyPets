param(
    [switch]$Gui,
    [switch]$Backend,
    [switch]$Client,
    [switch]$Status,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$env:QT_LOGGING_RULES = "qt.qpa.fonts.warning=false"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "尚未创建 .venv，请先运行 scripts\setup_environment.ps1。"
    exit 1
}

$argList = $args + @($PSBoundParameters.Keys)

if ($Help -or ($argList -contains "Help") -or ($argList -contains "h") -or ($argList -contains "-h")) {
    Write-Host "==============================================="
    Write-Host "  MyPets 本地服务与程序管理器 (PowerShell)"
    Write-Host "==============================================="
    Write-Host " 用法："
    Write-Host "   .\scripts\manager.ps1            # 启动 PySide6 图形化控制台仪表盘"
    Write-Host "   .\scripts\manager.ps1 -Backend   # 单独启动后端 API 服务及 Web 管理台"
    Write-Host "   .\scripts\manager.ps1 -Client    # 单独启动桌宠客户端"
    Write-Host "   .\scripts\manager.ps1 -Status    # 检查工作流与后台服务状态"
    Write-Host "==============================================="
    exit 0
}

if ($Backend -or ($argList -contains "Backend")) {
    Write-Host "[OnePic] 启动云养宠后端 API 与 Web 管理台 (http://127.0.0.1:8000/admin)..."
    $env:MYPETS_JWT_SECRET = "mypets-secret-key-for-local-dev-test-123456789"
    $env:MYPETS_ADMIN_USERNAMES = "pet_editor,pet_reviewer"
    Set-Location (Join-Path $projectRoot "backend")
    & $python -m uvicorn mypets_backend.main:app --host 127.0.0.1 --port 8000 --reload
    exit 0
}

if ($Client -or ($argList -contains "Client")) {
    Write-Host "[OnePic] 启动桌宠客户端..."
    & $python (Join-Path $projectRoot "main.py")
    exit 0
}

if ($Status -or ($argList -contains "Status")) {
    Write-Host "[OnePic] 检查一图桌宠制作工作流状态..."
    & $python (Join-Path $projectRoot "tools\onepic_workflow.py") status
    exit 0
}

# 默认启动 GUI
Write-Host "[OnePic] 启动图形化本地服务与程序管理器..."
& $python (Join-Path $projectRoot "tools\local_manager_gui.py")
