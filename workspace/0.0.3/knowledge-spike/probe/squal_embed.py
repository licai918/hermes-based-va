"""S-QUAL rung 2 (embedding): recall@3 via a small local model (fastembed, no torch).
Same metric as rung 1 (gold-doc chunk in top-3), same corpus + questions, so the numbers
are directly comparable. Cosine over 167 chunks is trivial — no pgvector needed for a spike."""
import json, os, psycopg
import numpy as np
from fastembed import TextEmbedding

DSN = "postgresql://toee:toee@localhost:5432/toee_knowledge"
HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "questions.json")
BAR = 0.80
MODEL = "BAAI/bge-small-en-v1.5"          # 384-dim, ~130MB, strong small retriever
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _norm(m):
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def main():
    qs = json.load(open(QUESTIONS, encoding="utf-8"))
    with psycopg.connect(DSN, autocommit=True, connect_timeout=6) as conn:
        rows = conn.execute("SELECT page_id, chunk_text FROM knowledge_chunk "
                            "WHERE page_type<>'synth' ORDER BY id").fetchall()
    page_ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]

    emb = TextEmbedding(model_name=MODEL)
    try:                                            # bge wants an asymmetric query prefix
        C = np.array(list(emb.passage_embed(texts)))
        Q = np.array(list(emb.query_embed([q["q"] for q in qs])))
    except AttributeError:
        C = np.array(list(emb.embed(texts)))
        Q = np.array(list(emb.embed([QUERY_PREFIX + q["q"] for q in qs])))
    sims = _norm(Q) @ _norm(C).T                    # (M questions, N chunks)

    hits, misses = 0, []
    for i, item in enumerate(qs):
        top3 = np.argsort(-sims[i])[:3]
        got = [page_ids[j] for j in top3]
        if any(g in got for g in item["gold"]):
            hits += 1
        else:
            misses.append((item["q"], item["gold"], got))

    recall = hits / len(qs)
    print(f"S-QUAL rung 2 (embedding {MODEL}) — {len(texts)} chunks, {len(qs)} questions")
    print(f"  recall@3 = {hits}/{len(qs)} = {recall:.0%}   [bar {BAR:.0%}: {'PASS' if recall >= BAR else 'FAIL'}]")
    print("  (rung 1 FTS was 50%)")
    if misses:
        print(f"  {len(misses)} misses:")
        for q, gold, got in misses:
            print(f"    Q {q!r}")
            print(f"      gold={gold}  got={got}")


if __name__ == "__main__":
    main()
