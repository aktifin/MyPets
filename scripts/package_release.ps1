param(
    [switch]$IncludeUserAssets
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$versionFile = Join-Path $projectRoot "VERSION"
$distRoot = Join-Path $projectRoot "dist"

if (-not (Test-Path $python)) {
    throw "尚未安装构建环境，请先运行 scripts\setup_environment.ps1。"
}
if (-not (Test-Path $versionFile)) {
    throw "缺少 VERSION 文件，不能构建发布包。"
}

$version = (Get-Content $versionFile -Raw).Trim()
if (-not $version) {
    throw "VERSION 文件为空。"
}

Write-Host "[MyPets] 执行发布元数据检查…"
& $python (Join-Path $projectRoot "tools\release_check.py")
if ($LASTEXITCODE -ne 0) {
    throw "发布元数据检查失败。"
}

Write-Host "[MyPets] 构建 Windows 客户端 $version…"
& "$PSScriptRoot\build.ps1" -IncludeUserAssets:$IncludeUserAssets
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败。"
}

$source = Join-Path $distRoot "MyPets"
if (-not (Test-Path $source)) {
    throw "未找到 PyInstaller 输出目录：$source"
}

$releaseName = "MyPets-Desktop-$version-windows-x64"
$staging = Join-Path $distRoot $releaseName
$archive = Join-Path $distRoot "$releaseName.zip"
$checksum = "$archive.sha256"

Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $archive -Force -ErrorAction SilentlyContinue
Remove-Item $checksum -Force -ErrorAction SilentlyContinue

Copy-Item $source $staging -Recurse
Copy-Item (Join-Path $projectRoot "VERSION") (Join-Path $staging "VERSION")
Copy-Item (Join-Path $projectRoot "LICENSE") (Join-Path $staging "LICENSE")
Copy-Item (Join-Path $projectRoot "docs\普通用户安装使用指南.md") (Join-Path $staging "使用说明.md")

$releaseNote = @"
MyPets Windows 客户端 $version

本压缩包仅包含 Windows 桌面客户端，不包含正式云端服务。
请完整解压后运行 MyPets.exe，不要只复制单个 EXE。
详细说明见 使用说明.md。
"@
Set-Content -Path (Join-Path $staging "发布说明.txt") -Value $releaseNote -Encoding UTF8

Compress-Archive -Path $staging -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -Path $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path $checksum -Value "$hash  $releaseName.zip" -Encoding ASCII

Write-Host "[MyPets] 发布包已生成：$archive"
Write-Host "[MyPets] SHA-256：$hash"
