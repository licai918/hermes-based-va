# POST a signed TGP new_customer_post webhook (live Textline shape).
param(
    [string]$Body = "Hi",
    [string]$Phone = "(778) 680-3250",
    [string]$ConversationId = "7931e83f-96d9-4070-9ca4-081bcf36afd0",
    [string]$EventId = "evt-replay-tgp",
    [string]$GatewayUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"
$secret = $env:TEXTLINE_WEBHOOK_SECRET
if (-not $secret) { throw "TEXTLINE_WEBHOOK_SECRET is not set." }

$eventTime = [string][int][double]::Parse((Get-Date).ToUniversalTime().Subtract([datetime]'1970-01-01').TotalSeconds)
$payload = @{
    webhook = "new_customer_post"
    post = @{
        body = $Body
        created_at = [int]$eventTime
        uuid = $EventId
        conversation_uuid = $ConversationId
        is_whisper = $false
        creator = @{ type = "customer"; phone_number = $Phone }
    }
    conversation = @{ uuid = $ConversationId }
}
$rawBody = ($payload | ConvertTo-Json -Compress -Depth 6)
$signedPayload = "$eventTime.$rawBody"

$hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
$sigBytes = $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($signedPayload))
$signature = -join ($sigBytes | ForEach-Object { $_.ToString("x2") })

Write-Host "POST $GatewayUrl/webhooks/textline (TGP new_customer_post)"
Invoke-WebRequest -Method POST -Uri "$GatewayUrl/webhooks/textline" `
    -ContentType "application/json" `
    -Headers @{
        "X-Tgp-Event-Signature" = $signature
        "X-Tgp-Event-Time" = $eventTime
        "X-Tgp-Event-Type" = "new_customer_post"
    } `
    -Body $rawBody `
    -UseBasicParsing | ForEach-Object { Write-Host "HTTP $($_.StatusCode)"; if ($_.Content) { $_.Content } }
