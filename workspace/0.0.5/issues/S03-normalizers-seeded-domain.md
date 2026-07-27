# S03 — In-code normalizers + seeded domain #1 (tire / company / season)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** S01
- **Delivers:** FR-2
- **Surface:** pure normalizer functions (dependency-free package); seed entries; season rule

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D1** — this slice's seed migration is allocated prefix **0024** (the 0.0.5 floor is 0020,
  with 0021-0023 already spoken for by S09/S15/S18). Re-verify by listing the migrations
  directory before writing yours; if reality has moved past this number, take the next free one
  and say so in the report.

## Goal

FR-2: the three entry kinds become real — `alias` rows, `normalizer` code toggled per domain,
structured `default_rule` rows — seeded with domain #1: the tire-size parser
(`2055516|205 55 16|20555r16 → 205/55R16`), company aliases (TOEE ≡ TOEE TIRE), and the season
default (date-derived + admin-overridable rule row; grill-locked). US2/US3.

## Approach

- `parse_tire_size()` as a pure function beside `normalize_e164`/`canonicalize_email` (same
  discipline, dependency-free); regex lives in CODE — the table stores only enable/params
  (admin-editable regex is rejected, PRD §6).
- `default_rule` structured fields: condition (season=…, date-derived via a `current_season()`
  pure function) → default → confirm:required; an admin-set override row wins over the
  date-derived default.
- Seed via the governed manual-add path (S02) or a seed migration — seeded entries
  provenance=admin_manual, audited.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit — all three notations parse to the same TireSize; invalid strings
  rejected (no false positives on order numbers/phones); `current_season` deterministic given
  a date; seeded rows present + confirmed; toggle-off disables a normalizer for a domain.
- **② E2E (browser):** seeded aliases visible in the console; screenshot.
- **③ Product (PAC):** feeds PAC-1 (full path proven at S05/S06).

## Out of scope

- Applying normalizers to tool params — **S05**. Rendering defaults/confirm phrasing — **S06**.
