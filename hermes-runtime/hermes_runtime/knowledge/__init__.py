"""Knowledge store: schema + migrations + DSN seam for the separate ``toee_knowledge``
Postgres database (FR-1, PRD §7.4). Never the business datastore -- see
``hermes_runtime.datastore`` for that (S-ISO isolation invariant).
"""
