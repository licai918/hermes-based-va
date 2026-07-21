# Publishes the architecture-reconciliation / local-first vertical slices (32-37)
# as GitHub issues, following the Python-native pivot in ADR-0139/0140/0141/0142.
# These extend the Text-First Launch PRD (#2) after the in-process TS-shim
# assumption was replaced by per-profile Hermes over HTTP + Postgres.
# Run from repo root: pwsh scripts/publish-arch-slices.ps1

$ErrorActionPreference = "Stop"
$ParentIssue = 2
$Label = "ready-for-agent"
$map = @{}

function Resolve-Refs([object[]]$refs) {
    if ($refs.Count -eq 0) { return "None - can start immediately" }
    $lines = foreach ($r in $refs) {
        if ($r -is [int]) { "- #$($map[$r])" }
        else { "- $r" }
    }
    return ($lines -join "`n")
}

function New-SliceIssue([int]$n, [string]$title, [object[]]$blockedBy, [string]$what, [string[]]$acceptance) {
    $blocked = Resolve-Refs $blockedBy
    $criteria = ($acceptance | ForEach-Object { "- [ ] $_" }) -join "`n"
    $body = @"
## Parent

#$ParentIssue

## What to build

$what

## Acceptance criteria

$criteria

## Blocked by

$blocked
"@
    $tmp = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmp, $body, [System.Text.UTF8Encoding]::new($false))
    $fullTitle = "[Slice $n] $title"
    try {
        $url = gh issue create --title $fullTitle --label $Label --body-file $tmp
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
    if ($url -match '/issues/(\d+)') { $map[$n] = [int]$Matches[1] }
    Write-Host "Slice $n -> #$($map[$n]) $title"
}

New-SliceIssue 32 "Local Toee Business Datastore (Postgres): schema, migrations, dev compose" @() @"
Stand up the Toee Business Datastore as LOCAL Postgres (docker-compose) per ADR-0140 and ADR-0142, as the development system-of-record substrate. Author schema and migrations for the structured entities: Identity Graph + Session Identity Snapshot, Customer Memory slots, Customer Thread / SMS Session / MessageTurn, Cases + Workbench Audit Log, Workbench Accounts, knowledge versions + publish state, and eval-run records. Connection config comes from env, defaults to local, needs no cloud credentials. Migrations stay Cloud SQL-portable for the later cloud slice.
"@ @(
    "docker compose brings up local Postgres; documented in ops or README",
    "Migration tool creates all system-of-record tables from a clean database",
    "Connection config read from env with local defaults; no GCP credentials required",
    "Retention-relevant timestamps/columns present per ADR-0004 and ADR-0116"
)

New-SliceIssue 33 "Postgres-backed tool handlers (datastore driver)" @(32) @"
Implement a Postgres-backed driver/repository so execute_tool reads and writes the local datastore instead of MockDriver for the structured toee_* actions: toee_case + case_manage, toee_workbench_read, audit, toee_supervisor_admin accounts, knowledge, eval review, toee_identity_lookup, and toee_customer_memory. MockDriver stays the default for eval and unit tests; a driver selector chooses datastore vs mock. Tool Gate and the profile allowlist are unchanged (same governance path).
"@ @(
    "Datastore mode performs real CRUD against local Postgres through execute_tool",
    "Tool Gate and profile allowlist behavior identical to mock mode (no governance drift)",
    "MockDriver remains default for the eval suite; datastore path covered by integration tests against local Postgres",
    "Audit and retention writes land in the datastore"
)

New-SliceIssue 34 "Per-profile Hermes API server runnable locally" @(33) @"
Promote the ADR-0141 tracer tool-dispatch app into runnable per-profile services: one process per HERMES_HOME (internal_copilot and supervisor_admin), each exposing POST /v1/tools:dispatch and GET /healthz with its own bearer token, backed by the datastore driver from Slice 33. Add local run scripts and wire the BFF env (HERMES_COPILOT_API_URL/TOKEN, HERMES_ADMIN_API_URL/TOKEN) to localhost. Cloud Run packaging is deferred to Slice 37 per ADR-0142.
"@ @(
    "Two local processes boot, each under its own HERMES_HOME and bearer token",
    "healthz returns 200; dispatch enforces bearer (401) and the profile allowlist",
    "BFF reaches each profile over http://localhost and dispatch hits Postgres-backed handlers",
    "Documented dev commands run both per-profile servers locally"
)

New-SliceIssue 35 "Workbench BFF resource routes: full HTTP cutover" @(34) @"
Migrate the remaining copilot and admin BFF resource routes off the in-memory TypeScript stores to tools:dispatch over HTTP per ADR-0141 (the tracer wired only GET /api/copilot/cases). Add snake_case to camelCase field mapping, runtime response validation against the ADR-0070 shared types, and per-error-class HTTP mapping that replaces the single 502 with ADR-0090 / ADR-0104 aligned outcomes. The in-memory fallback remains only when no API URL is configured.
"@ @(
    "All copilot and admin resource routes call the per-profile API in API-config mode; no in-memory store reads",
    "Request params and responses are mapped and validated against ADR-0070 shared types",
    "Tool Gate denials and backend failures surface as governed UI errors (ADR-0090) with correct status per error class (ADR-0104)",
    "In-memory fallback path remains for local/dev/test when no API URL is set"
)

New-SliceIssue 36 "Copilot chat + drafts over the agent-turn API (local)" @(34) @"
Implement ADR-0141 capability 2 locally: /api/copilot/chat and /api/copilot/drafts/* call the per-profile agent-turn API (Hermes OpenAI-compatible / embedded AIAgent) under the internal_copilot profile, with a deterministic local model option for tests. Drafts are never auto-sent (ADR-0036); governed send still goes through the tools:dispatch SMS reply.
"@ @(
    "Copilot draft and chat routes hit the agent-turn API, not tools:dispatch",
    "Drafts never auto-send; governed send stays on the tools:dispatch SMS path (ADR-0036)",
    "Deterministic/mock model path works in local and CI without an external LLM key",
    "Profile allowlist and Tool Gate identical to the dispatch path"
)

New-SliceIssue 37 "Cloud deploy: per-profile API servers + Cloud SQL (deferred)" @(32, 33, 34, 35, 36, "#33 (Slice 31 Cloud Run deploy)") @"
The cloud-later bucket per ADR-0142: only after the local end-to-end path is green. Containerize the two per-profile API servers, provision Cloud SQL on demand (ADR-0025), apply migrations, wire Secret Manager + OIDC (ADR-0098), deploy the servers as separate Cloud Run services (ADR-0139/0141), and extend docs/ops/deploy-cloud-run.md.
"@ @(
    "Dockerfiles and Cloud Run services exist for the internal_copilot and supervisor_admin API servers",
    "Cloud SQL provisioned on demand; migrations applied; Secret Manager holds per-profile tokens and DB credentials",
    "Staging smoke: healthz + one tools:dispatch per profile + one copilot draft",
    "Deploy runbook updated; no secrets in repo or browser"
)

Write-Host "`nPublished $($map.Count) slices. Parent: #$ParentIssue"
$map.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Host "  Slice $($_.Name) -> #$($_.Value)" }
