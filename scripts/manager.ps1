param(
    [switch]$Gui,
    [switch]$Backend,
    [switch]$Client,
    [switch]$Status,
    [switch]$Test,
    [switch]$Build,
    [switch]$BuildPrivate,
    [switch]$CheckEnv,
    [switch]$ApproveWalk,
    [switch]$h,
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

$keys = @($PSBoundParameters.Keys)
$rawArgs = @($args)

if ($h -or $Help -or ($keys -contains "Help") -or ($keys -contains "h") -or ($rawArgs -contains "Help") -or ($rawArgs -contains "h") -or ($rawArgs -contains "-h")) {
    Write-Host "=================================================================="
    Write-Host "  MyPets 本地服务与程序管理器 (PowerShell)"
    Write-Host "=================================================================="
    Write-Host " 用法："
    Write-Host "   .\scripts\manager.ps1               # 启动 PySide6 图形化控制台仪表盘"
    Write-Host "   .\scripts\manager.ps1 -Backend      # 单独启动后端 API 服务及 Web 管理台"
    Write-Host "   .\scripts\manager.ps1 -Client       # 单独启动桌宠客户端"
    Write-Host "   .\scripts\manager.ps1 -Status       # 检查工作流与后台服务状态"
    Write-Host "   .\scripts\manager.ps1 -Test         # 运行全套单元测试与客户端冒烟测试"
    Write-Host "   .\scripts\manager.ps1 -Build        # 执行 PyInstaller 公开构建"
    Write-Host "   .\scripts\manager.ps1 -BuildPrivate # 执行包含私有素材的 EXE 打包"
    Write-Host "   .\scripts\manager.ps1 -CheckEnv     # 运行系统与 Python 环境检查"
    Write-Host "   .\scripts\manager.ps1 -ApproveWalk  # 打开八相位走路 GIF 人工确认窗口"
    Write-Host "=================================================================="
    exit 0
}

if ($CheckEnv -or ($keys -contains "CheckEnv") -or ($rawArgs -contains "CheckEnv")) {
    Write-Host "[OnePic] 运行环境检查..."
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "check_environment.ps1")
    exit 0
}

if ($Backend -or ($keys -contains "Backend") -or ($rawArgs -contains "Backend")) {
    Write-Host "[OnePic] 启动云养宠后端 API、Web 用户端 (http://127.0.0.1:8000/portal) 与 Web 管理台 (http://127.0.0.1:8000/admin)..."
    $env:MYPETS_JWT_SECRET = "mypets-secret-key-for-local-dev-test-123456789"
    $env:MYPETS_ADMIN_USERNAMES = "pet_editor,pet_reviewer"
    Set-Location (Join-Path $projectRoot "backend")
    & $python -m uvicorn mypets_backend.main:app --host 127.0.0.1 --port 8000 --reload
    exit 0
}

if ($Client -or ($keys -contains "Client") -or ($rawArgs -contains "Client")) {
    Write-Host "[OnePic] 启动桌宠客户端..."
    Set-Location $projectRoot
    & $python (Join-Path $projectRoot "main.py")
    exit 0
}

if ($Status -or ($keys -contains "Status") -or ($rawArgs -contains "Status")) {
    Write-Host "[OnePic] 检查一图桌宠制作工作流状态..."
    Set-Location $projectRoot
    & $python (Join-Path $projectRoot "tools\onepic_workflow.py") status
    exit 0
}

if ($ApproveWalk -or ($keys -contains "ApproveWalk") -or ($rawArgs -contains "ApproveWalk")) {
    Write-Host "[OnePic] 打开八相位走路 GIF 确认窗口..."
    Set-Location $projectRoot
    & $python (Join-Path $projectRoot "tools\onepic_workflow.py") approve-walk
    exit 0
}

if ($Test -or ($keys -contains "Test") -or ($rawArgs -contains "Test")) {
    Write-Host "[OnePic] 运行全套单元测试与冒烟测试..."
    Set-Location $projectRoot
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "test.ps1")
    exit $LASTEXITCODE
}

if ($Build -or ($keys -contains "Build") -or ($rawArgs -contains "Build")) {
    Write-Host "[OnePic] 运行公开构建..."
    Set-Location $projectRoot
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build.ps1")
    exit $LASTEXITCODE
}

if ($BuildPrivate -or ($keys -contains "BuildPrivate") -or ($rawArgs -contains "BuildPrivate")) {
    Write-Host "[OnePic] 运行私有素材打包构建..."
    Set-Location $projectRoot
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build.ps1") -IncludeUserAssets
    exit $LASTEXITCODE
}

# 默认启动 GUI
Write-Host "[OnePic] 启动图形化本地服务与程序管理器..."
Set-Location $projectRoot
& $python (Join-Path $projectRoot "tools\local_manager_gui.py")
