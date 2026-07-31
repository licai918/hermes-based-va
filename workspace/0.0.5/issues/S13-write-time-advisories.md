# S13 — Write-time advisories: lexicon-shape re-file annotation + cross-layer dedup

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T3 Boundary enforcement
- **Size:** S
- **Depends on:** S01
- **Delivers:** FR-18
- **Surface:** both propose handlers (annotation fields only)

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D8** — the Approach line below ("decide at implementation... declaring no migration") is
  corrected: this slice DOES ship a migration. Declare ONE `annotations` JSONB column on the
  proposal row with two reserved top-level keys, `heuristic` (yours) and `copilot` (S16's,
  landing later). Write only your own `heuristic` key — never touch `copilot` — so the two
  slices never lost-update each other's advisories on the same row.
- **D1** — the `annotations` column migration is allocated prefix **0025**. Re-verify by
  listing the migrations directory before writing yours.

## Goal

Tier-3 enforcement (C4; owner decision ③ — **annotate-only**): `propose_experience` runs a
deterministic "is this lexicon-shaped?" heuristic (looks like `A = B` / `A means B`) and
annotates "consider re-filing to L7" — never auto-reroutes; both propose handlers annotate
cross-layer duplicates (same surface exists in L7 / similar L6 note) at propose time. The
human re-files via S15's Re-classify.

## Approach

- Cheap regex/shape heuristic (no LLM) in a shared helper; annotation stored on the proposal
  row (a `advisory` JSONB field or sibling — smallest schema touch, decide at implementation).
- Dedup check: exact surface match against confirmed L7 + trigram-ish similarity against
  confirmed L6 (keep it deterministic and cheap; no embeddings).
- Annotations are advisory metadata — NEVER block a propose, NEVER mutate content (NFR-3).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit — "2055516 means 205/55R16" as an L6 proposal gets the re-file
  annotation; a duplicate surface gets the dup annotation; a plain procedure note gets
  neither; proposals persist regardless of annotations.
- **② E2E (browser):** the annotations render on queue items (interim: console; full render at
  S15/S16); screenshot.
- **③ Product (PAC):** feeds PAC-5.

## Out of scope

- LLM triage annotations — **S16**. Re-classify action — **S15**. Graduation sweep — **S20**.
