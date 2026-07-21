# knowledge-spike / probe — throwaway spike harness

Reproducible probes for the 0.0.3 knowledge-layer feasibility spike (Path Y = Postgres FTS).
See [../SPIKE-PLAN.md](../SPIKE-PLAN.md) and [../TRACKER.md](../TRACKER.md).

- `corpus.json` — 27 real Toee Tire docs (13 pages, 10 articles, 4 policies) pulled
  **read-only** from the Shopify connector (pages / articles / shopPolicies only; no
  products / orders / PII).
- `ingest.py` — `corpus.json` → chunk (~600 chars) → `knowledge_chunk` in the separate
  `toee_knowledge` DB. TRUNCATEs first (idempotent; keeps the S-QUAL corpus real-only).
- `slat.py` — S-LAT: pads to 1500 chunks, times in-turn FTS (host → `localhost:5432`),
  and tests the driver-side deadline → `found=false`. **Throwaway** (harness + synthetic
  padding); the DSN seam + `knowledge_chunk` schema are the kept part.

## Run
```
PY=../../../../hermes-runtime/.venv/Scripts/python.exe   # has psycopg 3
PYTHONUTF8=1 "$PY" ingest.py     # load real corpus (167 chunks)
PYTHONUTF8=1 "$PY" slat.py       # S-LAT (pads to 1500; re-run ingest.py after to restore clean)
```
Separate knowledge DB (created in the S-ISO scaffold step):
`postgresql://toee:toee@localhost:5432/toee_knowledge`

## Verdicts (2026-07-16)
- **S-ISO ✅** — separate `toee_knowledge` DB; business `toee_va` untouched (16 tables, no leak).
- **S-LAT ✅** — FTS p95=1.40ms @1500 chunks (gate <800ms); 2s query → `found=false` in 201ms.
- **S-QUAL** — staged (167-chunk real corpus loaded); awaits ~30 real questions + gold labels.
