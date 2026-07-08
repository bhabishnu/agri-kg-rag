"""
Central configuration for the starter pipeline.

The most important idea here is SOURCES: every source has a `reliability`
weight. When we store data, we attach that weight to each chunk. That is
EXACTLY the `Reliability` term in the project's verification score:

    S(f) = w1*Agreement + w2*Reliability + w3*Recency + w4*Confidence

So your ingestion work feeds the core innovation directly, instead of the
verification module having to hardcode reliability later. Keep this in mind —
it's what makes "just fetch data" strategically valuable.
"""

# ---------------------------------------------------------------------------
# Source registry + reliability metadata
# ---------------------------------------------------------------------------
SOURCES = {
    "agmarknet": {
        "name": "Agmarknet (via data.gov.in)",
        "reliability": 0.95,          # official govt price feed
        "type": "market_price",
        "url": "https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi",
    },
    "icar": {
        "name": "ICAR advisories",
        "reliability": 0.98,          # official agricultural research body
        "type": "advisory",
        "url": "https://icar.org.in",
    },
    "icar_pdf": {
        "name": "ICAR advisory PDFs",
        "reliability": 0.98,          # same official body, PDF publications
        "type": "advisory",
        "url": "https://icar.org.in",
    },
}

# ---------------------------------------------------------------------------
# PDF cache (downloaded advisory PDFs are stored here so we don't refetch)
# ---------------------------------------------------------------------------
PDF_CACHE_DIR = "./cache"

# ---------------------------------------------------------------------------
# data.gov.in (Agmarknet) API
# ---------------------------------------------------------------------------
# Resource ID for "Current Daily Price of Various Commodities from Various
# Markets (Mandi)". CONFIRM this on the portal when you register — data.gov.in
# occasionally reissues IDs. It's just a config string, so easy to change.
DATA_GOV_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
DATA_GOV_BASE = "https://api.data.gov.in/resource"

# ---------------------------------------------------------------------------
# Chunking (simple character-based splitter — good enough to learn on)
# ---------------------------------------------------------------------------
CHUNK_SIZE = 500        # target characters per chunk
CHUNK_OVERLAP = 80      # characters shared between neighbouring chunks

# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
# Small, fast, CPU-friendly, free, no API key. Downloads (~80 MB) on first run.
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Vector store (Chroma)
# ---------------------------------------------------------------------------
CHROMA_DIR = "./chroma_db"
COLLECTION = "agri_knowledge"
