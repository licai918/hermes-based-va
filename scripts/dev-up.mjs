#!/usr/bin/env node
// One-command local dev stack (0.0.4 S10, FR-5/NFR-5).
//
//   pnpm dev                 full stack + workbench dev server (foreground)
//   pnpm dev -- --stack-only everything except the workbench dev server
//
// Node, not PowerShell + a parallel .sh, because Node is already a hard
// prerequisite (pnpm) and one file works in PowerShell, Git Bash and CI alike.
//
// Everything except the workbench runs in docker compose; the workbench dev
// server runs on the host, where its node_modules and hot reload already live.
//
// This waits on REAL readiness (pg_isready, then /healthz per server), because a
// `docker compose up` that returns before Postgres accepts connections is exactly
// the confusing half-started stack this script exists to remove.

import assert from "node:assert/strict";
import { spawnSync, spawn } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const WORKBENCH_ENV = join(ROOT, "apps", "workbench", ".env.local");
const RUNTIME_ENV = join(ROOT, "hermes-runtime", ".env");
const STACK_ONLY = process.argv.includes("--stack-only");

// Dispatch ports. 8091/8092 (not the 8081/8082 the pre-S10 runbooks used by
// hand) so a stale hand-started server does not silently answer for the composed
// one -- if one is still bound here, compose fails with "port is already
// allocated" and step() prints how to stop it.
const PORTS = { copilot: 8091, admin: 8092, gateway: 8080, workbench: 3000 };

const log = (msg) => console.log(`\n[dev-up] ${msg}`);
const die = (msg) => {
  console.error(`\n[dev-up] ${msg}\n`);
  process.exit(1);
};

/** Parse a KEY=VALUE .env file. Missing file -> {}. */
function readEnvFile(path) {
  if (!existsSync(path)) return {};
  const out = {};
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq < 1) continue;
    out[trimmed.slice(0, eq).trim()] = trimmed
      .slice(eq + 1)
      .trim()
      .replace(/^["']|["']$/g, "");
  }
  return out;
}

function run(cmd, args, opts = {}) {
  return spawnSync(cmd, args, { cwd: ROOT, stdio: "inherit", shell: false, ...opts });
}

// ---------------------------------------------------------------------------
// 0. Docker preflight
// ---------------------------------------------------------------------------
// Two failure modes account for essentially every "dev up doesn't work" on this
// repo's Windows box: Docker Desktop is not running, or a stale user-level
// DOCKER_HOST=tcp://localhost:2375 points the CLI at a daemon that isn't there.
// The second one is self-inflicted and invisible, so clear it rather than making
// the reader diagnose a `dial tcp [::1]:2375` error.
function dockerPreflight() {
  const ping = () =>
    spawnSync("docker", ["version", "--format", "{{.Server.Version}}"], {
      cwd: ROOT,
      encoding: "utf8",
    });
  let probe = ping();
  if (probe.status !== 0 && process.env.DOCKER_HOST) {
    log(`DOCKER_HOST=${process.env.DOCKER_HOST} is unreachable; ignoring it (Docker Desktop uses the default named pipe).`);
    delete process.env.DOCKER_HOST;
    probe = ping();
  }
  if (probe.status !== 0) {
    die(
      "Docker is not reachable. Start Docker Desktop and re-run `pnpm dev`.\n" +
        `        docker said: ${(probe.stderr || probe.error?.message || "").trim().split("\n")[0]}`,
    );
  }
  log(`docker engine ${probe.stdout.trim()}`);
}

