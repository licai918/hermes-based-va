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
# SIMPLETEXTING_WEBHOOK_TOKEN must equal the gateway's; \`pnpm dev\` passes this value on.
SIMULATOR_GATEWAY_URL=http://127.0.0.1:${PORTS.gateway}
SIMPLETEXTING_WEBHOOK_TOKEN=dev-webhook-token
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
  const webhookToken = resolveWebhookToken(rt, wb);
  log(
    `SIMPLETEXTING_WEBHOOK_TOKEN resolved from ${webhookToken.source}` +
      (webhookToken.source === "hermes-runtime/.env"
        ? ""
        : " -- set it in hermes-runtime/.env to the token embedded in the registered SimpleTexting webhook URL before pointing ngrok at this gateway, or every inbound is a silent 401."),
  );

  return {
    HERMES_COPILOT_API_TOKEN: wb.HERMES_COPILOT_API_TOKEN,
    HERMES_ADMIN_API_TOKEN: wb.HERMES_ADMIN_API_TOKEN,
    SIMPLETEXTING_WEBHOOK_TOKEN: webhookToken.value,
    INTERNAL_JOB_SECRET: rt.INTERNAL_JOB_SECRET || "dev-internal-job-secret",
    REPLY_SENDER: rt.REPLY_SENDER || "simulated",
  };
}

// SIMPLETEXTING_WEBHOOK_TOKEN must match the token in the webhook URL registered
// with the EXTERNAL provider (SimpleTexting does not sign payloads -- the URL token
// is the whole credential, ADR-0153), so hermes-runtime/.env -- the
// real-credentials file -- wins over the
// workbench's auto-written local-dev default in apps/workbench/.env.local. Same
// precedence as INTERNAL_JOB_SECRET/REPLY_SENDER above (0.0.4 S10 fix wave 1,
// finding 2: the old wb-first order let a real hermes-runtime/.env secret be
// silently shadowed by the dev default, so every real inbound 401'd).
function resolveWebhookToken(rt, wb) {
  if (rt.SIMPLETEXTING_WEBHOOK_TOKEN) return { value: rt.SIMPLETEXTING_WEBHOOK_TOKEN, source: "hermes-runtime/.env" };
  if (wb.SIMPLETEXTING_WEBHOOK_TOKEN) return { value: wb.SIMPLETEXTING_WEBHOOK_TOKEN, source: "apps/workbench/.env.local" };
  return { value: "dev-webhook-token", source: "dev default" };
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

/** `docker compose ps --format {{.Service}}\t{{.State}}` -> { service: state }. */
function parseComposeStates(stdout) {
  return Object.fromEntries(
    stdout
      .trim()
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => line.split("\t")),
  );
}

// Both workers log this line (name differs) the moment main() finishes the slow
// collaborator setup (Postgres connect, embedder warm) and enters its poll loop --
// the first point at which it can actually claim a job. See turn_worker.main() /
// background_worker.main(): "Turn worker %s polling for..." / "Background worker
// %s polling for...".
function hasStartedPolling(logsText) {
  return /polling for/.test(logsText);
}

/**
 * The workers serve no HTTP, so "running" alone is not readiness: `restart:
 * unless-stopped` with no healthcheck means a worker crash-looping on a bad DSN or
 * missing credential is "running" most of the time too, and a worker can be
 * "running" while still inside resolve_turn_collaborators() and not yet consuming
 * anything. This checks three things instead of one: the probe itself succeeded,
 * the container isn't crash-looping (RestartCount > 0), and main() actually
 * reached its poll loop (0.0.4 S10 fix wave 1, finding 1).
 */
