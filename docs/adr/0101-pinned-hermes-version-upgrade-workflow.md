# Pinned Hermes versions with eval-gated upgrade workflow

> **Refined by ADR-0139.** The pin-and-eval-gate workflow holds, but the pinned
> artifact is the upstream Python package at an exact git rev
> (`hermes-agent @ git+...@<rev>`, managed by `uv`), not an npm semver.

Official Hermes package versions are pinned to exact semver releases in package manifests. The repo does not use caret or tilde ranges for official Hermes dependencies in v1.

## Version pinning rule

- official Hermes packages are pinned exactly, for example `1.4.2`, not `^1.4.2`
- the primary pin lives in `packages/hermes-runtime`
- `apps/workbench` and `services/hermes-gateway` inherit Hermes functionality through `packages/hermes-runtime`, not direct Hermes dependency drift

## Upgrade workflow

A Hermes version upgrade happens only through a pull request with this sequence:

1. bump the pinned official Hermes version
2. update `packages/hermes-runtime` and any affected `packages/domain-adapters` for public API changes
3. run `typecheck`, tests, and the required **Launch Eval Gate** suites
4. deploy `toee-hermes-workbench` and `toee-hermes-gateway` to staging
5. perform supervisor or admin smoke checks for Copilot login, Textline webhook ingress, and governance reads
6. promote production only after staging verification succeeds

If the upgrade changes integration boundaries or requires non-trivial adapter rewrites, add or update an ADR.

## Promotion authority

**Workbench Admin** users own production promotion of Hermes runtime upgrades. **Customer Service Rep** users do not change runtime dependency versions.

Eval reports must record the deployed Hermes package version alongside model, prompt, and knowledge metadata for audit.

**Considered options:** caret-based automatic minor upgrades (rejected—silent behavior drift across environments); production upgrade without eval or staging (rejected—conflicts with launch and publish gates); let any employee promote runtime upgrades (rejected—governance and blast-radius risk).