// ---------------------------------------------------------------------------
// 1. Dev env files
// ---------------------------------------------------------------------------
// apps/workbench/.env.local is the source of truth for the four HERMES_* pairs:
// the workbench reads it directly (0.0.4 S09 -- it refuses to boot without them),
// and compose reads the same values back out through this script, so the BFF's
// bearer and the dispatch server's DISPATCH_API_TOKEN cannot drift apart.
const WORKBENCH_ENV_TEMPLATE = `# Local dev workbench env (gitignored). Written by scripts/dev-up.mjs.
# The workbench is API-only (0.0.4 S09): all four HERMES_* values are REQUIRED and
# it refuses to boot without them. Each *_API_TOKEN must equal the matching
# dispatch server's DISPATCH_API_TOKEN -- \`pnpm dev\` reads them from here and
# passes them to docker compose, so edit them here and nowhere else.
WORKBENCH_SESSION_SECRET=workbench-dev-session-secret-change-me

HERMES_COPILOT_API_URL=http://127.0.0.1:${PORTS.copilot}
HERMES_COPILOT_API_TOKEN=dev-copilot-token
HERMES_ADMIN_API_URL=http://127.0.0.1:${PORTS.admin}
HERMES_ADMIN_API_TOKEN=dev-admin-token

# External Profile Simulator -> the real gateway webhook (no bypass chat).
# TEXTLINE_WEBHOOK_SECRET must equal the gateway's; \`pnpm dev\` passes this value on.
SIMULATOR_GATEWAY_URL=http://127.0.0.1:${PORTS.gateway}
TEXTLINE_WEBHOOK_SECRET=dev-webhook-secret
`;

function resolveDevEnv() {
  if (!existsSync(WORKBENCH_ENV)) {
    writeFileSync(WORKBENCH_ENV, WORKBENCH_ENV_TEMPLATE, "utf8");
    log(`wrote apps/workbench/.env.local (dev defaults)`);
  }
  const wb = readEnvFile(WORKBENCH_ENV);
  const rt = readEnvFile(RUNTIME_ENV);

  const missing = ["HERMES_COPILOT_API_URL", "HERMES_COPILOT_API_TOKEN", "HERMES_ADMIN_API_URL", "HERMES_ADMIN_API_TOKEN"].filter(
    (k) => !wb[k],
  );
  if (missing.length) {
    die(
      `apps/workbench/.env.local is missing ${missing.join(", ")}.\n` +
        "        The workbench is API-only (0.0.4 S09) and will not boot without them.\n" +
        "        Delete the file and re-run to regenerate it with dev defaults.",
    );
  }
  for (const [key, port] of [
    ["HERMES_COPILOT_API_URL", PORTS.copilot],
    ["HERMES_ADMIN_API_URL", PORTS.admin],
  ]) {
    if (!wb[key].endsWith(`:${port}`)) {
      log(`WARNING: ${key}=${wb[key]} does not point at the composed server on :${port}. Login/queue reads will miss.`);
    }
  }

  // Exported into compose's interpolation environment. Values already present in
  // hermes-runtime/.env win over the dev defaults so nobody's real secret is
  // clobbered by this script (compose `environment:` beats `env_file:`).
  return {
    HERMES_COPILOT_API_TOKEN: wb.HERMES_COPILOT_API_TOKEN,
    HERMES_ADMIN_API_TOKEN: wb.HERMES_ADMIN_API_TOKEN,
    TEXTLINE_WEBHOOK_SECRET: wb.TEXTLINE_WEBHOOK_SECRET || rt.TEXTLINE_WEBHOOK_SECRET || "dev-webhook-secret",
    INTERNAL_JOB_SECRET: rt.INTERNAL_JOB_SECRET || "dev-internal-job-secret",
    REPLY_SENDER: rt.REPLY_SENDER || "simulated",
  };
}

// ---------------------------------------------------------------------------
// 2. Compose phases
// ---------------------------------------------------------------------------
function compose(args, failHint) {
  const res = run("docker", ["compose", ...args]);
  if (res.status !== 0) die(`\`docker compose ${args.join(" ")}\` failed.\n        ${failHint}`);
}

const STALE_HINT =
  "If it says a port is already allocated, a hand-started server from an earlier\n" +
  "        session still owns it (those predate this stack and can be running older code).\n" +
  "        Find it:  npx kill-port 8080 8091 8092   -- or close that terminal -- then re-run.";

/** Poll an HTTP endpoint until it answers, or give up. */
async function waitForHttp(label, url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        log(`${label} ready (${url})`);
        return;
      }
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) die(`${label} never answered ${url} within ${timeoutMs / 1000}s.`);
    await new Promise((r) => setTimeout(r, 1000));
  }
}

