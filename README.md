# Agri KG-RAG — Ingestion & Retrieval Layer

The **data-ingestion and retrieval layer** for a knowledge-graph RAG (Retrieval-Augmented
Generation) agricultural advisory system. It acquires agricultural data from two sources,
normalizes and embeds it into a persistent vector database, and retrieves the most relevant
chunks for a question — re-ranked by a transparent, per-term **verification score**.

It is a **retrieval layer, not a full advisor**: there is no LLM answer-generation step and
no knowledge graph yet (see [What works / what's next](#what-works--whats-next)). `query.py`
prints the retrieved, re-ranked chunks so you can see exactly what an answer-generation step
would receive.

Two sources feed the store:

- **Agmarknet** — structured crop-price rows, via the official **data.gov.in** resource API.
- **ICAR advisories** — unstructured advisory text, crawled from PDF articles on ICAR's
  Open Journal Systems (OJS) journal platform (`epubs.icar.org.in`).

> The crawler is **journal-agnostic across ICAR's OJS platform** — point it at any OJS journal
> on `epubs.icar.org.in` (archive, issue, article, or direct-galley URL) and it resolves down
> to the article PDFs the same way.

---

## Architecture

```
  Agmarknet API ──────────────────────┐
  (structured prices, templatized)     │
                                        ├─▶ chunk ─▶ embed ─▶ ChromaDB ─▶ retrieve ─▶ verification re-rank
  ICAR OJS journal ─▶ crawl ─▶ PDF ─────┘         (all-MiniLM-L6-v2,   (persistent,   (top-k by     (S(f): reliability +
  (epubs.icar.org.in)   extract           384-dim vectors)    on disk)     distance)     recency + confidence)
```

The pipeline is linear. To understand it, read the files in this order:
`config → sources / pdf_sources / crawl_icar → pipeline → ingest → query / verification`.

- **`config.py`** — all settings, including the `SOURCES` registry. Every source carries a
  `reliability` weight that is attached to each stored chunk at ingestion, so downstream
  verification never hardcodes source trust.
- **`sources.py`** — Agmarknet price fetch/normalize + the local-text ICAR loader.
- **`pdf_sources.py`** — download (cached) → extract (`pypdf`) → clean a PDF advisory into text.
- **`crawl_icar.py`** — walk an ICAR OJS journal (archive → issue → article → PDF galley),
  download each article PDF, and ingest it through the same path as everything else.
- **`pipeline.py`** — the reusable machinery: `clean_text` → `chunk_text` (character-based
  sliding window) → `embed_texts` → Chroma `upsert` / `query`. Embeddings are computed here
  and passed into Chroma explicitly, so Chroma never loads its own embedding model.
- **`ingest.py`** — orchestrates a run and attaches metadata (`source`, `reliability`, `type`,
  `ingested_at`, `source_url`) to each doc. Prices become one doc per row; advisories are
  chunked into one doc per chunk.
- **`query.py`** — embeds the question, over-fetches candidates from Chroma, and re-ranks them
  by the verification score before printing the top results with a per-term breakdown.
- **`verification.py`** — computes `S(f)` (see below).

---

## Tech stack

| Layer | Tool |
|-------|------|
| Language | Python 3.10+ |
| Crawling / scraping | `requests`, `BeautifulSoup` + `lxml` |
| PDF extraction | `pypdf` |
| Embeddings | `sentence-transformers` — `all-MiniLM-L6-v2` (384-dim, CPU-friendly, no API key) |
| Vector store | ChromaDB (persistent, on disk) |
| Price data | data.gov.in resource API (Agmarknet) |

No LLM API, database server, or GPU is required to run the current pipeline.

---

## What works / what's next

**Works today:**

- Crawling ICAR OJS journals and resolving archive/issue/article/galley URLs down to article PDFs.
- PDF download + caching, text extraction, cleaning, character-based chunking.
- Fetching + normalizing Agmarknet prices from data.gov.in (or a bundled offline sample).
- Embedding with `all-MiniLM-L6-v2` and storing in a persistent Chroma collection (idempotent
  upserts via deterministic ids).
- Semantic retrieval with a **verification re-rank** so the top result is the most *trustworthy*
  relevant chunk, not merely the closest vector.

**Not yet implemented (honest limitations):**

- **LLM answer generation.** The system stops at retrieval; it returns chunks, it does not
  write answers.
- **Knowledge graph.** There is no Neo4j / KG component yet — despite the "KG" in the name,
  structured facts and relationships are not modeled. Prices currently live in the vector
  store as templatized sentences, which is a deliberate simplification (exact numeric lookups
  really belong in SQL/Neo4j).
- **The `Agreement` term is a placeholder.** In the verification score it is fixed at a neutral
  `0.5`. Real agreement requires a *second independent source* corroborating a fact, and no
  cross-source lookup exists yet — so it is not fabricated. The other three terms
  (`Reliability`, `Recency`, `Confidence`) use real data.

---

## Verification score

Retrieved chunks are re-ranked by:

```
S(f) = w1*Agreement + w2*Reliability + w3*Recency + w4*Confidence
```

| Term | Status | Source |
|------|--------|--------|
| Reliability | real | `metadata["reliability"]`, from `config.SOURCES`, attached at ingestion |
| Recency | real | `metadata["ingested_at"]`, exponential decay (365-day half-life) |
| Confidence | real | derived from the Chroma vector distance (closer = higher) |
| Agreement | **placeholder** | fixed `0.5` — no cross-source corroboration yet |

Weights are defined (and normalized to sum to 1) in `verification.py`. `query.py` prints each
term's raw value and weighted contribution, and flags the placeholder, so it's always clear
*why* a chunk ranked where it did.

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

A **free data.gov.in API key** (register at https://data.gov.in → My Account → Generate API
Key) is needed only for live Agmarknet prices — not for the offline demo below.

Two env flags control ingestion:

- `USE_SAMPLE` — `1` (default) reads `sample_data/` fully offline; `0` hits the live
  data.gov.in API (needs `DATA_GOV_API_KEY`).
- `USE_DUMMY_EMBEDDINGS` — `1` uses deterministic hash vectors (no model download, but rankings
  are meaningless — a plumbing test only); leave unset for real semantic embeddings.

> `ingest.py` upserts on deterministic ids, so re-running is safe. To start completely clean,
> delete `./chroma_db/`.

### Quickstart (offline, ~2 minutes)

```bash
# bundled sample data + fake embeddings — no API key, no model download
USE_SAMPLE=1 USE_DUMMY_EMBEDDINGS=1 python ingest.py
USE_DUMMY_EMBEDDINGS=1 python query.py "price of wheat in Patna"
```

> ⚠️ With `USE_DUMMY_EMBEDDINGS=1` the ranking is **random** — the fake vectors carry no
> meaning. It only proves the plumbing wires up. Real ranking appears once you drop the flag.

### Real embeddings (still sample prices)

Dropping the dummy flag loads the real embedding model (downloads ~80 MB once):

```bash
USE_SAMPLE=1 python ingest.py
python query.py "why are my wheat leaves turning yellow"
```

Retrieval is now **semantic** — the relevant advisory chunk should rise to the top.

### Live Agmarknet prices

```bash
cp .env.example .env
# edit .env and paste your data.gov.in key, then:
export DATA_GOV_API_KEY=$(grep DATA_GOV_API_KEY .env | cut -d= -f2)

USE_SAMPLE=0 python ingest.py
python query.py "onion price today"
```

`sources.fetch_agmarknet()` calls the data.gov.in resource API. Adjust `limit`, or add
`filters[commodity]=Wheat`-style params, to control what you pull. **Confirm the resource ID**
in `config.py` on the portal — data.gov.in occasionally reissues it.

### Crawling ICAR advisory PDFs

`crawl_icar.py` ingests real ICAR advisory PDFs from the OJS platform. It accepts any of four
URL shapes and resolves each down to the article PDFs:

```bash
# newest 3 issues of a journal's archive
python crawl_icar.py "https://epubs.icar.org.in/index.php/IndFarm/issue/archive" --limit 3

# a single issue, a single article, or a direct PDF galley
python crawl_icar.py "https://epubs.icar.org.in/index.php/IndFarm/issue/view/<id>"
python crawl_icar.py "https://epubs.icar.org.in/index.php/IndFarm/article/view/<id>"
```

Downloaded PDFs are cached under `./cache/`, so re-runs skip the network. Scanned/image-only
PDFs (no extractable text) and any PDF that errors out are warned about and skipped — one bad
PDF never aborts the run. Honors `USE_DUMMY_EMBEDDINGS=1` just like `ingest.py`.

---

## A note on prices in a vector DB

Price tables are **structured** and ideally belong in a SQL table or the knowledge graph
(Neo4j) for exact queries like "max wheat price in Bihar today". This layer turns each price
row into a **sentence** (`price_to_text`) so it flows through the same RAG pipeline — good for
fuzzy questions and for exercising the whole flow with one store, but not a substitute for
structured storage in the final system.

---

## File map

| File | What it does |
|------|--------------|
| `config.py` | Settings + source reliability metadata |
| `sources.py` | Fetch/normalize Agmarknet prices; load local ICAR text |
| `pdf_sources.py` | Download (cached) + extract + clean a PDF advisory |
| `crawl_icar.py` | Crawl an ICAR OJS journal and ingest every article PDF |
| `pipeline.py` | clean → chunk → embed → store/query (core machinery) |
| `ingest.py` | Orchestrate a run; build docs with metadata; load the DB |
| `query.py` | Ask a question; retrieve + verification re-rank + print |
| `verification.py` | Compute the verification score `S(f)` |
| `sample_data/` | Offline sample price JSON + illustrative ICAR advisory |

`.venv/`, `chroma_db/`, and `cache/` live in the working tree but are gitignored.

---

## Troubleshooting

- **First real run is slow / seems stuck** — it's downloading the embedding model (~80 MB) once.
  Later runs are fast.
- **`sentence-transformers` download fails** — first run needs internet to HuggingFace; a
  locked-down network will block it.
- **API returns very few rows** — the public/demo data.gov.in key is capped; use your own
  registered key and raise `limit`.
- **Crawler skips a PDF** — likely a scanned/image-only PDF (no extractable text) or a URL that
  served HTML instead of a PDF; the run continues past it.
- **`ModuleNotFoundError`** — activate the venv, then reinstall requirements.
- **Weird/irrelevant ranking** — you probably still have `USE_DUMMY_EMBEDDINGS=1` set. Unset it
  for real results.
