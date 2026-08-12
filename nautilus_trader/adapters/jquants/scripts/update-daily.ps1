# J-Quants 日次カタログ更新 (タスクスケジューラ用)
# 前提: D:\jQuants\Lean\scripts\setup-op-token.ps1 と同方式の
#       DPAPI 暗号化サービスアカウントトークン (無人実行時)
param(
    [string]$Catalog = "D:\nautilus_trader\catalog",
    [string]$EnvFile = "D:\nautilus_trader\.env.1password",
    [string]$TokenFile = "$env:USERPROFILE\.jquants\op-service-token.clixml"
)
$ErrorActionPreference = "Stop"

if (-not $env:OP_SERVICE_ACCOUNT_TOKEN -and (Test-Path $TokenFile)) {
    $secure = Import-Clixml $TokenFile
    $env:OP_SERVICE_ACCOUNT_TOKEN = [System.Net.NetworkCredential]::new("", $secure).Password
}

$python = "D:\nautilus_trader\.venv\Scripts\python.exe"
op run --env-file=$EnvFile -- $python -m nautilus_trader.adapters.jquants.scripts.jquants_etl update --catalog $Catalog
if ($LASTEXITCODE -ne 0) { throw "jquants_etl update failed: $LASTEXITCODE" }
