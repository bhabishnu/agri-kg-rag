"""
Ask a question, get back the most relevant stored chunks (this is the
"Retrieval" in Retrieval-Augmented Generation).

    python query.py "should I sell wheat now"
    python query.py "why are my wheat leaves turning yellow"

In the full system, these retrieved chunks would be handed to an LLM together
with the question to write the final answer. Here we just show what was
retrieved, plus each chunk's source and reliability — so you can literally see
the raw material the LLM would reason over.

Ranking: Chroma returns candidates ordered by raw vector distance. We then
re-rank them with the verification score S(f) (see verification.py), which
folds in source reliability and recency on top of match quality. So the top
result is the most *trustworthy* relevant chunk, not merely the closest vector.
To give the re-rank something to work with, we over-fetch a handful of extra
candidates from Chroma and re-order those.
"""

import sys

import pipeline
from verification import verification_score

# How many candidates to pull from Chroma before re-ranking, vs how many of the
# re-ranked results to actually show.
N_CANDIDATES = 12
N_SHOW = 4


def _fmt(x):
    return f"{x:.4f}" if isinstance(x, (int, float)) else "n/a"


def main():
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = "price of wheat and how to treat yellowing leaves"

    coll = pipeline.get_collection()
    if coll.count() == 0:
        print("Collection is empty — run `python ingest.py` first.")
        return

    # Over-fetch: grab extra candidates so the verification re-rank has room to
    # reorder (a slightly-farther but far more reliable/recent chunk can win).
    res = pipeline.query(coll, question, n_results=N_CANDIDATES)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = (res.get("distances") or [[None] * len(docs)])[0]

    # Score every candidate, then re-rank by verification score (desc), NOT by
    # raw distance. `chroma_rank` preserves the original distance ordering so we
    # can see how far each result moved.
    scored = []
    for chroma_rank, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        score, breakdown = verification_score(meta, dist)
        scored.append((score, breakdown, doc, meta, dist, chroma_rank))
    scored.sort(key=lambda t: t[0], reverse=True)

    print(f"\nQ: {question}")
    print(f"(retrieved {len(scored)} candidates from Chroma, showing top "
          f"{min(N_SHOW, len(scored))} after verification re-rank)")
    print("-" * 70)

    for i, (score, bd, doc, meta, dist, chroma_rank) in enumerate(scored[:N_SHOW], 1):
        src = meta.get("source_name") or meta.get("source", "?")
        moved = "" if chroma_rank == i else f" (was #{chroma_rank} by distance)"
        print(f"[{i}] score={score:.4f}{moved}")
        print(f"    source={src} | distance={_fmt(dist)}")

        # Per-term breakdown so it's obvious WHY this chunk ranked here.
        # agreement is a placeholder — flag it so it isn't read as real evidence.
        for term in ("agreement", "reliability", "recency", "confidence"):
            t = bd[term]
            tag = "" if t["real"] else "  <-- placeholder (no cross-source check)"
            print(f"      {term:<12} raw={t['raw']:.4f}"
                  f"  x w={t['weight']:.3f}"
                  f"  = {t['contribution']:.4f}{tag}")

        print(f"    {doc[:300]}")
        print()


if __name__ == "__main__":
    main()
