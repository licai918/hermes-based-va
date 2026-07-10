# Runs one per-profile Hermes tool-dispatch server locally (ADR-0141, Slice 34 / #37).
# Each profile is its own process with its own bearer token and port; run this once
# per profile (two terminals) to bring up the copilot + admin servers the workbench
# BFF calls. Cloud Run packaging is deferred to Slice 37 (ADR-0142 local-first).
#
# Examples (from repo root):
#   pwsh scripts/run-dispatch-server.ps1 -Profile internal_copilot -Port 8081 -Token dev-copilot-token
#   pwsh scripts/run-dispatch-server.ps1 -Profile supervisor_admin -Port 8082 -Token dev-admin-token
#   # Back the system-of-record tools with local Postgres (see docs/ops/local-datastore.md):
#   pwsh scripts/run-dispatch-server.ps1 -Profile internal_copilot -Port 8081 -Token dev-copilot-token -ToolBackend datastore

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("internal_copilot", "supervisor_admin", "customer_service_external")]
    [string]$Profile,

    [int]$Port = 8081,

    # Dev default only. The workbench BFF must present the SAME value via
    # HERMES_COPILOT_API_TOKEN / HERMES_ADMIN_API_TOKEN for the matching server.
    [string]$Token = "dev-dispatch-token",

    [ValidateSet("mock", "datastore")]
    [string]$ToolBackend = "mock",

    # Optional Postgres DSN; only used when -ToolBackend datastore. Defaults to the
    # docker-compose DSN inside the runtime (postgresql://toee:toee@localhost:5432/toee_va).
    [string]$DatabaseUrl
)

$ErrorActionPreference = "Stop"

# Load hermes-runtime/.env (TEXTLINE_ACCESS_TOKEN, DATABASE_URL, …) — same as run-gateway.ps1.
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

$env:TOEE_HERMES_PROFILE = $Profile
$env:DISPATCH_API_TOKEN = $Token
$env:TOOL_BACKEND = $ToolBackend
if ($DatabaseUrl) { $env:DATABASE_URL = $DatabaseUrl }

Write-Host "Starting tool-dispatch server: profile=$Profile backend=$ToolBackend http://127.0.0.1:$Port"
Write-Host "  healthz:  http://127.0.0.1:$Port/healthz"
Write-Host "  dispatch: POST http://127.0.0.1:$Port/v1/tools:dispatch (Bearer $Token)"

Push-Location $runtimeDir
try {
    uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app `
        --factory --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
