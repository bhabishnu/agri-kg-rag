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
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config


USER_AGENT = "Mozilla/5.0 (M.Tech research project)"


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


def _find_embedded_pdf(html, base_url):
    """Given an HTML viewer page, return the URL of the PDF it embeds, or None.

    OJS galley "view" pages sometimes serve an HTML shell that embeds the real
    PDF via an <embed>/<iframe> (typically an `/article/download/...` URL) or
    links to it. We resolve the first such reference against the page URL.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag, attr in (("embed", "src"), ("iframe", "src")):
        for node in soup.find_all(tag):
            ref = node.get(attr)
            if ref and ("/download/" in ref or ".pdf" in ref.lower()):
                return urljoin(base_url, ref)

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/download/" in href or href.lower().endswith(".pdf"):
            return urljoin(base_url, href)

    return None


def _fetch_pdf_bytes(url):
    """Fetch `url` and return PDF bytes, following an HTML viewer to the real PDF.

    If the URL returns a PDF, we use it. If it returns HTML (a galley viewer
    page), we look for the embedded PDF link and fetch that instead. Anything
    else is an error the caller reports and skips.
    """
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, timeout=120, headers=headers)
    resp.raise_for_status()

    if _looks_like_pdf(resp):
        return resp.content

    pdf_url = _find_embedded_pdf(resp.text, resp.url)
    if not pdf_url:
        ctype = resp.headers.get("Content-Type", "") or "unknown"
        raise ValueError(
            f"expected a PDF but got {ctype} and found no embedded PDF link"
        )

    resp = requests.get(pdf_url, timeout=120, headers=headers)
    resp.raise_for_status()
    if not _looks_like_pdf(resp):
        raise ValueError(f"embedded link {pdf_url} did not return a PDF")
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
