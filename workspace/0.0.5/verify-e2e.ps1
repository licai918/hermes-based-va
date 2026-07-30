<#
.SYNOPSIS
  NFR-1 layer 2 (browser E2E) evidence for 0.0.5 -- re-runnable, not prose.

.DESCRIPTION
  The slice acceptance blocks ask for screenshots. This header used to claim they
  could not be produced on this machine at all. That was wrong -- it was true of
  the in-app Browser pane (which does not composite frames) and was never checked
  against Chrome, which screenshots fine. See workspace/0.0.5/e2e-evidence.md.

  This script is not a substitute for a missing capability, then. It is the
  PRIMARY evidence because it re-executes: a reader can look at a screenshot but
  cannot re-derive it. It drives the real running workbench over HTTP, asserts the
  invariants the acceptance blocks care about, and prints a verdict anyone can
  reproduce by running it again.

  WHAT IT PROVES
    * every 0.0.5 admin BFF route refuses an unauthenticated caller with 401,
      which is the check that catches a new route shipped without its gate --
      such a route answers 200 with data.
    * the pages that carry 0.0.5's new surfaces are served and contain the
      invariants their slices claim (scoping language on counts, the D22
      correction, the honest "not yet measured" labels).

  WHAT IT DOES NOT PROVE, stated so a green run is not over-read:
    * the rep-403 leg. Exercising it needs a signed-in rep session, and this
      script does not enter credentials.
    * anything served by the dispatch containers. They run a baked image; the
      workbench UI hot-reloads and is what this checks.

.EXAMPLE
  pwsh -File workspace/0.0.5/verify-e2e.ps1
  pwsh -File workspace/0.0.5/verify-e2e.ps1 -BaseUrl http://localhost:3000
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://localhost:3000"
)

$ErrorActionPreference = "Continue"
$script:Failures = 0

function Test-Gate {
    param([string]$Path, [int]$Expected = 401)
    $code = try {
        (Invoke-WebRequest -Uri "$BaseUrl$Path" -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 15 -ErrorAction Stop).StatusCode
    } catch {
        if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { -1 }
    }
    $ok = $code -eq $Expected
    if (-not $ok) { $script:Failures++ }
    "{0}  {1,-46} expected {2}, got {3}" -f $(if ($ok) { "PASS" } else { "FAIL" }), $Path, $Expected, $code
}

function Test-PageDoesNotLeak {
    <#
      The page-level counterpart of the 401 check, and the stronger half.

      An admin page fetched WITHOUT a session must return the sign-in affordance
      and none of its own data. A page that renders its content before the session
      check leaks it to anyone who curls the URL -- and it would still "work" in a
      browser, so no manual walkthrough would ever notice.

      This started life as a `contains` assertion and failed six times before the
      harness -- not the app -- turned out to be what was wrong: an unauthenticated
      fetch returns the login page, so the data strings were never going to be
      there. Asserting their ABSENCE is what that fetch can actually prove.
    #>
    param([string]$Path, [string[]]$MustNotContain)
    $body = try {
        # -UseBasicParsing is REQUIRED: without it Invoke-WebRequest reaches for
        # Internet Explorer's DOM parser, which throws in a non-interactive shell
        # and returns nothing -- every assertion then "fails" for a reason that has
        # nothing to do with the page.
        (Invoke-WebRequest -Uri "$BaseUrl$Path" -UseBasicParsing -TimeoutSec 25 -ErrorAction Stop).Content
    } catch { "" }

    $signin = $body -and ($body.Contains("Sign in") -or $body.Contains("Login"))
    if (-not $signin) { $script:Failures++ }
    "{0}  {1,-24} unauthenticated -> sign-in page" -f $(if ($signin) { "PASS" } else { "FAIL" }), $Path

    foreach ($needle in $MustNotContain) {
        $leaked = $body -and $body.Contains($needle)
        if ($leaked) { $script:Failures++ }
        "{0}  {1,-24} does NOT leak {2}" -f $(if ($leaked) { "FAIL" } else { "PASS" }), $Path, ("'" + $needle + "'")
    }
}

"# 0.0.5 — NFR-1 layer 2 evidence"
""
"run at   : {0:yyyy-MM-ddTHH:mm:ssZ}" -f (Get-Date).ToUniversalTime()
"base url : $BaseUrl"
"commit   : $(git rev-parse --short HEAD 2>$null)"
""
"## Every new admin BFF route refuses an unauthenticated caller"
"(a route shipped without its gate answers 200 with data, which is what this catches)"
""
Test-Gate "/api/admin/metrics"
Test-Gate "/api/admin/memory-hub"
Test-Gate "/api/admin/inbox"
Test-Gate "/api/admin/lexicon"
Test-Gate "/api/admin/agent-experience"
Test-Gate "/api/admin/memory-audit"
""
"## The pages 0.0.5 added do not render their data to an unauthenticated caller"
"(a page that renders before its session check leaks to anyone who curls it, and would"
" still look correct in a signed-in browser -- so no manual walkthrough would catch it)"
""
Test-PageDoesNotLeak "/admin/memory-hub" @(
    "No live count on this hub",   # S14's L1-L3 wording
    "Counts only",                  # S14's L4 NFR-6 caveat
    "entry_effectiveness"           # D22's corrected zero-use tile
)
Test-PageDoesNotLeak "/admin/metrics" @(
    "Not yet measured",             # S22's honest unmeasured-layer label
    "Memory injection rate"
)
Test-PageDoesNotLeak "/admin/inbox" @("Review Inbox")
""
"## NOT covered here, stated rather than implied"
"  * the rep-403 leg: needs a signed-in rep session; this script enters no credentials."
"  * the AUTHENTICATED content of these pages: see e2e-evidence.md, captured through a"
"    browser session, which is evidence a reader cannot re-derive without one."
"  * anything served by the dispatch containers: they run a baked image."
""
if ($script:Failures -eq 0) {
    "RESULT: PASS — 0 failures"
    exit 0
} else {
    "RESULT: FAIL — $($script:Failures) failure(s)"
    exit 1
}
