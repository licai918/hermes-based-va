-- 0024_lexicon_seed_domain_1
-- L7 seeded domain #1 (0.0.5 S03, FR-2). The first real domain language in
-- semantic_lexicon, so the iteration's headline behaviours stop riding on model
-- guesswork: a customer texting 2055516 / 205 55 16 / 20555r16 reaches ONE
-- product, TOEE resolves to TOEE TIRE, and in winter a bare size implies winter
-- tires -- after the agent asks.
--
-- SINGLE SOURCE OF TRUTH: hermes/toee_hermes/lexicon.py :: LEXICON_SEED_ENTRIES.
-- This file is its transcription; tests/test_datastore_lexicon_seed.py compares
-- every column against that constant, so the two cannot drift apart silently.
--
-- The three entry kinds, graded by how much determinism each deserves (FR-2):
--
--   alias        pure data -- an exact surface -> canonical mapping over a
--                finite vocabulary. An admin adds one from the console, no
--                deploy, because the worst a bad row does is map one string to
--                another.
--   normalizer   the REGEX LIVES IN CODE (toee_hermes.lexicon.parse_tire_size).
--                This row is only the per-domain TOGGLE, and the toggle is the
--                `status` column the schema already has -- no enable/params
--                columns were added (the table's shape is another slice's).
--                Admin-editable regex is rejected for 0.0.5 (PRD 6): a bad
--                pattern typed into a console is a production incident with no
--                review step, and the mapping is infinite anyway.
--   default_rule a structured condition -> default -> CONFIRM. surface_form is
--                the condition (`season=winter`), canonical_form the default.
--                Resolution is date-derived (current_season) and an admin pins
--                it by adding a confirmed `season=override` row; either way the
--                result always carries confirm_required, so a customer who
--                wanted all-seasons can never be quoted winters silently.
--
-- 205 55 16 is the flagship, and it is the string that nearly broke 0.0.5: it
-- matches the write scanner's _PHONE_RE. D2 split scan_injection from scan_pii
-- so a surface form gets the injection leg only -- test_datastore_lexicon_seed
-- pushes every row below through the real governed write path to prove it.
--
-- status/provenance: these rows are the owner's CURATED vocabulary, not a
-- proposal, so they land `confirmed` + `admin_manual` -- S05/S06 read confirmed
-- rows only, and a proposed seed would be invisible to them.
--
-- AUDIT: this migration deliberately writes NO workbench_audit_log row. An
-- audit row records an in-app actor's decision and a migration has no actor;
-- per D14 a deploy-time change is audited by git history, which is exactly what
-- this file is. `decider_account_id` therefore names the commit rather than
-- being left NULL -- an unattributed admin_manual row is the unfalsifiable
-- provenance D20 exists to prevent.
--
-- Idempotent (ON CONFLICT DO NOTHING) so a renumber or a re-execution cannot
-- abort a migrate, matching 0005's discipline.

INSERT INTO semantic_lexicon
    (id, domain, entry_kind, surface_form, canonical_form, status, provenance,
     evidence, proposer_context, pii_redacted, decider_account_id, decided_at)
VALUES
    (
        'seed_lex_tire_size',
        'tire',
        'normalizer',
        '205 55 16',
        '205/55R16',
        'confirmed',
        'admin_manual',
        'Toggle row for the in-code tire-size normalizer (parse_tire_size). The pattern lives in code, never in this row; retiring this entry switches tire-size normalization off for the whole tire domain. The forms are the canonical exemplar: 205 55 16, 2055516 and 20555r16 all parse to 205/55R16.',
        '{}'::jsonb,
        false,
        'seed:0024_lexicon_seed_domain_1',
        now()
    ),
    (
        'seed_lex_company_toee',
        'company',
        'alias',
        'TOEE',
        'TOEE TIRE',
        'confirmed',
        'admin_manual',
        'Customers write TOEE for TOEE TIRE. An exact mapping over a finite vocabulary, so it is data an admin adds from the console with no deploy -- the reason alias is the least deterministic-privileged of the three kinds.',
        '{}'::jsonb,
        false,
        'seed:0024_lexicon_seed_domain_1',
        now()
    ),
    (
        'seed_lex_season_winter',
        'tire',
        'default_rule',
        'season=winter',
        'winter tires',
        'confirmed',
        'admin_manual',
        'In the winter window a bare tire size means winter tires. The condition is date-derived by current_season(); an admin pins it by adding a confirmed season=override row. The agent must ASK before quoting -- this rule proposes, it never assumes.',
        '{}'::jsonb,
        false,
        'seed:0024_lexicon_seed_domain_1',
        now()
    ),
    (
        'seed_lex_season_all_season',
        'tire',
        'default_rule',
        'season=all_season',
        'all-season tires',
        'confirmed',
        'admin_manual',
        'Outside the winter window a bare tire size means all-season tires. Same confirm-first rule as the winter row: a default is a question.',
        '{}'::jsonb,
        false,
        'seed:0024_lexicon_seed_domain_1',
        now()
    )
ON CONFLICT (domain, surface_form) DO NOTHING;
