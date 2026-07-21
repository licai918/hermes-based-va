-- Provisions the separate toee_knowledge database (S-ISO isolation, PRD §7.4)
-- alongside the POSTGRES_DB-provisioned toee_va. Postgres only runs
-- docker-entrypoint-initdb.d scripts on first init of an EMPTY data volume --
-- an existing toee_pgdata volume from before this script existed will NOT get
-- toee_knowledge from this file. hermes_runtime.knowledge.migrate.ensure_database
-- covers that case (and fresh CI Postgres, which doesn't mount this at all) by
-- creating the database itself before running migrations.
SELECT 'CREATE DATABASE toee_knowledge OWNER toee'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'toee_knowledge')\gexec
