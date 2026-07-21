"""S-QUAL rung 1 (Postgres FTS): recall@3 on questions.json.
Hit = a chunk from a gold doc appears in the top-3 retrieved chunks.
Corpus must be real-only (run ingest.py first). Synthetic questions bias FTS optimistic;
the real signal comes from real customer questions."""
import json, os, psycopg

DSN = "postgresql://toee:toee@localhost:5432/toee_knowledge"
HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "questions.json")
BAR = 0.80

# plainto_tsquery ANDs every term -> most multi-word questions match nothing.
# OR the lexemes (match ANY term) and let ts_rank surface the best-covered chunk.
_TSQ = "to_tsquery('english', replace(plainto_tsquery('english', %s)::text, '&', '|'))"
RETRIEVE = (f"SELECT page_id, ts_rank(tsv, {_TSQ}) r "
            f"FROM knowledge_chunk WHERE tsv @@ {_TSQ} "
            f"ORDER BY r DESC LIMIT 3")


def main():
    qs = json.load(open(QUESTIONS, encoding="utf-8"))
    with psycopg.connect(DSN, autocommit=True, connect_timeout=5) as conn:
        n_real = conn.execute("SELECT count(*) FROM knowledge_chunk WHERE page_type<>'synth'").fetchone()[0]
        n_all = conn.execute("SELECT count(*) FROM knowledge_chunk").fetchone()[0]
        if n_all != n_real:
            print(f"WARNING: {n_all - n_real} synthetic rows present — run ingest.py to restore real-only.")
        hits, misses = 0, []
        for item in qs:
            rows = conn.execute(RETRIEVE, (item["q"], item["q"])).fetchall()
            got = [r[0] for r in rows]                      # top-3 chunk page_ids, rank order
            if any(g in got for g in item["gold"]):
                hits += 1
            else:
                misses.append((item["q"], item["gold"], got))

    recall = hits / len(qs)
    print(f"S-QUAL rung 1 (FTS) — corpus {n_real} real chunks, {len(qs)} questions")
    print(f"  recall@3 = {hits}/{len(qs)} = {recall:.0%}   [bar {BAR:.0%}: {'PASS' if recall >= BAR else 'FAIL'}]")
    if misses:
        print(f"  {len(misses)} misses (no gold-doc chunk in top-3):")
        for q, gold, got in misses:
            print(f"    Q {q!r}")
            print(f"      gold={gold}")
            print(f"      got ={got}")


if __name__ == "__main__":
    main()
