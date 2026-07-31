-- 0025_proposal_annotations
-- D8's shared annotation column, on the two PROPOSAL tables (0.0.5 S13, FR-18).
--
-- WHY THIS IS NOT ALREADY DONE, since 0022 looks like it did it. S15 shipped
-- `review_item.annotations` with that table, because S16 annotates graduation /
-- blast-radius / persona-review items and those live only there. It did NOT
-- reach the two tables that hold the OTHER four inbox kinds: an l6_proposal is
-- an `agent_experience` row and an l7_proposal is a `semantic_lexicon` row, and
-- neither had anywhere to put an advisory. D1's 0025 allocation is therefore
-- still live and covers exactly the gap 0022 left -- verified against the
-- directory at land time, not assumed from the table.
--
-- ONE column, TWO reserved top-level keys, spelled the same on all three tables:
--
--   heuristic   S13's write-time advisories (FR-18) -- "looks lexicon-shaped,
--               consider re-filing to L7", "this surface is already confirmed
--               in L7", "a confirmed L6 note already says this".
--   copilot     S16's LLM triage annotations (FR-23), landing later.
--
-- Each writer assigns its own WHOLE key and never reads or writes the other's,
-- so the two slices cannot lost-update each other on one row and the UI can
-- render them as visually distinct blocks (it already does -- the inbox's
-- annotation render shipped with S15 and reads `annotations` straight off the
-- raw proposal row).
--
-- ADVISORY ONLY (NFR-3). Nothing in this column decides anything. A proposal
-- persists identically whether it is annotated or not; the annotation is read by
-- a human who re-files with S15's Re-classify. Nothing here is ever consulted by
-- the deterministic seam, the prompt glossary, or any gate.
--
-- NOT NULL DEFAULT '{}' rather than nullable, matching 0022: "no advisories" is
-- an empty object, so every reader can index into it without a null branch, and
-- the backfill of existing rows is the default itself.
ALTER TABLE agent_experience
    ADD COLUMN annotations JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE semantic_lexicon
    ADD COLUMN annotations JSONB NOT NULL DEFAULT '{}'::jsonb;
