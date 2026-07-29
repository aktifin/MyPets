param(
    [switch]$SkipSetup,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendRoot = Join-Path $projectRoot "backend"
$healthUrl = "http://127.0.0.1:8000/health"
$portalUrl = "http://127.0.0.1:8000/portal"
$backendProcess = $null
$ownsBackend = $false

function Test-MyPetsHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        return $response.status -eq "ok"
    } catch {
        return $false
    }
}

if (-not (Test-Path $python)) {
    if ($SkipSetup) {
        throw "尚未创建 .venv，不能跳过环境安装。请运行 scripts\setup_environment.ps1。"
    }
    & "$PSScriptRoot\setup_environment.ps1"
}

if (-not (Test-Path $python)) {
    throw "Python 虚拟环境创建失败。"
}

try {
    if (-not (Test-MyPetsHealth)) {
        Write-Host "[MyPets] 正在启动本地服务…"
        $backendProcess = Start-Process `
            -FilePath $python `
            -ArgumentList @("-m", "uvicorn", "mypets_backend.main:app", "--host", "127.0.0.1", "--port", "8000") `
            -WorkingDirectory $backendRoot `
            -WindowStyle Minimized `
            -PassThru
        $ownsBackend = $true

        $healthy = $false
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 500
            if ($backendProcess.HasExited) {
                throw "本地服务启动失败，进程已提前退出。"
            }
            if (Test-MyPetsHealth) {
                $healthy = $true
                break
            }
        }
        if (-not $healthy) {
            throw "本地服务未在预期时间内通过健康检查。"
        }
    } else {
        Write-Host "[MyPets] 检测到 127.0.0.1:8000 已有可用服务，本次不重复启动。"
    }

    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
    Write-Host "[MyPets] 服务已就绪：$($health.version) / $($health.channel)"

    if (-not $NoBrowser) {
        Start-Process $portalUrl
    }

    Write-Host "[MyPets] 正在启动桌面宠物。关闭桌面宠物后，本脚本启动的本地服务将自动结束。"
    & $python (Join-Path $projectRoot "main.py")
    exit $LASTEXITCODE
} finally {
    if ($ownsBackend -and $null -ne $backendProcess -and -not $backendProcess.HasExited) {
        Write-Host "[MyPets] 正在关闭本地服务…"
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $backendProcess.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
}
