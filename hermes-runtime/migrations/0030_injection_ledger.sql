-- 0030_injection_ledger
-- Injection provenance ledger (0.0.5 S09, FR-11; prefix 0030 per DECISIONS D1 --
-- moved from 0021, which S21 reached first).
--
-- Every governed turn may inject remembered content into the prompt: L4 customer
-- memory slots, L6 confirmed agent-experience notes, and (when S06 lands) L7
-- lexicon entries. The system already COUNTS that injections happened; nothing
-- records WHICH entries went into WHICH turn. This table is that record, and it
-- is two locators at once:
--
--   * blast radius (S10)      -- retire a wrong entry, list the cases it touched:
--                                WHERE layer = ? AND entry_ref = ?
--   * effectiveness (S26)     -- attribute a judge score to the entries that were
--                                actually in that turn's prompt: WHERE turn_ref = ?
--
-- **The grain is the point.** ONE row per (turn, layer, entry) -- stated as the
-- primary key rather than as a comment, so the turn x layer x entry join both
-- slices need cannot be built on sand. No surrogate id: the natural triple IS
-- the identity, and this table gains rows every turn, so a second key and its
-- index would be pure overhead.
--
-- **entry_ref is a STABLE NATURAL KEY, never a row id (D4.3):**
--   l4  -> binding_key || ':' || slot_name  (customer_memory_slot's own
--          UNIQUE(binding_key, slot_name))
--   l6  -> agent_experience.id
--   l7  -> semantic_lexicon.id  (additive when S06 renders the block)
-- The cross-channel merge path (merge_provisional_memory) DELETEs and re-INSERTs
-- L4 rows with FRESH ids, so a row id would silently orphan S10's join and S26's
-- per-entry score -- later, in someone else's slice, with no obvious cause.
--
-- **No memory VALUES here (NFR-6).** Ids and slot NAMES only. The content lives
-- in the layer that owns it; copying it would create a second, ungoverned copy
-- of customer PII outside that layer.
--
-- **Retention.** The table grows every turn, so S09 also ships a windowed prune
-- job (hermes_runtime.injection_ledger, on the 0.0.4 S04 schedule tick). Its
-- window is a named constant coupled to S20's zero-hit window by an asserted
-- test (D12): prune_window >= zero_hit_window, or garbage collection quietly
-- manufactures retirement candidates for entries that are actively in use.
CREATE TABLE injection_ledger (
    turn_ref            TEXT NOT NULL,
    layer               TEXT NOT NULL,
    entry_ref           TEXT NOT NULL,
    -- The customer/case this turn was about: the L4 binding key on the external
    -- turn, the case id on the copilot draft turn. Nullable: an L6/L7-only
    -- injection on an unbound turn has neither.
    case_or_binding_ref TEXT,
    injected_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (turn_ref, layer, entry_ref)
);

-- S10's direction: given ONE entry, every turn/case it reached, newest first.
-- The PK covers the turn direction; this covers the entry direction.
CREATE INDEX injection_ledger_entry_idx
    ON injection_ledger (layer, entry_ref, injected_at DESC);

-- The prune job's windowed DELETE.
CREATE INDEX injection_ledger_injected_at_idx ON injection_ledger (injected_at);
