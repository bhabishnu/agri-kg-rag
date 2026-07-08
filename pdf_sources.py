"""
PDF advisories as a data source.

Same idea as the ICAR text loader in sources.py, but the advisory arrives as a
PDF on the web instead of a local .txt file. The shape is still UNSTRUCTURED
text: download the PDF, pull its text out, clean it, and it flows through the
exact same clean -> chunk -> embed path as any other prose.

We cache downloaded PDFs on disk (config.PDF_CACHE_DIR) so re-running ingestion
doesn't re-fetch the same file over the network every time.
"""

import os
import hashlib

import requests

import config


def _cache_path_for(url):
    """Deterministic local filename for a URL, kept inside the cache dir.

    We hash the URL (so odd query strings / long paths don't break the
    filesystem) and keep a .pdf suffix so cached files are recognisable.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(config.PDF_CACHE_DIR, f"{digest}.pdf")


def download_pdf(url, cache_dir=None):
    """Download a PDF to the local cache, skipping the fetch if we already have it.

    Returns the local path to the cached PDF.
    """
    cache_dir = cache_dir or config.PDF_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(cache_dir, f"{digest}.pdf")

    if os.path.exists(path):
        return path  # already downloaded — skip the network entirely

    resp = requests.get(
        url, timeout=120,
        headers={"User-Agent": "Mozilla/5.0 (M.Tech research project)"},
    )
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def extract_pdf_text(path):
    """Pull the readable text out of a PDF file, page by page."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages)


def load_pdf_text(url, cache_dir=None):
    """THE PATTERN for PDF sources: download (cached) -> extract -> clean.

    Mirrors sources.load_icar_text / scrape_icar_page but for a PDF URL. The
    returned text is cleaned with the same helper the rest of the pipeline uses,
    so it's ready to be chunked and embedded.
    """
    import pipeline

    path = download_pdf(url, cache_dir=cache_dir)
    text = extract_pdf_text(path)
    return pipeline.clean_text(text)
