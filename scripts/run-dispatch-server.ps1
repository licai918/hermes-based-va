# Runs ONE per-profile Hermes tool-dispatch server on the host (ADR-0141).
#
# NOT the normal dev path any more. `pnpm dev` (scripts/dev-up.mjs) runs both
# servers as docker compose services on 8091/8092 with the rest of the stack --
# see apps/workbench/README.md. This script survives for the narrow case of
# debugging one server against host-side code; stop the composed one first
# (`docker compose stop dispatch-copilot`) so the port is free, and remember a
# server left running here is exactly the stale process that runbook warns about.
#
# Examples (from repo root):
#   pwsh scripts/run-dispatch-server.ps1 -Profile internal_copilot -Port 8091 -Token dev-copilot-token -ToolBackend datastore
#   pwsh scripts/run-dispatch-server.ps1 -Profile supervisor_admin -Port 8092 -Token dev-admin-token -ToolBackend datastore

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
