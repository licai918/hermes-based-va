# POST a signed Textline inbound webhook to the local Python gateway (ADR-0021/0103).
# Requires TEXTLINE_WEBHOOK_SECRET in the environment (same as hermes-runtime/.env).
#
# Example (gateway on :8080):
#   $env:TEXTLINE_WEBHOOK_SECRET = 'whsec-dev'
#   powershell -NoProfile -File scripts/simulate-textline-webhook.ps1 -Body "Do you have 225/65R17 in stock?"

[CmdletBinding()]
param(
    [string]$Body = "Do you have 225/65R17 in stock?",
    [string]$From = "+14165550101",
    [string]$ConversationId = "conv-local-sim",
    [string]$EventId = "evt-local-sim",
    [string]$GatewayUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"

$secret = $env:TEXTLINE_WEBHOOK_SECRET
if (-not $secret) {
    throw "TEXTLINE_WEBHOOK_SECRET is not set. Export it or add it to hermes-runtime/.env before running."
}

$payload = @{
    id              = $EventId
    conversation_id = $ConversationId
    from            = $From
    body            = $Body
    received_at     = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    type            = "message.created"
}
$rawBody = ($payload | ConvertTo-Json -Compress)

$hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
$sigBytes = $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($rawBody))
$signature = -join ($sigBytes | ForEach-Object { $_.ToString("x2") })

Write-Host "POST $GatewayUrl/webhooks/textline"
Write-Host "  event_id=$EventId conversation_id=$ConversationId from=$From"

try {
    $response = Invoke-WebRequest -Method POST -Uri "$GatewayUrl/webhooks/textline" `
        -ContentType "application/json" `
        -Headers @{ "X-Textline-Signature" = $signature } `
        -Body $rawBody `
        -UseBasicParsing
    $statusCode = [int]$response.StatusCode
} catch [System.Net.WebException] {
    $statusCode = [int]$_.Exception.Response.StatusCode
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $responseBody = $reader.ReadToEnd()
    $reader.Close()
    Write-Host "HTTP $statusCode"
    if ($responseBody) { Write-Host $responseBody }
    exit 1
}

Write-Host "HTTP $statusCode"
if ($response.Content) { Write-Host $response.Content }

if ($statusCode -ge 400) {
    exit 1
}
