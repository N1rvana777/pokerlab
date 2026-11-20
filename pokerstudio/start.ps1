param([int]$Port = 8770, [string]$DataDir = "")
$ErrorActionPreference = "Stop"
$studioRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $studioRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 Python。请安装 Python 3.11+ 并勾选加入 PATH。"
}
$studioArgs = @("-X", "utf8", "-m", "pokerstudio.server", "--port", "$Port")
if ($DataDir) { $studioArgs += @("--data-dir", $DataDir) }
& python @studioArgs
if ($LASTEXITCODE -ne 0) { throw "Pokerstudio 启动失败。请查看上方错误。" }