async function waitForWorkersReady(timeoutMs = 60_000) {
  const workers = ["turn-worker", "background-worker"];
  const ready = new Set();
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const ps = spawnSync("docker", ["compose", "ps", "--format", "{{.Service}}\t{{.State}}"], {
      cwd: ROOT,
      encoding: "utf8",
    });
    // Finding 4: a probe failure used to surface as "absent, not running", which
    // points the reader at the worker when the problem is `docker compose ps`
    // itself (e.g. Docker Desktop restarting mid-command).
    if (ps.status !== 0) {
      die(
        `\`docker compose ps\` failed: ${(ps.stderr || ps.error?.message || "").trim().split("\n")[0]}\n` +
          "        That is a probe failure, not a signal about turn-worker/background-worker -- re-run once docker responds.",
      );
    }
    const states = parseComposeStates(ps.stdout);
    for (const worker of workers) {
      if (ready.has(worker)) continue;
      const state = states[worker];
      if (state !== "running") {
        die(
          `${worker} is "${state ?? "absent"}", not running.\n` +
            `        Both workers fail closed without TOOL_BACKEND=datastore -- read the boot error:\n` +
            `        docker compose logs ${worker}`,
        );
      }
      const restarts = spawnSync("docker", ["inspect", "-f", "{{.RestartCount}}", `toee-va-${worker}`], {
        encoding: "utf8",
      });
      const restartCount = restarts.status === 0 ? Number.parseInt(restarts.stdout.trim(), 10) : 0;
      if (restartCount > 0) {
        die(
          `${worker} has restarted ${restartCount} time(s) -- it is crash-looping (bad DSN, missing credential, etc.).\n` +
            `        docker compose logs ${worker}`,
        );
      }
      const logs = spawnSync("docker", ["compose", "logs", worker], { cwd: ROOT, encoding: "utf8" });
      if (logs.status === 0 && hasStartedPolling(logs.stdout)) ready.add(worker);
    }
    if (ready.size === workers.length) {
      log("turn-worker + background-worker running and polling");
      return;
    }
    if (Date.now() > deadline) {
      const stuck = workers.filter((w) => !ready.has(w));
      die(
        `${stuck.join(", ")} still "running" but never logged its startup line within ${timeoutMs / 1000}s.\n` +
          `        It may still be inside Postgres connect / embedder warm-up -- check:\n` +
          `        docker compose logs ${stuck[0]}`,
      );
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
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

  // Finding 2: hermes-runtime/.env (the real-credentials file) must win for
  // SIMPLETEXTING_WEBHOOK_TOKEN, not the workbench's auto-written dev default.
  assert.deepStrictEqual(
    resolveWebhookToken({ SIMPLETEXTING_WEBHOOK_TOKEN: "real-provider-token" }, { SIMPLETEXTING_WEBHOOK_TOKEN: "dev-webhook-token" }),
    { value: "real-provider-token", source: "hermes-runtime/.env" },
    "hermes-runtime/.env must win over the workbench dev default",
  );
  assert.deepStrictEqual(
    resolveWebhookToken({}, { SIMPLETEXTING_WEBHOOK_TOKEN: "dev-webhook-token" }),
    { value: "dev-webhook-token", source: "apps/workbench/.env.local" },
    "falls back to the workbench file when hermes-runtime/.env has nothing",
  );
  assert.deepStrictEqual(
    resolveWebhookToken({}, {}),
    { value: "dev-webhook-token", source: "dev default" },
    "falls back to the dev default when neither file has it",
  );

  // Finding 1: readiness parsing the live worker-readiness loop depends on.
  assert.deepStrictEqual(
    parseComposeStates("turn-worker\trunning\nbackground-worker\trestarting\n"),
    { "turn-worker": "running", "background-worker": "restarting" },
    "parseComposeStates mismatch",
  );
  assert.deepStrictEqual(parseComposeStates(""), {}, "parseComposeStates empty -> {}");
  assert.ok(
    hasStartedPolling("2026-01-01 INFO hermes_runtime.turn_worker Turn worker w1 polling for agent_turn jobs every 2.0s"),
    "must recognize turn_worker's startup line",
  );
  assert.ok(
    hasStartedPolling("2026-01-01 INFO hermes_runtime.background_worker Background worker w1 polling for l6_review, retention, ingest jobs every 2.0s (schedules: retention/86400s)"),
    "must recognize background_worker's startup line",
  );
  assert.ok(!hasStartedPolling("2026-01-01 INFO hermes_runtime.turn_worker starting up"), "must not false-positive on unrelated log lines");

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
  await waitForWorkersReady();

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
  // Registered BEFORE the 180s waitForHttp below (finding 7), not after: a
  // workbench that dies at boot should fail immediately, not leave the script
  // polling a dead port for the full timeout.
  let workbenchReady = false;
  child.on("exit", (code) => {
    if (!workbenchReady) die(`workbench dev server exited (code ${code ?? "unknown"}) before it became ready. See the output above.`);
    process.exit(code ?? 0);
  });
  const stop = () => child.kill();
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);

  await waitForHttp("workbench", `http://127.0.0.1:${PORTS.workbench}/login`, 180_000);
  workbenchReady = true;
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
}

main();
