import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// Pin the workspace root: stray lockfiles elsewhere on disk otherwise confuse
// Next's root inference (Turbopack file tracing / dev watch).
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const nextConfig: NextConfig = {
  turbopack: { root: repoRoot },
  transpilePackages: [
    "@toee/shared",
    "@toee/hermes-runtime",
    "@toee/domain-adapters",
  ],
};

export default nextConfig;
