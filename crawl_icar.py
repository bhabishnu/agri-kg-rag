"""
Crawl an ICAR journal page and ingest every article PDF it links to.

    python crawl_icar.py <url> [--limit N]

Point it at any of four page shapes on an OJS-based ICAR journal
(epubs.icar.org.in, e.g. "Indian Farming"):

  * an ARCHIVE page /issue/archive                   -> every issue, newest first
  * an ISSUE page   /issue/view/{id}                 -> every article in the issue
  * an ARTICLE page /article/view/{id}               -> that article's PDF
  * a direct GALLEY /article/view/{id}/{galleyId}    -> that PDF directly

The archive lists issues newest-first; `--limit N` takes only the newest N
issues (default: all). Each issue is then crawled through the same
issue -> article -> PDF-download path as a lone /issue/view/ URL.

The galley URL `/article/view/{id}/{galleyId}` is an HTML *viewer* shell, not the
PDF; the real bytes live at the sibling `/article/download/{id}/{galleyId}`. So we
resolve inputs down to galley view URLs first (an issue page is scraped for its
`/article/view/{id}` article links, and each article page for its "PDF" galley
link), then for each one fetch the `/article/download/` URL for the actual PDF.
If even that returns HTML, we fall back to scraping the viewer page for an
embedded PDF link (an iframe/embed src, or a link ending in .pdf / containing
/download/). The bytes then run through the SAME path demo_pdf.py uses:
pdf_sources.load_pdf_text (download + cache + extract + clean) ->
ingest.build_docs_from_pdf -> pipeline upsert.

Re-running is safe: cache/ skips re-downloading PDFs we already have, and the
deterministic ids in build_docs_from_pdf upsert in place instead of duplicating.

Scanned/image-only PDFs (no extractable text) and any PDF that errors out are
warned about and skipped — one bad PDF never aborts the whole run.

Honors USE_DUMMY_EMBEDDINGS=1 (fake vectors, no model download) just like ingest.py.
"""

import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config
import pdf_sources
import pipeline
import ingest


# Same User-Agent the rest of the project uses, plus a polite pause between
# network requests so we don't hammer the journal server.
USER_AGENT = "Mozilla/5.0 (M.Tech research project)"
REQUEST_DELAY = 1.0  # seconds between network requests

# OJS URL shapes, matched against the path only:
#   article page: /article/view/{id}            (one numeric segment)
#   PDF galley:   /article/view/{id}/{galleyId} (two numeric segments)
#   issue page:   /issue/view/{id}
GALLEY_RE = re.compile(r"/article/view/\d+/\d+/?$")
ARTICLE_RE = re.compile(r"/article/view/\d+/?$")
ISSUE_RE = re.compile(r"/issue/view/\d+")


def _fetch_soup(url):
    """GET a page and parse it, using the project User-Agent."""
    resp = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def collect_issue_urls(archive_url, limit=None):
    """Scrape the archive page for issue-page links (`/issue/view/{id}`).

    The archive lists issues newest-first, so we preserve page order and, when
    `limit` is given, keep only the first `limit` (newest) issues. Deduped,
    order-preserving (the archive links the same issue by its cover and title).
    """
    soup = _fetch_soup(archive_url)

    urls, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(archive_url, a["href"])
        if not ISSUE_RE.search(urlparse(full).path):
            continue
        if full not in seen:
            seen.add(full)
            urls.append(full)

    if limit is not None:
        urls = urls[:limit]
    return urls


def collect_article_urls(issue_url):
    """Scrape an issue page for its article-page links (`/article/view/{id}`).

    Deduped, order preserving (an issue page lists the same article link more
    than once — title, thumbnail, "PDF" button).
    """
    soup = _fetch_soup(issue_url)

    urls, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(issue_url, a["href"])
        if not ARTICLE_RE.search(urlparse(full).path):
            continue
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def resolve_article_galley(article_url):
    """Scrape an article page for its PDF galley URL, or return None.

    The galley link is an `<a>` whose href is `/article/view/{id}/{galleyId}`.
    An article can carry several galleys (PDF, HTML, ...), so we prefer the one
    labelled or classed "pdf" and only fall back to the first galley otherwise.
    """
    soup = _fetch_soup(article_url)

    candidates, preferred = [], []
    for a in soup.find_all("a", href=True):
        full = urljoin(article_url, a["href"])
        if not GALLEY_RE.search(urlparse(full).path):
            continue
        candidates.append(full)
        label = (a.get_text() or "") + " " + " ".join(a.get("class") or [])
        if "pdf" in label.lower():
            preferred.append(full)

    if preferred:
        return preferred[0]
    return candidates[0] if candidates else None


def resolve_galley_urls(url):
    """Turn any supported input URL into a list of PDF galley URLs to ingest."""
    path = urlparse(url).path

    if GALLEY_RE.search(path):
        return [url]  # already a direct PDF galley

    if ARTICLE_RE.search(path):
        galley = resolve_article_galley(url)
        return [galley] if galley else []

    if ISSUE_RE.search(path):
        article_urls = collect_article_urls(url)
        print(f"Found {len(article_urls)} article page(s) in the issue.\n")
        galleys = []
        for i, article_url in enumerate(article_urls, 1):
            print(f"  resolving [{i}/{len(article_urls)}] {article_url}")
            try:
                galley = resolve_article_galley(article_url)
            except Exception as e:
                print(f"      WARNING: could not resolve galley ({e}) — skipping.")
                galley = None
            if galley:
                print(f"      -> {galley}")
                galleys.append(galley)
            else:
                print("      WARNING: no PDF galley link found — skipping.")
            if i < len(article_urls):
                time.sleep(REQUEST_DELAY)  # be polite between page fetches
        return galleys

    print("WARNING: unrecognized URL shape; treating it as an article page.")
    galley = resolve_article_galley(url)
    return [galley] if galley else []


