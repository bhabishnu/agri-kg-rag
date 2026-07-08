# Agri KG-RAG — Starter Ingestion Pipeline

A minimal, **runnable** skeleton for the data-ingestion part of the Dynamic
KG-RAG agricultural advisor. It pulls from **two sources** and loads them into a
**vector database (Chroma)** that you can query.

- **Source 1 — Agmarknet** (crop prices) via the official **data.gov.in API**
- **Source 2 — ICAR** advisory text (a local sample now; real scraping when you go live)

The goal is to help you *get a hang of the whole flow* fast, then extend it.

---

## What actually happens (the flow in one picture)

```
  Agmarknet API ─┐
                 ├─▶ clean ─▶ (chunk text / templatize prices) ─▶ embed ─▶ Chroma ─▶ query
  ICAR text ─────┘                                                          (vector DB)
```

"Embed" = turn text into a list of numbers (a *vector*) that captures its
meaning. The vector DB stores these and, at query time, finds the chunks whose
vectors are closest to your question's vector. That's retrieval. In the full
system those retrieved chunks get handed to an LLM to write the final answer —
this starter stops at retrieval so you can see the raw material clearly.

---

## Prerequisites (so you're not lost)

### Concepts to be comfortable with (you can learn as you go)
- **Embedding** — text → vector of numbers representing meaning. You *call* a
  model to do this; you don't need to understand the ML inside it.
- **Vector database** — stores those vectors and finds "nearest" (most similar)
  ones. Best for **unstructured text** (advisories), not for exact number
  lookups (prices) — see the note below.
- **Chunking** — splitting a long document into small overlapping pieces so
  retrieval is sharp.
- **RAG** — Retrieve relevant chunks, then let an LLM reason over them.
- **Structured vs unstructured data** — prices are structured (rows/numbers);
  advisories are unstructured (prose). This starter handles both.

### Software to have installed
- **Python 3.10+**
- **A code editor** — VS Code recommended
- **Git** (to clone / hand to Claude Code later)
- Basic command-line comfort (run a script, activate a virtual environment)

### Python skills that are enough
Running a script, editing a file, `pip install`, and reading dicts/lists/JSON.
**No machine-learning background needed.**

### One account to create
A **free data.gov.in API key** — register at https://data.gov.in
(My Account → Generate API Key). Not needed for the offline demo below.

---

## Quickstart (offline — get a win in 2 minutes)

```bash
# 1. create an isolated environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. run the pipeline on bundled SAMPLE data with fake embeddings
#    (no API key, no model download — just proves it all wires up)
USE_SAMPLE=1 USE_DUMMY_EMBEDDINGS=1 python ingest.py
USE_DUMMY_EMBEDDINGS=1 python query.py "price of wheat in Patna"
```

> ⚠️ With `USE_DUMMY_EMBEDDINGS=1` the ranking is **random junk** — the fake
> vectors carry no meaning, so a rice row might top a wheat query. That's
> expected. It only proves the plumbing. Real ranking appears in the next step.

---

## Run it "for real" (real embeddings, still sample prices)

Drop the dummy flag so the real embedding model loads (downloads ~80 MB once):

```bash
USE_SAMPLE=1 python ingest.py
python query.py "why are my wheat leaves turning yellow"
```

Now retrieval is **semantic** — the nitrogen-deficiency advisory chunk should
rise to the top for that question. This is the moment the system "gets it".

---

## Go fully live (real Agmarknet prices)

```bash
cp .env.example .env
# edit .env and paste your data.gov.in key, then:
export DATA_GOV_API_KEY=$(grep DATA_GOV_API_KEY .env | cut -d= -f2)

USE_SAMPLE=0 python ingest.py
python query.py "onion price today"
```

`sources.fetch_agmarknet()` calls the data.gov.in resource API. Adjust `limit`,
or add `filters[commodity]=Wheat` style params, to control what you pull.
**Confirm the resource ID** in `config.py` on the portal — data.gov.in
occasionally reissues it.

