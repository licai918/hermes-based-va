#!/usr/bin/env node
// CI harness-topology smoke (0.0.4 S25, NFR-9).
//
// Proves the full turn-path topology is wired in CI at the durable-path seam
// that needs NO LLM: POST a tokened inbound webhook to the gateway, then assert
// the gateway fast-acked by writing a `job` row AND the turn-worker claimed it
// (attempts >= 1). Runs the check TWICE with distinct events -- the S25
// determinism/idempotency proof at the topology level.
//
// It deliberately does NOT run a scripted agent turn end-to-end: seeding
// `scripted_completions` into the RUNNING dispatch/turn-worker process (a real
// deterministic turn with no OpenRouter call) is the S18 harness deliverable,
// which runs ON this topology. See .superpowers/sdd/0.0.4-S25-report.md.
//
// `attempts >= 1` is the claim signal: `claim()` increments attempts and never
// decrements, so a claimed job reads >= 1 whether it then succeeds, fails
// (no OpenRouter key -> the turn errors, which is fine -- the CLAIM is the proof
// the worker consumed the gateway's enqueue), retries, or dead-letters. A
// never-claimed job stays status='queued', attempts=0.
//
//   node scripts/ci-harness-smoke.mjs              run the smoke (needs a booted stack)
//   node scripts/ci-harness-smoke.mjs --selfcheck  the one runnable parse check

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const GATEWAY_URL = process.env.GATEWAY_URL || "http://127.0.0.1:8080";
// Must equal the gateway's SIMPLETEXTING_WEBHOOK_TOKEN (dev-up's default), or the
// webhook 401s. CI exports the same default; override via env to match a real one.
const WEBHOOK_TOKEN = process.env.SIMPLETEXTING_WEBHOOK_TOKEN || "dev-webhook-token";
// The seeded mock customer number (see scripts/dev-up.mjs). Identity match does
// not gate the enqueue -- an unmatched caller still starts a turn -- but using
// the seeded number keeps the smoke on the ordinary happy path.
const CONTACT_PHONE = "+14165550101";
const CLAIM_TIMEOUT_MS = 45_000;

const log = (msg) => console.log(`[ci-smoke] ${msg}`);

/** `psql -tA` single-row "status|attempts" -> {status, attempts}; ""/no row -> null. */
function parseJobRow(stdout) {
  const line = stdout.trim().split(/\r?\n/)[0]?.trim();
  if (!line) return null;
  const [status, attempts] = line.split("|");
  return { status, attempts: Number.parseInt(attempts, 10) };
}

/** Query the composed Postgres for one agent_turn job by its inbound event id. */
function queryJob(eventId) {
  const res = spawnSync(
    "docker",
    [
      "compose", "exec", "-T", "postgres",
      "psql", "-U", "toee", "-d", "toee_va", "-tAc",
      `SELECT status, attempts FROM job WHERE type = 'agent_turn' AND payload->>'event_id' = '${eventId}'`,
    ],
    { cwd: ROOT, encoding: "utf8" },
  );
  if (res.status !== 0) {
    throw new Error(`psql query failed: ${(res.stderr || res.error?.message || "").trim()}`);
  }
  return parseJobRow(res.stdout);
}

async function postInbound(eventId) {
  const body = {
    type: "INCOMING_MESSAGE",
    reportId: eventId,
    webhookId: "ci-harness-smoke",
    values: {
      messageId: eventId,
      text: "CI harness-topology smoke -- please ignore.",
      accountPhone: "+15005550000",
      contactPhone: CONTACT_PHONE,
      timestamp: new Date().toISOString(),
    },
  };
  const url = `${GATEWAY_URL}/webhooks/simpletexting?token=${encodeURIComponent(WEBHOOK_TOKEN)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  });
  if (res.status !== 200) {
    throw new Error(`gateway webhook returned ${res.status} (expected 200 fast-ack); token/health?`);
  }
}

/** One liveness pass: inbound webhook -> job row enqueued -> turn-worker claims it. */
async function livenessCheck(label) {
  const eventId = `ci-smoke-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  log(`${label}: POST inbound event ${eventId}`);
  await postInbound(eventId);

  const deadline = Date.now() + CLAIM_TIMEOUT_MS;
  for (;;) {
    const job = queryJob(eventId);
    if (job && job.attempts >= 1) {
      log(`${label}: job ${eventId} claimed (status=${job.status}, attempts=${job.attempts})`);
      return;
    }
    if (Date.now() > deadline) {
      const state = job ? `status=${job.status}, attempts=${job.attempts}` : "no job row";
      throw new Error(
        `${label}: job for ${eventId} was never claimed within ${CLAIM_TIMEOUT_MS / 1000}s (${state}). ` +
          "Gateway enqueue or turn-worker claim path is broken.",
      );
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

function selfcheck() {
  assert.deepStrictEqual(parseJobRow("running|1"), { status: "running", attempts: 1 });
  assert.deepStrictEqual(parseJobRow("succeeded|2\n"), { status: "succeeded", attempts: 2 });
  assert.deepStrictEqual(parseJobRow("queued|0"), { status: "queued", attempts: 0 });
  assert.deepStrictEqual(parseJobRow(""), null, "empty (no row) -> null");
  assert.deepStrictEqual(parseJobRow("  \n"), null, "whitespace-only -> null");
  console.log("[ci-smoke] selfcheck ok");
}

async function main() {
  if (process.argv.includes("--selfcheck")) return selfcheck();
  // Twice consecutively -- the S25 determinism/idempotency proof at the topology
  // level. The scenario-level scripted-harness determinism proof is S18's.
  await livenessCheck("pass 1/2");
  await livenessCheck("pass 2/2");
  log("topology smoke green twice — gateway enqueue + turn-worker claim proven.");
}

main().catch((err) => {
  console.error(`[ci-smoke] FAILED: ${err.message}`);
  process.exit(1);
});
