import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// Pin the workspace root: stray lockfiles elsewhere on disk otherwise confuse
// Next's root inference (Turbopack file tracing / dev watch).
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const nextConfig: NextConfig = {
  turbopack: { root: repoRoot },
  // Slim, self-contained server bundle for the Cloud Run image (ADR-0098, #33).
  // outputFileTracingRoot pins tracing to the monorepo root so the standalone
  // tree preserves the workspace layout — the server is emitted at
  // .next/standalone/apps/workbench/server.js (see apps/workbench/Dockerfile).
  output: "standalone",
  outputFileTracingRoot: repoRoot,
  transpilePackages: ["@toee/shared"],
};

export default nextConfig;