### Adding real ICAR text
`sources.scrape_icar_page(url)` shows the BeautifulSoup pattern. To use it,
call it in `ingest.py` instead of `load_icar_text()`, e.g.:

```python
icar_text = sources.scrape_icar_page("https://icar.org.in/some-advisory-page")
```

Real government pages are messy — you'll tune which tags to strip per site.
Always set a User-Agent, add a short delay between requests, and check the
site's `robots.txt`. (For PDF advisories, extract text first with a PDF library,
then feed the string to `build_docs_from_icar`.)

---

## About prices in a vector DB (important nuance)

Price tables are **structured** and ideally live in a SQL table or the
knowledge graph (Neo4j) so you can do exact queries like "max wheat price in
Bihar today". This starter turns each price row into a **sentence**
(`price_to_text`) so it flows through the same RAG pipeline — great for learning
and for answering fuzzy questions, but not a substitute for structured storage
in the final system. Keep both in mind; both are legitimate.

---

## File map

| File | What it does |
|------|--------------|
| `config.py` | Settings + **source reliability metadata** (the key tie-in) |
| `sources.py` | Fetch Agmarknet (API) + load/scrape ICAR text |
| `pipeline.py` | clean → chunk → embed → store/query (the core machinery) |
| `ingest.py` | Runs everything; builds docs with metadata; loads the DB |
| `query.py` | Ask a question, see retrieved chunks + their source/reliability |
| `sample_data/` | Offline sample price JSON + illustrative ICAR advisory |

---

## Why your part matters (connect it to the big project)

Every chunk you store carries a `reliability` value (see `config.SOURCES`).
That is **exactly** the `Reliability` term in the project's verification score:

```
S(f) = w1*Agreement + w2*Reliability + w3*Recency + w4*Confidence
```

Because you attach it at ingestion, the verification module can read it directly
instead of hardcoding source trust later. Same goes for the `ingested_at`
timestamp (feeds *Recency*) and, if you add conflict detection at ingestion
(e.g. Agmarknet vs eNAM disagree), that feeds *Agreement*. So "just loading
data" is really building the foundation the verification innovation stands on.

---

## Suggested 3-day plan

**Day 1 — Environment + understand the flow.**
Install Python + VS Code, create the venv, `pip install -r requirements.txt`,
run the offline quickstart. Then read the five `.py` files **in this order**:
`config → sources → pipeline → ingest → query`. By end of day you should be
able to explain embedding, chunking, and retrieval in your own words. Register
on data.gov.in and get your API key.

**Day 2 — Go live with Agmarknet.**
Drop the dummy flag (real embeddings), then `USE_SAMPLE=0` with your key.
Confirm real prices flow in and that `query.py` returns sensible results.
Experiment: change `limit`, filter by a commodity or state, pull a couple of
days of data.

**Day 3 — Add real ICAR text + write up.**
Scrape one or two real ICAR/Krishi pages with `scrape_icar_page` (or drop in a
few real advisory text/PDF files), re-ingest, and test retrieval across both
sources. Then write a short note: what you built, and how the reliability +
timestamp metadata plugs into the verification module. Hand the repo to **Claude
Code** to extend to more sources (eNAM, IMD, etc.).

---

## Troubleshooting

- **First real run is slow / seems stuck** — it's downloading the embedding
  model (~80 MB) once. Later runs are fast.
- **`sentence-transformers` download fails** — you need internet to huggingface
  on first run; a locked-down network will block it.
- **API returns very few rows** — the public/demo data.gov.in key is capped;
  use your own registered key and raise `limit`.
- **`ModuleNotFoundError`** — activate the venv, then reinstall requirements.
- **Weird/irrelevant ranking** — you probably still have
  `USE_DUMMY_EMBEDDINGS=1` set. Unset it for real results.
