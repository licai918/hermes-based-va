-- 0032 -- the seeded non-winter seasonal default must not say "all-season tires".
--
-- FOUND BY LOOKING AT THE CONSOLE during the 0.0.5 sign-off walkthrough, not by a
-- test. /admin/lexicon showed:
--
--     tire | default_rule | season=all_season | all-season tires | confirmed
--
-- `canonical_form` is what hooks._default_rule_line renders into an imperative ASK,
-- so it is customer-facing wording -- and the business will not say that phrase in
-- this market: "加拿大冬天雪特别厚，我们不会称之为 ALL SEASON，避免出现 misleading
-- information". Where winter capability is a safety question, "all-season" reads as
-- a claim the product does not support. 0.0.6's D1 records the approved outward
-- label for the class: PASSENGER -> "passenger tires", never "all-season tires".
--
-- WHY THIS IS A NEW MIGRATION AND NOT AN EDIT TO 0024. `schema_migrations` skips
-- versions it has already applied, so editing 0024 would change what a FRESH
-- database gets while silently leaving every already-migrated one alone -- the exact
-- drift D1's note on 0031 describes. It is also above the highest applied version,
-- which is what the out-of-order guard in datastore/migrate.py requires.
--
-- Scoped to the seeded row by id. An admin who has since edited that row on purpose
-- keeps their wording: the WHERE clause matches the phrase this migration exists to
-- remove, so a row already carrying something else is left untouched.
UPDATE semantic_lexicon
SET
    canonical_form = 'passenger tires',
    evidence = 'Outside the winter window a bare tire size means the passenger class. Same confirm-first rule as the winter row: a default is a question. The wording is the business''s approved label for the class -- the phrase ''all-season'' is not used with customers in this market, because where winter capability is a safety question it reads as a claim the product does not support.',
    updated_at = now()
WHERE id = 'seed_lex_season_all_season'
  AND canonical_form = 'all-season tires';

-- NOT changed here, and deliberately: the condition token. _default_rule_line also
-- prints `Seasonal default (tire, all_season): ...`, so `all_season` still reaches
-- the prompt as the name of the WINDOW the rule applies in rather than as a product
-- label. Renaming the condition vocabulary means deciding what the facet values are
-- called, which is 0.0.6 D1's spec-layer work (customer wording IN, one approved
-- label OUT). Recorded rather than half-done.
