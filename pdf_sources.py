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


USER_AGENT = "Mozilla/5.0 (M.Tech research project)"


class NotAPdfError(ValueError):
    """Raised when a URL we expected to serve a PDF returns something else.

    On epubs.icar.org.in the PDF galley URL `/article/view/{id}/{galleyId}`
    returns the PDF bytes directly. If it instead returns HTML (a viewer shell,
    an error page, a login wall), we refuse to treat it as a PDF so we never
    ingest garbage — the caller logs it and skips.
    """


def _cache_path_for(url):
    """Deterministic local filename for a URL, kept inside the cache dir.

    We hash the URL (so odd query strings / long paths don't break the
    filesystem) and keep a .pdf suffix so cached files are recognisable.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(config.PDF_CACHE_DIR, f"{digest}.pdf")


def _looks_like_pdf(resp):
    """True if a response body is actually a PDF, by header or by magic bytes.

    OJS galley URLs usually return the PDF directly, but some are served with a
    sloppy content-type, so we also sniff the leading `%PDF-` marker.
    """
    ctype = resp.headers.get("Content-Type", "").lower()
    return "application/pdf" in ctype or resp.content[:5] == b"%PDF-"


def _fetch_pdf_bytes(url):
    """Fetch `url` and return PDF bytes, verifying it really is a PDF.

    On this site the galley URL `/article/view/{id}/{galleyId}` serves the PDF
    bytes directly, so we fetch once and check the response is a PDF (by
    Content-Type, with a `%PDF-` magic-byte fallback for sloppy servers). We do
    NOT chase `/download/` or embedded links — those don't exist here, and
    guessing at them is how the old code ended up ingesting HTML. If the
    response is HTML/anything else, we raise NotAPdfError so the caller skips.
    """
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, timeout=120, headers=headers)
    resp.raise_for_status()

    if not _looks_like_pdf(resp):
        ctype = resp.headers.get("Content-Type", "") or "unknown"
        raise NotAPdfError(f"expected a PDF but server returned Content-Type '{ctype}'")

    return resp.content


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

    content = _fetch_pdf_bytes(url)
    with open(path, "wb") as f:
        f.write(content)
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
