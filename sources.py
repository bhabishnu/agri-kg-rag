"""
Where the data comes from.

Two sources, two different shapes of data:

  1. Agmarknet  -> STRUCTURED price rows, pulled from an official API.
  2. ICAR       -> UNSTRUCTURED advisory text, loaded from a file (and, when
                   you go live, scraped from the web with BeautifulSoup).

Note on prices: strictly speaking, price tables belong in a SQL table or the
knowledge graph (Neo4j) for exact lookups. For this starter we turn each price
row into a short SENTENCE (see price_to_text) so it can be embedded and
retrieved by the same RAG flow — that lets you see the whole pipeline end to
end with one store. Both approaches are valid; the README explains the trade.
"""

import json
import requests

import config


# ---------------------------------------------------------------------------
# 1. AGMARKNET  (structured prices via data.gov.in API)
# ---------------------------------------------------------------------------
def fetch_agmarknet(api_key, limit=50, use_sample=False,
                    sample_path="sample_data/agmarknet_sample.json"):
    """Return a list of normalized price dicts.

    use_sample=True reads the bundled sample file so you can run OFFLINE with
    no API key. Set it False (and pass your key) to hit the live API.
    """
    if use_sample:
        with open(sample_path, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        url = f"{config.DATA_GOV_BASE}/{config.DATA_GOV_RESOURCE_ID}"
        params = {"api-key": api_key, "format": "json", "limit": limit}
        resp = requests.get(url, params=params, timeout=120)
        resp.raise_for_status()
        raw = resp.json()

    records = raw.get("records", [])
    return [_normalize_price(r) for r in records]


def _normalize_price(r):
    """data.gov.in field names have shifted over the years, so look up each
    value defensively and fall back to None if it's missing."""
    def g(*keys):
        for k in keys:
            if k in r and r[k] not in ("", None, "NA"):
                return r[k]
        return None

    return {
        "state":        g("state", "State"),
        "district":     g("district", "District"),
        "market":       g("market", "Market"),
        "commodity":    g("commodity", "Commodity"),
        "variety":      g("variety", "Variety"),
        "arrival_date": g("arrival_date", "Arrival_Date"),
        "min_price":    g("min_price", "Min_Price"),
        "max_price":    g("max_price", "Max_Price"),
        "modal_price":  g("modal_price", "Modal_Price"),
    }


def price_to_text(p):
    """Structured row -> one natural-language sentence, so it can be embedded."""
    return (
        f"On {p.get('arrival_date')}, the price of {p.get('commodity')} "
        f"({p.get('variety') or 'NA'} variety) at {p.get('market')} market, "
        f"{p.get('district')}, {p.get('state')} was: modal "
        f"Rs {p.get('modal_price')}/quintal "
        f"(min Rs {p.get('min_price')}, max Rs {p.get('max_price')})."
    )


# ---------------------------------------------------------------------------
# 2. ICAR  (unstructured advisory text)
# ---------------------------------------------------------------------------
def load_icar_text(path="sample_data/icar_sample.txt"):
    """Load an advisory document from a local .txt file (used by the demo)."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def scrape_icar_page(url):
    """THE PATTERN you'll use for real sources (not run in the offline demo).

    Fetch a page and pull out the readable text. Real government/ICAR pages are
    messy, so you'll tune the tag-stripping per site. Always add a User-Agent
    and a polite delay between requests, and check the site's robots.txt.
    """
    from bs4 import BeautifulSoup

    resp = requests.get(
        url, timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (M.Tech research project)"},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Drop boilerplate that isn't real content.
    for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)
