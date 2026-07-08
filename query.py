"""
Ask a question, get back the most relevant stored chunks (this is the
"Retrieval" in Retrieval-Augmented Generation).

    python query.py "should I sell wheat now"
    python query.py "why are my wheat leaves turning yellow"

In the full system, these retrieved chunks would be handed to an LLM together
with the question to write the final answer. Here we just show what was
retrieved, plus each chunk's source and reliability — so you can literally see
the raw material the LLM would reason over.
"""

import sys

import pipeline


def main():
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = "price of wheat and how to treat yellowing leaves"

    coll = pipeline.get_collection()
    if coll.count() == 0:
        print("Collection is empty — run `python ingest.py` first.")
        return

    res = pipeline.query(coll, question, n_results=4)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = (res.get("distances") or [[None] * len(docs)])[0]

    print(f"\nQ: {question}")
    print("-" * 60)
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        src = meta.get("source_name", "?")
        rel = meta.get("reliability", "?")
        dist_str = f"{dist:.4f}" if isinstance(dist, (int, float)) else "n/a"
        print(f"[{i}] source={src} | reliability={rel} | distance={dist_str}")
        print(f"    {doc[:300]}")
        print()


if __name__ == "__main__":
    main()
