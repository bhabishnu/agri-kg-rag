"""
Run the whole pipeline:  sources -> docs (with metadata) -> vector store.

    python ingest.py

Environment switches:
    USE_SAMPLE=1            (default) use bundled sample data, fully offline
    USE_SAMPLE=0           hit the live data.gov.in API (needs DATA_GOV_API_KEY)
    USE_DUMMY_EMBEDDINGS=1  skip the model download, use fake vectors (testing)
    DATA_GOV_API_KEY=...    your key from https://data.gov.in (for live mode)
"""

import os
import uuid
from datetime import datetime, timezone

import config
import sources
import pipeline


def _now():
    return datetime.now(timezone.utc).isoformat()


def build_docs_from_prices(price_rows):
    """Each price row -> one doc, carrying source + reliability metadata."""
    src = config.SOURCES["agmarknet"]
    docs = []
    for p in price_rows:
        docs.append({
            "id": f"agmarknet::{uuid.uuid4().hex[:12]}",
            "text": sources.price_to_text(p),
            "metadata": {
                "source": "agmarknet",
                "source_name": src["name"],
                "reliability": src["reliability"],   # <- feeds verification score
                "type": src["type"],
                "commodity": p.get("commodity") or "",
                "market": p.get("market") or "",
                "state": p.get("state") or "",
                "arrival_date": p.get("arrival_date") or "",
                "ingested_at": _now(),
            },
        })
    return docs


def build_docs_from_icar(text, doc_title="ICAR wheat advisory"):
    """Advisory text -> cleaned -> chunked -> one doc per chunk."""
    src = config.SOURCES["icar"]
    chunks = pipeline.chunk_text(pipeline.clean_text(text))
    docs = []
    for i, chunk in enumerate(chunks):
        docs.append({
            "id": f"icar::{uuid.uuid4().hex[:12]}",
            "text": chunk,
            "metadata": {
                "source": "icar",
                "source_name": src["name"],
                "reliability": src["reliability"],
                "type": src["type"],
                "doc_title": doc_title,
                "chunk_index": i,
                "ingested_at": _now(),
            },
        })
    return docs


def main():
    use_sample = os.environ.get("USE_SAMPLE", "1") == "1"
    api_key = os.environ.get("DATA_GOV_API_KEY", "")

    if not use_sample and not api_key:
        print("Live mode needs DATA_GOV_API_KEY. Set it, or run with USE_SAMPLE=1.")
        return

    print("=" * 60)
    print("AGRI KG-RAG — starter ingestion")
    print("=" * 60)

    # --- Source 1: Agmarknet prices ---
    print(f"\n[1/3] Fetching Agmarknet prices  {'(sample)' if use_sample else '(LIVE)'}")
    prices = sources.fetch_agmarknet(api_key, limit=50, use_sample=use_sample)
    price_docs = build_docs_from_prices(prices)
    print(f"      {len(prices)} price rows -> {len(price_docs)} docs")

    # --- Source 2: ICAR advisory ---
    print("\n[2/3] Loading ICAR advisory text")
    icar_text = sources.load_icar_text()
    icar_docs = build_docs_from_icar(icar_text)
    print(f"      advisory -> {len(icar_docs)} chunks")

    # --- Embed + store ---
    print("\n[3/3] Embedding + storing in Chroma")
    coll = pipeline.get_collection()
    pipeline.add_documents(coll, price_docs + icar_docs)
    print(f"      collection '{config.COLLECTION}' now holds {coll.count()} items")
    print(f"      (persisted to {config.CHROMA_DIR})")

    print("\nDone. Now try:  python query.py \"price of wheat in Patna\"\n")


if __name__ == "__main__":
    main()
