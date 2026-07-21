"""S-LAT spike: in-turn FTS latency @ projected corpus size + driver-side deadline.
Client-side timing from the host -> localhost:5432 (mirrors how the runtime driver connects).
Throwaway. Pads the table with synthetic rows to a projected size so p95 is meaningful;
re-run ingest.py afterwards to restore a real-only corpus for S-QUAL."""
import time, psycopg

DSN = "postgresql://toee:toee@localhost:5432/toee_knowledge"
PROJECTED = 1500      # projected corpus size (chunks)
DEADLINE_MS = 200     # driver-side deadline for the guarded retriever

RETRIEVE = ("SELECT id,page_type,title,ts_rank(tsv,plainto_tsquery('english',%s)) r "
            "FROM knowledge_chunk WHERE tsv @@ plainto_tsquery('english',%s) "
            "ORDER BY r DESC LIMIT 3")

QUERIES = ["return policy", "winter tires", "how to read sidewall numbers", "shipping options",
           "warranty", "dealer program", "vip points", "payment methods", "brand story",
           "grenlander", "windforce", "tire pressure", "business hours", "bulk order discount",
           "set up account", "all season tires", "refund", "who are you", "delivery time", "snow tires"]


def pct(sorted_ms, f):
    return sorted_ms[min(len(sorted_ms) - 1, int(f * len(sorted_ms)))]


def main():
    with psycopg.connect(DSN, autocommit=True) as conn:
        real = conn.execute("SELECT count(*) FROM knowledge_chunk").fetchone()[0]
        if real < PROJECTED:
            conn.execute(
                "INSERT INTO knowledge_chunk (page_id,page_type,title,url,chunk_index,chunk_text) "
                "SELECT 'synth-'||g,'synth','Synthetic filler '||g,NULL,0,"
                "'tire wheel rim tread pattern winter summer all season load index speed rating "
                "sidewall pressure warranty shipping delivery dealer program token '||g "
                "FROM generate_series(1,%s) g", (PROJECTED - real,))
        total = conn.execute("SELECT count(*) FROM knowledge_chunk").fetchone()[0]
        conn.execute("ANALYZE knowledge_chunk")
        print(f"corpus: {real} real + {total - real} synthetic = {total} chunks (projected {PROJECTED})")

        # --- Phase 1: true in-turn latency (generous timeout so we measure, not cap) ---
        conn.execute("SET statement_timeout = 5000")
        for q in QUERIES[:5]:
            conn.execute(RETRIEVE, (q, q)).fetchall()          # warm
        times = []
        for _ in range(10):
            for q in QUERIES:
                t0 = time.perf_counter()
                conn.execute(RETRIEVE, (q, q)).fetchall()
                times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        p95 = pct(times, .95)
        print(f"latency over {len(times)} in-turn FTS retrievals (host client -> localhost:5432):")
        print(f"  p50={pct(times,.5):.2f}ms  p95={p95:.2f}ms  p99={pct(times,.99):.2f}ms  max={times[-1]:.2f}ms")
        print(f"  [S-LAT gate] p95 < 800ms: {'PASS' if p95 < 800 else 'FAIL'}")

        # --- Phase 2: driver-side deadline -> governed found=false (no turn hang) ---
        conn.execute(f"SET statement_timeout = {DEADLINE_MS}")

        def guarded(sql, params=()):
            try:
                rows = conn.execute(sql, params).fetchall()
                return {"found": len(rows) > 0}
            except psycopg.errors.QueryCanceled:
                return {"found": False, "degraded": "deadline"}

        ok = guarded(RETRIEVE, ("winter tires", "winter tires"))
        t0 = time.perf_counter()
        dl = guarded("SELECT pg_sleep(2)")          # force an overrun
        el = (time.perf_counter() - t0) * 1000
        passed = dl.get("found") is False and dl.get("degraded") == "deadline" and el < 800
        print(f"deadline mechanism (statement_timeout={DEADLINE_MS}ms):")
        print(f"  normal retrieval under deadline -> {ok}")
        print(f"  forced 2000ms query -> {dl} in {el:.0f}ms")
        print(f"  [S-LAT deadline] slow retrieval degrades to found=false, no hang: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    main()
