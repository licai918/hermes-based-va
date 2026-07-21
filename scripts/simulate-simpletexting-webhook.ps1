# Simulate a SimpleTexting INCOMING_MESSAGE webhook against a local gateway
# (ADR-0021: auth is the shared token in the webhook URL — no body signature).
#
# Example (from repo root, gateway running via scripts/run-gateway.ps1):
#   pwsh scripts/simulate-simpletexting-webhook.ps1 -Token dev-webhook-token
#   pwsh scripts/simulate-simpletexting-webhook.ps1 -Body "STOP" -ContactPhone 7786803250

[CmdletBinding()]
param(
    [string]$GatewayUrl = "http://127.0.0.1:8080",
    [Parameter(Mandatory = $true)][string]$Token,
    [string]$Body = "Do you have 225/65R17 in stock?",
    [string]$ContactPhone = "7786803250",
    [string]$AccountPhone = "9053378266",
    [string]$MessageId = ("sim-{0}" -f ([guid]::NewGuid().ToString("N").Substring(0, 12)))
)

$ErrorActionPreference = "Stop"

$payload = @{
    reportId  = "rep-$MessageId"
    webhookId = "wh-local-sim"
    type      = "INCOMING_MESSAGE"
    values    = @{
        messageId    = $MessageId
        text         = $Body
        accountPhone = $AccountPhone
        contactPhone = $ContactPhone
        timestamp    = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
        category     = "SMS"
    }
} | ConvertTo-Json -Depth 4

$uri = "$GatewayUrl/webhooks/simpletexting?token=$([uri]::EscapeDataString($Token))"
Write-Host "POST $GatewayUrl/webhooks/simpletexting (messageId=$MessageId)"
$response = Invoke-WebRequest -Uri $uri -Method Post -ContentType "application/json" -Body $payload
Write-Host "HTTP $($response.StatusCode)"