/** The workers serve no HTTP, so their readiness signal is "running, not restarting". */
function assertWorkersRunning() {
  const res = spawnSync("docker", ["compose", "ps", "--format", "{{.Service}}\t{{.State}}"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  const states = Object.fromEntries(
    res.stdout
      .trim()
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => line.split("\t")),
  );
  for (const worker of ["turn-worker", "background-worker"]) {
    if (states[worker] !== "running") {
      die(
        `${worker} is "${states[worker] ?? "absent"}", not running.\n` +
          `        Both workers fail closed without TOOL_BACKEND=datastore -- read the boot error:\n` +
          `        docker compose logs ${worker}`,
      );
    }
  }
  log("turn-worker + background-worker running");
}

// The one runnable check: `node scripts/dev-up.mjs --selfcheck`. Env parsing is the
// only non-obvious logic here, and getting it wrong hands compose a wrong bearer,
// which surfaces three phases later as an opaque 401.
function selfcheck() {
  const tmp = join(process.env.TEMP || process.env.TMPDIR || ".", `dev-up-selfcheck-${process.pid}.env`);
  writeFileSync(
    tmp,
    ["# comment", "", "  A=1  ", 'B="quoted"', "C='single'", "D=has=equals", "E=", "nokey"].join("\n"),
    "utf8",
  );
  const got = readEnvFile(tmp);
  const want = { A: "1", B: "quoted", C: "single", D: "has=equals", E: "" };
  assert.deepStrictEqual(got, want, `readEnvFile mismatch: ${JSON.stringify(got)}`);
  assert.deepStrictEqual(readEnvFile(join(tmp, "does-not-exist")), {}, "missing file must parse to {}");
  rmSync(tmp);
  console.log("[dev-up] selfcheck ok");
}

async function main() {
  if (process.argv.includes("--selfcheck")) return selfcheck();
  dockerPreflight();
  const devEnv = resolveDevEnv();
  Object.assign(process.env, devEnv);

  log("phase 1/4 — Postgres (waits for pg_isready)");
  compose(["up", "-d", "--wait", "postgres"], STALE_HINT);

  log("phase 2/4 — migrations + dev seed (idempotent; safe against a populated DB)");
  compose(
    ["run", "--rm", "--build", "migrate"],
    "Migrations failed. `docker compose logs postgres` and check hermes-runtime/migrations/.",
  );

  log("phase 3/4 — gateway, both dispatch servers, both workers (waits for /healthz)");
  compose(
    ["up", "-d", "--wait", "gateway", "dispatch-copilot", "dispatch-admin", "turn-worker", "background-worker"],
    STALE_HINT,
  );
  await Promise.all([
    waitForHttp("dispatch-copilot", `http://127.0.0.1:${PORTS.copilot}/healthz`),
    waitForHttp("dispatch-admin", `http://127.0.0.1:${PORTS.admin}/healthz`),
    waitForHttp("gateway", `http://127.0.0.1:${PORTS.gateway}/healthz`),
  ]);
  assertWorkersRunning();

  if (STACK_ONLY) {
    log("stack up. --stack-only: skipping the workbench dev server.");
    log("Stop everything with: docker compose down");
    return;
  }

  log(`phase 4/4 — workbench dev server on http://localhost:${PORTS.workbench}`);
  const child = spawn("pnpm", ["--filter", "@toee/workbench", "dev"], {
    cwd: ROOT,
    stdio: "inherit",
    shell: process.platform === "win32", // pnpm is a .cmd shim on Windows
  });
  const stop = () => child.kill();
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);

  await waitForHttp("workbench", `http://127.0.0.1:${PORTS.workbench}/login`, 180_000);
  console.log(
    [
      "",
      "  ================================================================",
      `   Log in at  http://localhost:${PORTS.workbench}/login`,
      "     rep / supervisor / admin      password: Workbench123!",
      "",
      "   Ctrl-C stops the workbench. The containers keep running:",
      "     docker compose ps     docker compose logs -f gateway     docker compose down",
      "  ================================================================",
      "",
    ].join("\n"),
  );
  child.on("exit", (code) => process.exit(code ?? 0));
}

main();
