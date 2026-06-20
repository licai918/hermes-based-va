# Hermes native-first boundary for upgrade compatibility

> **Superseded by ADR-0139** (mechanics only). The native-first principle holds,
> but the boundary is the Python `toee_hermes` plugin + profiles against an
> upstream-pinned `hermes-agent`, not an npm `packages/hermes-runtime` wrapping an
> official Node SDK.

Tooe Tire **Hermes VA** should stay upgrade-friendly across official Hermes releases by keeping custom code out of orchestration, memory, and profile enforcement paths.

## Allowed custom layers

Custom code is allowed only in these repo layers:

| Layer | Allowed responsibility |
|-------|------------------------|
| `apps/workbench` | Employee UI, BFF routes, session auth, and workbench workflows |
| `services/hermes-gateway` | Public channel ingress, webhook verification, and event normalization |
| `packages/domain-adapters` | Toee Tire business rules exposed through official Hermes Skills, Tools, and MCP surfaces |
| `packages/hermes-runtime` | Thin bootstrapping over the official Hermes SDK: runtime startup, profile selection, and adapter registration |

`packages/shared` may hold types and constants only. It must not implement agent orchestration or memory behavior.

## Forbidden custom replacements

The repository must not implement its own:

- agent orchestrator or planner loop
- parallel memory store outside **Hermes Native Memory**
- profile allowlist or **Tool Gate** enforcement logic
- copied Hermes built-in tool routing
- forked Hermes Core source maintained inside this repo

When Hermes adds an official capability that overlaps with a local workaround, the local workaround should be removed in favor of the native path.

## Version and upgrade rule

The official Hermes package version is pinned explicitly in package manifests. A Hermes version bump is allowed only after:

1. dependency update in `packages/hermes-runtime` and any affected adapters
2. **Launch Eval Gate** regression for the impacted suites
3. an ADR note or new ADR when the upgrade changes integration boundaries

Patch or minor upgrades with unchanged integration contracts should not require workbench UI changes by default.

## Architectural intent

`apps/workbench` and `services/hermes-gateway` are deployment and ingress boundaries, not second agent cores. Both call the same thin `packages/hermes-runtime` wrapper so Hermes upgrades touch a small, well-defined surface.

**Considered options:** thick `hermes-runtime` that re-implements agent routing and memory adapters (rejected—high upgrade drag); fork Hermes modules into the monorepo (rejected—creates a second core to maintain); upgrade Hermes without eval regression (rejected—silent behavior drift risk).
