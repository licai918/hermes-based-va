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
  "INTERNAL_JOB_SECRET",
  "DISPATCH_API_TOKEN",
  "HERMES_COPILOT_API_TOKEN",
  "HERMES_ADMIN_API_TOKEN",
  "HERMES_EXTERNAL_SIM_TOKEN",
  "WORKBENCH_SESSION_SECRET",
  "NGROK_AUTHTOKEN",
];

// Values that are not credentials. The load-bearing one is the LAST: a value
// made only of lowercase letters and dashes is a human-written slug
// ("dev-webhook-token", "copilot-tok", "from-env"), not a credential -- every
// provider's tokens carry digits, mixed case, or underscores. That single rule
// clears the test fixtures and published dev defaults this repo is full of,
// while "zz9realvaluepastedhere" still trips.
const NOT_A_SECRET = [
  /^$/,
  /^<.*>$/, //          <your-token>
  /\.{3}/, //           ca_..., sk-or-...
  /^\$\{?[A-Za-z_]/, // ${VAR} / $VAR interpolation
  /^-/, //              ${VAR:-default} shell substitution
  /^[A-Za-z_$][\w$]*\./, // code reference: rt.INTERNAL_JOB_SECRET, webhookToken.value
  /^[A-Z_][A-Z0-9_]{0,39}$/, // SCREAMING_CASE constant reference: `= SECRET`
  /^[a-z0-9-]+:(latest|\d+)$/, // Secret Manager ref: composio-api-key:latest
  /^[a-z][a-z-]{0,39}$/, // slug-shaped -> human-written, not a token
];

// The value stops at whitespace, a comment, or the punctuation that ends a
// literal in .env / YAML / JS / shell -- otherwise a `--set-secrets="A=x,B=y"`
// list is captured as one giant "value".
const SECRET_ASSIGNMENT = new RegExp(
  `\\b(${SECRET_VARS.join("|")})\\s*[=:]\\s*["']?([^\\s#,;"'\`)}]*)`,
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
  const assignment = SECRET_ASSIGNMENT.exec(text);
  if (assignment) {
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
