# Hermes Python SMS gateway (ADR-0095, SimpleTexting). Loads hermes-runtime/.env at boot.
#
# Example (from repo root):
#   pwsh scripts/run-gateway.ps1
#   pwsh scripts/run-gateway.ps1 -Port 8080

[CmdletBinding()]
param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

$runtimeDir = Join-Path (Join-Path $PSScriptRoot "..") "hermes-runtime"
$envFile = Join-Path $runtimeDir ".env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { return }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if ($key -and -not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $val)
        }
    }
}

Write-Host "Starting Hermes SMS gateway (SimpleTexting; OpenRouter + Composio from hermes-runtime/.env)"
Write-Host "  healthz:  http://127.0.0.1:$Port/healthz"
Write-Host "  webhook:  POST http://127.0.0.1:$Port/webhooks/simpletexting?token=<SIMPLETEXTING_WEBHOOK_TOKEN>"

Push-Location $runtimeDir
try {
    uv run uvicorn hermes_runtime.gateway_composition:build_gateway_app `
        --factory --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
