# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A minimal, runnable skeleton for the **data-ingestion** half of a Dynamic KG-RAG
agricultural advisor. It pulls from two sources, normalizes them, embeds the text,
and stores it in a persistent Chroma vector DB you can query. It deliberately stops
at retrieval — there is no LLM answer-generation step; `query.py` just prints the
retrieved chunks. This is a learning starter meant to be extended (more sources,
Neo4j knowledge graph, verification scoring).

## Commands

Setup:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Run the pipeline (ingest then query). Two env flags control the mode:
- `USE_SAMPLE` — `1` (default) reads `sample_data/`, fully offline; `0` hits the live data.gov.in API (needs `DATA_GOV_API_KEY`).
- `USE_DUMMY_EMBEDDINGS` — `1` uses deterministic hash vectors (no model download, but rankings are meaningless junk — plumbing test only); leave unset for real semantic embeddings.

```bash
# offline plumbing check (fake vectors — ranking is random, that's expected)
USE_SAMPLE=1 USE_DUMMY_EMBEDDINGS=1 python ingest.py
USE_DUMMY_EMBEDDINGS=1 python query.py "price of wheat in Patna"

# real embeddings on sample data (downloads ~80 MB model once, into HF cache)
USE_SAMPLE=1 python ingest.py
python query.py "why are my wheat leaves turning yellow"

# fully live prices (needs a data.gov.in key in .env)
cp .env.example .env   # then paste key
export DATA_GOV_API_KEY=$(grep DATA_GOV_API_KEY .env | cut -d= -f2)
USE_SAMPLE=0 python ingest.py
```

There is no test suite, linter, or build step. `ingest.py` is idempotent-ish but
**appends** to Chroma every run (new UUID ids), so re-running duplicates data. To
start clean, delete `./chroma_db/`.

## Architecture

The flow is a linear pipeline, read the files in this order to understand it:
`config → sources → pipeline → ingest → query`.

- **`config.py`** — all settings. The strategically important object is `SOURCES`:
  each source carries a `reliability` weight (and `type`). This weight is attached
  to every stored chunk at ingestion time (see below) so downstream verification
  never has to hardcode source trust.
- **`sources.py`** — data acquisition, two shapes:
  - Agmarknet = **structured** price rows via the data.gov.in resource API.
    `_normalize_price` looks up fields defensively (data.gov.in has renamed columns
    across versions, e.g. `state` vs `State`). `price_to_text` flattens each row
    into a sentence so it can be embedded through the same path as prose.
  - ICAR = **unstructured** advisory text. `load_icar_text` reads a local file (demo);
    `scrape_icar_page` is the BeautifulSoup pattern for going live (not wired into
    `ingest.py` by default).
- **`pipeline.py`** — the reusable machinery: `clean_text` → `chunk_text` (character-based
  sliding window, `CHUNK_SIZE`/`CHUNK_OVERLAP`) → `embed_texts` → Chroma `add`/`query`.
  Embeddings are computed here and passed into Chroma explicitly, so Chroma never
  loads its own embedding model. The `sentence-transformers` model is lazy-loaded
  and cached in module global `_model`.
- **`ingest.py`** — orchestrates one full run. `build_docs_from_prices` and
  `build_docs_from_icar` are where **metadata is attached** to each doc: `source`,
  `reliability` (from `config.SOURCES`), `type`, and an `ingested_at` UTC timestamp.
  Prices become one doc per row; advisories are chunked into one doc per chunk.
- **`query.py`** — embeds the question, pulls nearest chunks, prints them with their
  source/reliability/distance. This is the retrieval-only endpoint.

## Key conventions

- **Doc shape** everywhere is `{"id": str, "text": str, "metadata": dict}`. Ids are
  namespaced `agmarknet::<hex>` / `icar::<hex>`.
- **The `reliability` + `ingested_at` metadata is the point.** They feed the planned
  verification score `S(f) = w1*Agreement + w2*Reliability + w3*Recency + w4*Confidence`.
  When adding a new source, register it in `config.SOURCES` with a reliability weight
  and propagate that weight into the doc metadata — don't drop it.
- Prices in a vector DB is a deliberate simplification. Exact numeric lookups
  ("max wheat price in Bihar today") really belong in SQL/Neo4j; this starter
  embeds them only so the whole flow works with one store.
- The embedding dimension is 384 (`all-MiniLM-L6-v2`); the dummy embedder matches it.

`.venv/` and `chroma_db/` live in the working tree but are gitignored.
