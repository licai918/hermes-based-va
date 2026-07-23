#!/usr/bin/env node
// Repo-wide secret-scan gate (0.0.4 S12, NFR-6). ONE CI job, one script:
//
//   node scripts/secret-scan.mjs              # scan tracked files, exit 1 on a hit
//   node scripts/secret-scan.mjs --selfcheck  # prove the rules still catch things
//
// S14 (EasyRoutes) and every later integration REFERENCE this gate rather than
// adding their own -- a new credential is one entry in SECRET_VARS below, not a
// new job.
//
// Scope is deliberately narrow: `git ls-files`, i.e. what is actually committed.
// History rewriting and provider-side rotation are out of scope; this stops the
// next token from landing, it does not clean up one that already did.
//
// Three rules, in increasing order of how often they fire:
//
// 1. NO TRACKED ENV FILE. `.env` / `.env.local` are where real credentials live
//    on every box in this repo (docker-compose reads hermes-runtime/.env,
//    `pnpm dev` reads apps/workbench/.env.local). Committing one is the single
//    most likely way a secret gets in, and it needs no pattern matching to catch.
// 2. KNOWN TOKEN SHAPES. Public, documented prefixes only -- a shape-based rule
//    that guesses is a rule people learn to skip.
// 3. SECRET-NAMED ASSIGNMENT WITH A REAL VALUE. Catches the pasted token in a
//    doc, a compose file, or a CI workflow, whatever its shape. This is the rule
//    that covers vendors with no recognizable prefix (Composio, SimpleTexting).
//    Placeholders and this repo's published dev defaults are allowed.

import { spawnSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { join, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

// Rule 1: tracked env files. `*.env.example` is the documented template and is
// the ONLY env-shaped file allowed in the tree.
const ENV_FILE = /(^|\/)\.env($|\.)|\.env$/;
const ENV_FILE_ALLOWED = /\.env\.example$/;

// Rule 2: public, documented credential prefixes. Anchored lengths keep prose
// like "sk-" or "ghp" from matching.
const TOKEN_SHAPES = [
  ["OpenRouter", /\bsk-or-v1-[A-Za-z0-9]{32,}/],
  ["Anthropic", /\bsk-ant-[A-Za-z0-9_-]{24,}/],
  ["OpenAI", /\bsk-[A-Za-z0-9]{40,}/],
  ["Shopify", /\bshp(at|ca|pa|ss)_[A-Fa-f0-9]{32}\b/],
  ["Slack", /\bxox[abprs]-[A-Za-z0-9-]{12,}/],
  ["GitHub", /\bgh[pousr]_[A-Za-z0-9]{36}\b/],
  ["AWS", /\bAKIA[0-9A-Z]{16}\b/],
  ["Google API key", /\bAIza[0-9A-Za-z_-]{35}\b/],
  ["private key", /-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/],
  // A bearer token pasted into a test fixture or a curl example carries no
  // variable name and no vendor prefix, so rule 3 never sees it (fix wave 1,
  // review Finding 7). The 20-char floor clears this repo's published dev
  // defaults -- `Bearer dev-copilot-token` is 17 -- and `${VAR}` interpolation
  // cannot match the character class at all.
  ["bearer token", /\bBearer\s+[A-Za-z0-9_.-]{20,}/],
];

// Rule 3: variables whose VALUE is a credential. Add one line per new
// integration; the shape does not matter.
const SECRET_VARS = [
  "COMPOSIO_API_KEY",
  "OPENROUTER_API_KEY",
  "SIMPLETEXTING_API_TOKEN",
  "SIMPLETEXTING_WEBHOOK_TOKEN",
  "EASYROUTES_API_TOKEN",
  "EASYROUTES_CLIENT_ID",
  "GADGET_API_KEY",
  "INTERNAL_JOB_SECRET",
  "DISPATCH_API_TOKEN",
  "HERMES_COPILOT_API_TOKEN",
  "HERMES_ADMIN_API_TOKEN",
  "HERMES_EXTERNAL_SIM_TOKEN",
  "WORKBENCH_SESSION_SECRET",
  "NGROK_AUTHTOKEN",
];

// Values that are not credentials. The two load-bearing ones are the last two:
// a value made only of lowercase letters and dashes is a human-written slug
// ("dev-webhook-token", "copilot-tok", "from-env"), and an all-caps one is a
// constant reference -- neither is a credential, because every provider's tokens
// carry digits, mixed case, or underscores. Those two rules clear the test
// fixtures and published dev defaults this repo is full of.
//
// Both were too wide at the original 40-char ceiling (fix wave 1, review Finding
// 7) -- they waved through a real token that happened to be all-caps
// ("AB12CD34EF56GH78IJ90KL12MN34OP56", which the SCREAMING_CASE rule accepted
// digits and all) or all-lowercase ("zzrealvaluepastedhereandhere"). Fix wave 1
// was one tightening plus one widening, not two tightenings (0.0.4 S12 fix wave
// 2 correction -- the report had claimed both were tightened):
//
//   - a constant reference is capped at 24 chars (TIGHTENED from 40). This
//     repo's longest is INTERNAL_JOB_SECRET (19); no provider issues a 24-char
//     all-caps token that is also a plausible identifier. This cap alone would
//     flag an honest placeholder like "CHANGE_ME_BEFORE_DEPLOY_PLEASE" (31
//     chars) as a secret -- the explicit placeholder allowlist below (fix wave
//     2) keeps those clean without reopening the 24+ char real-token shape.
//   - a lowercase value longer than 24 chars must be HYPHENATED to count as
//     human-written (TIGHTENED). "workbench-dev-session-secret-change-me" (38)
//     reads as a published dev default; an unbroken run of 28 letters reads as
//     a paste.
//   - a short (<=12 char) lowercase-alnum stub, e.g. "tok-123" / "or-key-123",
//     now passes where it previously did not (WIDENED, fix wave 1 -- these are
//     exactly the fixture values `tests/test_gateway_composition.py` and
//     friends assign to SIMPLETEXTING_API_TOKEN / OPENROUTER_API_KEY). Kept
//     deliberately: no real vendor token is this short, and every shaped one
//     is caught by TOKEN_SHAPES regardless of length.
const NOT_A_SECRET = [
  /^$/,
  /^<.*>$/, //          <your-token>
  /\.{3}/, //           ca_..., sk-or-...
  /^\$\{?[A-Za-z_]/, // ${VAR} / $VAR interpolation
  /^-/, //              ${VAR:-default} shell substitution
  /^[A-Za-z_$][\w$]*\./, // code reference: rt.INTERNAL_JOB_SECRET, webhookToken.value
  // Obvious placeholders, regardless of length -- added fix wave 2 so narrowing
  // the SCREAMING_CASE cap to 24 (above) doesn't flag a legitimate long
  // placeholder like "CHANGE_ME_BEFORE_DEPLOY_PLEASE" or "YOUR_API_KEY_HERE".
  // Named prefixes only, so this can't accidentally wave through a real random
  // token -- a real secret does not spell out "replace me".
  /^(CHANGE_?ME|REPLACE_?ME|YOUR_[A-Z0-9_]*_HERE|TODO|FIXME|PLACEHOLDER|SAMPLE|EXAMPLE)([A-Z0-9_]*)$/i,
  /^X{4,}$/i, //        XXXX... redaction placeholder
  /^[A-Z_][A-Z0-9_]{0,23}$/, // SCREAMING_CASE constant reference: `= SECRET`
  /^[a-z0-9-]+:(latest|\d+)$/, // Secret Manager ref: composio-api-key:latest
  /^[a-z][a-z-]{0,23}$/, //     short slug: "from-env", "dev-webhook-token"
  /^(?=.{2,40}$)[a-z][a-z-]*-[a-z-]*$/, // longer slug, but hyphenated
  /^[a-z][a-z0-9-]{0,11}$/, //  short fixture stub: "tok-123", "or-key-123" (widened, see above)
];

// The value stops at whitespace, a comment, or the punctuation that ends a
// literal in .env / YAML / JS / shell -- otherwise a `--set-secrets="A=x,B=y"`
// list is captured as one giant "value".
//
// Fix wave 1 (review Finding 7): the name may be QUOTED, so `"COMPOSIO_API_KEY":
// "..."` in JSON matches -- previously the closing quote sat between the name and
// the `:` and the whole rule missed.
const SECRET_ASSIGNMENT = new RegExp(
  `["']?\\b(${SECRET_VARS.join("|")})\\b["']?\\s*[=:]\\s*["']?([^\\s#,;"'\`)}]*)`,
);

// Same rule for a lower/mixed-case spelling (`composio_api_key = "..."` in a
// fixture), but ONLY when the value is a quoted string literal. Without that
// restriction every Python parameter and local named `internal_job_secret` is a
// finding, and a gate that cries wolf is a gate people stop reading.
const SECRET_ASSIGNMENT_QUOTED = new RegExp(
  `\\b(${SECRET_VARS.join("|")})\\b\\s*[=:]\\s*["']([^\\s#,;"'\`)}]*)`,
  "i",
);

// Files whose whole point is to describe the gate. Scanning them makes every
// pattern in this file its own finding.
const SELF = ["scripts/secret-scan.mjs"];

/** One finding. `file` is repo-relative with forward slashes. */
function finding(rule, file, line, detail) {
  return { rule, file, line, detail };
}

export function checkEnvFilename(file) {
  if (!ENV_FILE.test(file) || ENV_FILE_ALLOWED.test(file)) return null;
  return finding(
    "tracked env file",
    file,
    0,
    "env files hold real credentials on every box; only *.env.example may be committed",
  );
}

export function checkLine(file, lineNo, text) {
  for (const [vendor, pattern] of TOKEN_SHAPES) {
    if (pattern.test(text)) {
      return finding("token shape", file, lineNo, `looks like a ${vendor} credential`);
    }
  }
  for (const pattern of [SECRET_ASSIGNMENT, SECRET_ASSIGNMENT_QUOTED]) {
    const assignment = pattern.exec(text);
    if (!assignment) continue;
    const [, name, value] = assignment;
    if (!NOT_A_SECRET.some((allowed) => allowed.test(value))) {
      return finding("secret assignment", file, lineNo, `${name} is assigned a non-placeholder value`);
    }
  }
  return null;
}

function trackedFiles() {
  const res = spawnSync("git", ["ls-files", "-z"], { cwd: ROOT, encoding: "utf8", maxBuffer: 64 << 20 });
  if (res.status !== 0) {
    console.error(`[secret-scan] git ls-files failed: ${(res.stderr || "").trim()}`);
    process.exit(2);
  }
  return res.stdout.split("\0").filter(Boolean);
}

function scan() {
  const findings = [];
  for (const file of trackedFiles()) {
    if (SELF.includes(file)) continue;

    const envHit = checkEnvFilename(file);
    if (envHit) {
      findings.push(envHit);
      continue;
    }

    let text;
    try {
      // Skip anything big enough to be a lockfile/binary; a pasted token is a line.
      if (statSync(join(ROOT, file)).size > 2 << 20) continue;
      text = readFileSync(join(ROOT, file), "utf8");
    } catch {
      continue; // unreadable or deleted-but-tracked
    }
    if (text.includes("\0")) continue; // binary

    text.split(/\r?\n/).forEach((line, i) => {
      const hit = checkLine(file, i + 1, line);
      if (hit) findings.push(hit);
    });
  }
  return findings;
}

// The one runnable check: `node scripts/secret-scan.mjs --selfcheck`. A gate
// nobody can prove still bites is a gate that quietly stops biting.
function selfcheck() {
  const cases = [
    [checkEnvFilename("hermes-runtime/.env"), true, "tracked .env is a finding"],
    [checkEnvFilename("apps/workbench/.env.local"), true, "tracked .env.local is a finding"],
    [checkEnvFilename(".env.example"), false, ".env.example is allowed"],
    [checkEnvFilename("hermes-runtime/.env.example"), false, "nested .env.example is allowed"],
    [checkEnvFilename("docs/ops/deploy-cloud-run.md"), false, "a normal file is not a finding"],
    [checkLine("x", 1, `OPENROUTER_API_KEY=sk-or-v1-${"a".repeat(64)}`), true, "OpenRouter key shape"],
    [checkLine("x", 1, `token: shpat_${"0".repeat(32)}`), true, "Shopify token shape"],
    [checkLine("x", 1, "-----BEGIN RSA PRIVATE KEY-----"), true, "private key block"],
    [checkLine("x", 1, "COMPOSIO_API_KEY=zz9realvaluepastedhere"), true, "unshaped secret by var name"],
    [checkLine("x", 1, "EASYROUTES_API_TOKEN: A1b2C3d4E5f6G7h8"), true, "S14's credential is already covered"],
    [checkLine("x", 1, "GADGET_API_KEY=gsk-live-9Xy8Zt7Qw6Rv5Nm4"), true, "S27's Gadget key is covered"],
    [checkLine("x", 1, "# COMPOSIO_API_KEY=  # secret; set in the deployment"), false, "empty assignment is fine"],
    [checkLine("x", 1, "COMPOSIO_API_KEY=<your-key>"), false, "placeholder is fine"],
    [checkLine("x", 1, "COMPOSIO_API_KEY=composio-api-key:latest"), false, "Secret Manager ref is fine"],
    [
      checkLine("x", 1, '--set-secrets="SIMPLETEXTING_API_TOKEN=simpletexting-api-token:latest,X=y"'),
      false,
      "a --set-secrets list is refs, not values",
    ],
    [checkLine("x", 1, "HERMES_COPILOT_API_TOKEN=dev-copilot-token"), false, "published dev default is fine"],
    [checkLine("x", 1, "DISPATCH_API_TOKEN: ${HERMES_ADMIN_API_TOKEN:-dev-admin-token}"), false, "interpolation is fine"],
    [checkLine("x", 1, "    INTERNAL_JOB_SECRET: rt.INTERNAL_JOB_SECRET || \"dev\","), false, "code reference is fine"],
    [checkLine("x", 1, 'process.env.WORKBENCH_SESSION_SECRET = "from-env";'), false, "test fixture slug is fine"],
    [checkLine("x", 1, "process.env.WORKBENCH_SESSION_SECRET = SECRET;"), false, "constant reference is fine"],
    [checkLine("x", 1, "the sk- prefix identifies OpenAI keys"), false, "prose is not a token"],
    // Fix wave 1 (review Finding 7): the four shapes the gate used to wave through.
    [
      checkLine("x", 1, '  "COMPOSIO_API_KEY": "zz9realvaluepastedhere",'),
      true,
      "quoted/JSON key is still a secret assignment",
    ],
    [
      checkLine("x", 1, 'composio_api_key = "zz9realvaluepastedhere"'),
      true,
      "lowercase variable name is still a secret assignment",
    ],
    [
      checkLine("x", 1, "COMPOSIO_API_KEY=zzrealvaluepastedhereandhere"),
      true,
      "an all-lowercase value past the length cap is not a slug",
    ],
    [
      checkLine("x", 1, "COMPOSIO_API_KEY=AB12CD34EF56GH78IJ90KL12MN34OP56"),
      true,
      "an all-caps value past the length cap is not a constant reference",
    ],
    [
      checkLine("x", 1, '  headers: { authorization: "Bearer a1b2c3d4e5f6g7h8i9j0k1l2" },'),
      true,
      "a bare bearer token in a fixture has no variable name to key on",
    ],
    [
      checkLine("x", 1, "  -H 'authorization: Bearer dev-copilot-token' \\"),
      false,
      "the published dev bearer default is below the length floor",
    ],
    // Fix wave 2: the SCREAMING_CASE cap narrowed to 24 (fix wave 1) created a
    // false-positive class on long, obvious placeholders. These prove the
    // placeholder allowlist clears them without reopening the real-token shape.
    [
      checkLine("x", 1, "WORKBENCH_SESSION_SECRET=CHANGE_ME_BEFORE_DEPLOY_PLEASE"),
      false,
      "a CHANGE_ME placeholder past the 24-char cap is still clean",
    ],
    [
      checkLine("x", 1, "COMPOSIO_API_KEY=YOUR_API_KEY_HERE"),
      false,
      "a YOUR_..._HERE placeholder is clean",
    ],
    [
      checkLine("x", 1, "COMPOSIO_API_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
      false,
      "an XXXX redaction placeholder is clean",
    ],
    [
      checkLine("x", 1, "WORKBENCH_SESSION_SECRET=ZZ99YY88XX77WW66VV55UU44TT33SS22"),
      true,
      "a real-looking all-caps token past the cap is still caught -- placeholder allowlist did not reopen it",
    ],
  ];
  let failed = 0;
  for (const [result, shouldFind, label] of cases) {
    const found = result !== null;
    if (found !== shouldFind) {
      console.error(`[secret-scan] SELFCHECK FAIL: ${label} (got ${found ? "finding" : "clean"})`);
      failed += 1;
    }
  }
  if (failed) return 1;
  console.log(`[secret-scan] selfcheck ok (${cases.length} cases)`);
  return 0;
}

function main() {
  if (process.argv.includes("--selfcheck")) return selfcheck();
  const findings = scan();
  if (!findings.length) {
    console.log("[secret-scan] clean -- no credential found in tracked files");
    return 0;
  }
  for (const f of findings) {
    const where = f.line ? `${f.file}:${f.line}` : f.file;
    console.error(`::error file=${f.file},line=${f.line || 1}::[${f.rule}] ${where} -- ${f.detail}`);
  }
  console.error(
    `\n[secret-scan] ${findings.length} finding(s). If a value is real: ROTATE IT at the provider,` +
      " then remove it from the tree (env var only, NFR-6). If it is a placeholder, widen" +
      " NOT_A_SECRET in scripts/secret-scan.mjs and say why.",
  );
  return 1;
}

process.exit(main());
