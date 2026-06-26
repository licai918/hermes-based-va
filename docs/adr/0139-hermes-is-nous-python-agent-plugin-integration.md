# Hermes is the Nous Research Python agent — integrate via plugin, profiles, and embedding

## Context

Investigation while starting implementation established ground truth that earlier
foundation ADRs got wrong: **Hermes / Hermes Core is Nous Research's
`hermes-agent`** (https://github.com/NousResearch/hermes-agent), a **Python 3.11**
self-improving agent delivered as a CLI, a messaging gateway, and an
OpenAI-compatible **API Server**. Its extension surfaces are Python plugins,
per-profile homes, hooks, Skills, and MCP. **There is no official Node/TypeScript
in-process Hermes SDK** and no npm `@hermes/*` core package to `import` and call
`runProfile()` in a Node process.

This invalidates the embedding premise in ADR-0096, ADR-0099, ADR-0100, and
ADR-0101 (a TypeScript `packages/hermes-runtime` wrapping an "official Hermes
native SDK" pinned as an npm semver). Those parts are **superseded** by this ADR.
The team chose the **Python-native** direction (build on Hermes, not a parallel
core).

## Decision

Integrate with Hermes through its real, supported surfaces:

- **Hermes core stays upstream.** Depend on it as a pinned external package, not a
  vendored fork: `hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git@c253b07`
  (v0.17.0, the rev the v1 contract was verified against) installed with `uv`.
  `hermes update` / re-pinning is the upgrade path (ADR-0101 workflow still
  applies, now against the git rev).
- **Toee business logic is a Hermes plugin** (`toee_hermes`): a `plugin.yaml` +
  `register(ctx)` that registers every `toee_*` **Domain Adapter Tool**
  (ADR-0059/0070 catalog) with JSON-returning handlers, plus a `pre_llm_call`
  hook for identity + Customer Memory injection (see ADR-0140), plus bundled
  **Skills**. Shipped as a pip entry-point package (`hermes_agent.plugins`).
- **Hermes Profiles** (`customer_service_external`, `internal_copilot`,
  `supervisor_admin`) are three Hermes **profiles** (separate `HERMES_HOME`
  homes). Each profile `config.yaml` enables only its **Profile Tool Allowlist**
  toolsets, and its `SOUL.md` carries the response policy.
- **Tool Gate** remains Toee plugin handler code: identity/profile/policy checks
  that return governed `{"error": ...}` JSON before any backend call (ADR-0033,
  ADR-0020). Handlers never raise and never fabricate.
- **Execution paths.** The external channel pipeline embeds Hermes via the Python
  library (`from run_agent import AIAgent; agent.run_conversation(...)`).
  Employee Copilot/Admin surfaces reach Hermes via the per-profile **API Server**
  (OpenAI-compatible HTTP, bearer auth).
- **Import boundary.** Only the Python Hermes-integration layer (the plugin and
  the gateway embedding) may import `hermes_agent` / `run_agent`. `apps/workbench`
  (Next.js) never imports Hermes; it calls the API Server over HTTP. This
  reframes ADR-0100's single-import-boundary rule for a polyglot repo.

ADR-0096 forbade `apps/workbench` → gateway HTTP because both were same-language
in-process Node. With a Python core, cross-language calls require HTTP/IPC, so
workbench ↔ Hermes is HTTP to the per-profile API Server. The intent of ADR-0096
(no extra standalone runtime service, no profile/tool drift) is preserved: Hermes
itself is the runtime, and both surfaces share the one `toee_hermes` plugin and
the three profile definitions.

## Considered options

- **Depend on `hermes-agent` + Toee plugin + profiles (chosen).** Closest to
  native, upstream-updatable, reuses Hermes orchestration/memory/skills.
- **Vendor/fork `hermes-agent` core into this repo (rejected).** Fights
  `hermes update`, large maintenance surface, drifts from upstream.
- **Keep a TypeScript in-process SDK shim (rejected).** No such SDK exists.
- **Expose Toee tools as a TypeScript MCP server (rejected for v1).** Technically
  viable (Hermes consumes MCP), but the team chose Python-native plugins for the
  closest native fit and to keep Tool Gate in one language with the agent.

## Verification

The plugin contract was verified against the installed upstream (v0.17.0,
`c253b07`), not just the docs:

- `register(ctx)` is invoked by the loader as `register_fn(ctx)` with a real
  `hermes_cli.plugins.PluginContext`; `ctx.register_tool(name, toolset, schema,
  handler)` and `ctx.register_hook("pre_llm_call", cb)` match the upstream
  signatures, and `pre_llm_call` is a `VALID_HOOKS` member.
- Tool handlers are `def h(args, **kwargs) -> str`; the registry dispatches them
  as `entry.handler(args, **kwargs)` (params dict positional), and `pre_llm_call`
  callbacks are invoked as `cb(**kwargs)` with their return `{"context": ...}`
  appended to the user turn.
- End-to-end smoke: loading the `toee_hermes` plugin into a real `PluginContext`
  under the external profile registered exactly the 21 allowlisted action-tools
  (supervisor tools excluded), and `registry.dispatch(...)` returned governed
  JSON through registry → handler → `execute_tool` → `MockDriver`.

The probe ran in an isolated throwaway venv; flipping `toee_hermes` to an
installable entry-point package (`hermes_agent.plugins`) for real per-profile
homes lands with the gateway embedding slice.