def find_embedded_pdf_link(viewer_url):
    """Fallback for when the `/download/` URL itself serves HTML.

    Scrape the galley viewer page for the real PDF: an `<iframe>`/`<embed>` whose
    `src` points at it, or an `<a>` link ending in `.pdf` or going through
    `/download/`. Returns the first match (absolute URL), or None.
    """
    soup = _fetch_soup(viewer_url)

    def is_pdf_link(full):
        return full.lower().split("?")[0].endswith(".pdf") or "/download/" in full

    for tag in soup.find_all(["iframe", "embed"]):
        src = tag.get("src")
        if src:
            full = urljoin(viewer_url, src)
            if is_pdf_link(full):
                return full

    for a in soup.find_all("a", href=True):
        full = urljoin(viewer_url, a["href"])
        if is_pdf_link(full):
            return full

    return None


def load_galley_text(view_url):
    """Download + extract the PDF for a galley VIEW url via its `/download/` URL.

    `/article/view/{a}/{g}` is an HTML viewer shell, not the PDF, so we fetch the
    sibling `/article/download/{a}/{g}` for the actual bytes. If even that serves
    HTML (Content-Type guard trips in pdf_sources), we fall back to scraping the
    viewer page for an embedded PDF link and try that. Returns extracted text, or
    None if no PDF link could be found. Logs each URL it tries.
    """
    download_url = view_url.replace("/article/view/", "/article/download/")
    print(f"      download: {download_url}")
    try:
        return pdf_sources.load_pdf_text(download_url)
    except pdf_sources.NotAPdfError as e:
        print(f"      download URL not a PDF ({e}); scraping viewer for an embedded PDF link…")

    embedded = find_embedded_pdf_link(view_url)
    if not embedded:
        print("      WARNING: no embedded PDF link found in viewer page.")
        return None
    print(f"      embedded: {embedded}")
    return pdf_sources.load_pdf_text(embedded)


def _parse_args(argv):
    """Pull an optional `--limit N` (or `--limit=N`) out of argv.

    Returns (url, limit); url is None if no positional URL was given. `--limit`
    only applies to archive crawls (it's ignored for other URL shapes).
    """
    url, limit = None, None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--limit":
            if i + 1 >= len(argv):
                print("Usage: --limit requires a number, e.g. --limit 5")
                sys.exit(1)
            limit = int(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
            i += 1
            continue
        if url is None:
            url = arg
        i += 1
    return url, limit


def main():
    url, limit = _parse_args(sys.argv[1:])
    if url is None:
        print("Usage: python crawl_icar.py <url> [--limit N]")
        print("  <url> = an /issue/archive, /issue/view/{id}, /article/view/{id},")
        print("          or /article/view/{id}/{galleyId} page")
        print("  --limit N = archive mode only: crawl the newest N issues")
        sys.exit(1)

    print(f"Crawling:\n  {url}\n")

    if "/issue/archive" in url:
        issue_urls = collect_issue_urls(url, limit)
        limit_note = f" (limited to newest {limit})" if limit is not None else ""
        print(f"Found {len(issue_urls)} issue(s) in the archive{limit_note}.\n")
        pdf_urls = []
        for i, issue_url in enumerate(issue_urls, 1):
            print(f"Issue [{i}/{len(issue_urls)}] {issue_url}")
            try:
                pdf_urls.extend(resolve_galley_urls(issue_url))
            except Exception as e:  # one bad issue never aborts the whole run
                print(f"  WARNING: could not crawl issue ({e}) — skipping.")
            if i < len(issue_urls):
                time.sleep(REQUEST_DELAY)  # be polite between issue pages
    else:
        pdf_urls = resolve_galley_urls(url)

    print(f"\nResolved {len(pdf_urls)} PDF galley URL(s).\n")

    coll = pipeline.get_collection()
    ingested, skipped = 0, 0

    for i, view_url in enumerate(pdf_urls, 1):
        print(f"[{i}/{len(pdf_urls)}] {view_url}")
        try:
            text = load_galley_text(view_url)
        except pdf_sources.NotAPdfError as e:  # HTML/other where we expected a PDF
            print(f"      WARNING: not a PDF ({e}) — skipping.")
            skipped += 1
            continue
        except Exception as e:  # network error, corrupt PDF, etc. — skip, don't crash
            print(f"      WARNING: failed to download/extract ({e}) — skipping.")
            skipped += 1
            continue

        if text is None:  # no PDF link found even after the viewer-page fallback
            skipped += 1
            continue

        if not text.strip():
            print("      WARNING: no text extracted (scanned/image-only?) — skipping.")
            skipped += 1
            continue

        docs = ingest.build_docs_from_pdf(text, source_url=view_url)
        pipeline.add_documents(coll, docs)
        print(f"      ingested {len(docs)} chunk(s).")
        ingested += 1

        if i < len(pdf_urls):
            time.sleep(REQUEST_DELAY)  # be polite between requests

    print("\n" + "=" * 60)
    print("Crawl summary")
    print("=" * 60)
    print(f"  PDFs found:    {len(pdf_urls)}")
    print(f"  PDFs ingested: {ingested}")
    print(f"  PDFs skipped:  {skipped}")
    print(f"  Collection '{config.COLLECTION}' now holds {coll.count()} items")
    print(f"  (persisted to {config.CHROMA_DIR})")


if __name__ == "__main__":
    main()
