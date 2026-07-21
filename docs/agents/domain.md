# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.
- **`docs/architecture/`** — current-state structural maps (e.g. `memory-layers.md`). They index the ADRs rather than restating them, so read the map first to see which ADRs govern the area.

## Documentation maintenance

Docs rot when the direction changes and nothing forces the doc to change with it. A 2026-07-20
audit found rot from four distinct causes; each now has a trigger. **Triggers are event-driven
because calendar reminders get ignored** — the periodic sweep is only a backstop for what the
triggers miss.

`docs/architecture/*.md` are **living current-state maps** — unlike `docs/adr/` (an append-only
decision log) and `CONTEXT.md` (vocabulary). If a change contradicts what a map says, **the map
is what's wrong**: fix it in the same change rather than leaving both versions standing.

### Triggers — do these in the SAME PR as the change

| When | Do |
| --- | --- |
| An **ADR lands** that changes a layer or component | Update that row in `docs/architecture/*.md` |
| A decision **reverses an earlier decision** | **Retire the superseded doc in the same PR** — the current direction always wins |
| A **term's meaning changes**, or a named mechanism dies | Update `CONTEXT.md` (the definition *and* its `_Avoid_` list) |
| An **iteration closes** | Sweep: mark shipped work shipped in the PRD / slice index, bump `workspace/CURRENT`, add a line to the architecture map's change log |

### Periodic backstop

At **each iteration kickoff**, run a doc-conflict sweep before writing the PRD: grep the docs for
statements that contradict the current architecture map, and retire what you find. It costs
minutes and catches whatever the triggers missed. Note the sweep in that iteration's exploration
doc.

### How to retire a doc — never delete history

A retired doc keeps its content and gains a blockquote immediately under its H1:

> **\<What\> superseded by \<what / when\>.** \<what still holds\> … \<what died\> …
> Current direction → \<link\>

Two rules that make retirement useful instead of destructive:

1. **Name what still holds, first.** Most superseded docs are only *partly* wrong. ADR-0030's
   crawl orchestration died, but its primary decision — integrations via Hermes Tools, not MCP —
   is still load-bearing. Blanket-retiring it would have thrown that away.
2. **Point at the replacement.** A retirement note with no forward link just relocates the
   confusion.

### What NOT to retire

Delivered iteration records (`workspace/<version>/PRD.md`, `UAT-signoff.md`, `issues/`) are
history and should read as history. Leave them alone unless they would mislead someone into
thinking delivered work is still pending.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (most repos):

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence of `CONTEXT-MAP.md` at the root):

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
