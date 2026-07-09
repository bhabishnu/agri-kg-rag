"""
The reusable machinery: clean -> chunk -> embed -> store, plus query.

This is the heart of "put data in a vector database". Read it top to bottom
once and you'll understand the whole RAG ingestion flow.
"""

import os
import hashlib

import numpy as np

import config


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
def clean_text(text):
    """Trim whitespace and drop blank lines. Real cleaning gets fancier
    (removing headers/footers, fixing encoding), but this is the idea."""
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------
def chunk_text(text, size=None, overlap=None):
    """Split long text into overlapping windows.

    Why chunk? Embedding a whole 5-page document into ONE vector blurs its
    meaning, and you can't retrieve just the relevant paragraph. Small
    overlapping chunks keep retrieval sharp. Overlap avoids cutting a sentence
    clean in half at a boundary.
    """
    size = size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    chunks, start = [], 0
    while start < len(text):
        chunk = text[start:start + size].strip()
        if chunk:
            chunks.append(chunk)
        start += size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------
# Real embeddings use sentence-transformers (downloads the model on first run).
# Set USE_DUMMY_EMBEDDINGS=1 to use deterministic offline vectors instead —
# handy for testing the plumbing with no model download and no GPU. Your real
# runs should leave it OFF.
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"  (loading embedding model {config.EMBED_MODEL} — first run downloads it)")
        _model = SentenceTransformer(config.EMBED_MODEL)
    return _model


def embed_texts(texts):
    """Turn a list of strings into a list of vectors."""
    if os.environ.get("USE_DUMMY_EMBEDDINGS") == "1":
        return [_dummy_embed(t) for t in texts]
    model = _get_model()
    return model.encode(texts, show_progress_bar=False).tolist()


def _dummy_embed(text, dim=384):
    """Deterministic pseudo-embedding from a hash. ONLY for offline plumbing
    tests — it has no real semantic meaning."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
    v = rng.standard_normal(dim)
    v = v / (np.linalg.norm(v) + 1e-9)
    return v.tolist()


# ---------------------------------------------------------------------------
# Store / query (Chroma)
# ---------------------------------------------------------------------------
def get_collection():
    """Open (or create) a persistent Chroma collection on disk."""
    import chromadb
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    return client.get_or_create_collection(config.COLLECTION)


def add_documents(collection, docs):
    """Embed and store a batch of docs.

    Each doc is a dict: {"id": str, "text": str, "metadata": dict}.
    We compute embeddings ourselves and pass them in, so Chroma never has to
    download its own embedding model.
    """
    if not docs:
        return
    ids = [d["id"] for d in docs]
    texts = [d["text"] for d in docs]
    metas = [d["metadata"] for d in docs]
    embeddings = embed_texts(texts)
    collection.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metas)


def query(collection, question, n_results=3):
    """Embed the question and pull back the nearest stored chunks."""
    q_emb = embed_texts([question])
    return collection.query(query_embeddings=q_emb, n_results=n_results)
