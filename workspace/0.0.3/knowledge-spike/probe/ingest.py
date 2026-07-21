"""Spike ingest: corpus.json -> chunk -> knowledge_chunk (toee_knowledge).
Throwaway. TRUNCATEs first so re-runs are clean (keeps S-QUAL corpus real-only)."""
import json, os, sys, psycopg

DSN = "postgresql://toee:toee@localhost:5432/toee_knowledge"
HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus.json")
CHUNK = 600  # ~chars per chunk, word-boundary


def chunks(text, size=CHUNK):
    out, cur = [], ""
    for w in (text or "").split():
        if cur and len(cur) + 1 + len(w) > size:
            out.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def main():
    if not os.path.exists(CORPUS):
        sys.exit(f"corpus.json not found at {CORPUS} (is the pull subagent done?)")
    docs = json.load(open(CORPUS, encoding="utf-8"))
    rows = []
    for d in docs:
        for i, ch in enumerate(chunks(d.get("text", ""))):
            if ch.strip():
                rows.append((d["page_id"], d["page_type"], d["title"], d.get("url"), i, ch))
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("TRUNCATE knowledge_chunk RESTART IDENTITY")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO knowledge_chunk (page_id,page_type,title,url,chunk_index,chunk_text)"
                " VALUES (%s,%s,%s,%s,%s,%s)", rows)
        n = conn.execute("SELECT count(*) FROM knowledge_chunk").fetchone()[0]
        by = conn.execute("SELECT page_type, count(DISTINCT page_id), count(*)"
                          " FROM knowledge_chunk GROUP BY page_type ORDER BY 1").fetchall()
    print(f"ingested {len(rows)} chunks from {len(docs)} docs -> table now {n} rows")
    for t, d, c in by:
        print(f"  {t}: {d} docs -> {c} chunks")


if __name__ == "__main__":
    main()
