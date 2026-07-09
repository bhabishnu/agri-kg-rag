"""
Ingest a single PDF advisory from a URL into the existing Chroma collection.

    python demo_pdf.py <pdf-url>

Downloads (and caches) the PDF, extracts its text, builds chunked docs with
`icar_pdf` metadata, and adds them to the same persistent Chroma collection the
main pipeline uses. Prints how many chunks were added plus a preview of the
extracted text so you can eyeball that extraction actually worked.

Honors USE_DUMMY_EMBEDDINGS=1 (fake vectors, no model download) just like ingest.py.
"""

import sys

import config
import pdf_sources
import pipeline
import ingest


def main():
    if len(sys.argv) < 2:
        print("Usage: python demo_pdf.py <pdf-url>")
        sys.exit(1)

    url = sys.argv[1]

    print(f"Downloading + extracting PDF:\n  {url}\n")
    text = pdf_sources.load_pdf_text(url)

    if not text.strip():
        print("No text extracted — the PDF may be scanned/image-only or empty.")
        sys.exit(1)

    preview = text[:200]
    print("First 200 chars of extracted text:")
    print("-" * 60)
    print(preview)
    print("-" * 60)

    docs = ingest.build_docs_from_pdf(text, source_url=url)

    coll = pipeline.get_collection()
    pipeline.add_documents(coll, docs)

    print(f"\nAdded {len(docs)} chunks to collection '{config.COLLECTION}'.")
    print(f"Collection now holds {coll.count()} items (persisted to {config.CHROMA_DIR}).")


if __name__ == "__main__":
    main()
