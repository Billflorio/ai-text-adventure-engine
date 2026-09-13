"""
gutenberg.py
~~~~~~~~~~~~
Client for Project Gutenberg book data.

Primary API: gutenberg.org's own catalog endpoints (always available).
Secondary API: gutendex.com REST API (richer JSON, but sometimes slow/down).

Falls back gracefully — if gutendex times out, search still works via
the Gutenberg catalog HTML scraper.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from loader import text_cleaner

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GUTENDEX_URL  = "https://gutendex.com"
_GUTENBERG_URL = "https://www.gutenberg.org"
_USER_AGENT    = "AIBookGame/1.0 (educational; contact via GitHub)"
_TIMEOUT_API   = 10   # gutendex — short, fail fast
_TIMEOUT_BOOK  = 60   # actual book download can be large

TOPIC_CHILDREN  = "children"
TOPIC_ADVENTURE = "adventure"
TOPIC_MYSTERY   = "mystery"
TOPIC_ROMANCE   = "romance"
TOPIC_HORROR    = "horror"

_TEXT_FORMAT_PREFERENCE = [
    "text/plain; charset=utf-8",
    "text/plain; charset=us-ascii",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _USER_AGENT})
    return s


def _pick_text_url(formats: dict[str, str]) -> str | None:
    for key in _TEXT_FORMAT_PREFERENCE:
        if key in formats:
            return formats[key]
    for key, url in formats.items():
        if key.startswith("text/plain"):
            return url
    return None


def _gutenberg_text_url(book_id: int) -> str:
    """Construct a direct plain-text download URL from Gutenberg's standard layout."""
    # Gutenberg stores texts at predictable URLs:
    # https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt  (UTF-8)
    # https://www.gutenberg.org/files/{id}/{id}-0.txt       (UTF-8 alternative)
    return f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"


def _parse_gutenberg_search_html(html: str, query: str) -> dict[str, Any]:
    """
    Parse Gutenberg's search results HTML into a gutendex-compatible dict.
    Returns {count, results: [{id, title, authors, formats, download_count}]}
    """
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Each book is in <li class="booklink">
    for li in soup.select("li.booklink"):
        a = li.select_one("span.title")
        link = li.select_one("a")
        author_tag = li.select_one("span.subtitle")

        if not link or not a:
            continue

        # Extract book ID from href like /ebooks/11
        href = link.get("href", "")
        m = re.search(r"/ebooks/(\d+)", href)
        if not m:
            continue

        book_id = int(m.group(1))
        title = a.get_text(strip=True)
        author_text = author_tag.get_text(strip=True) if author_tag else ""

        # Parse "Lastname, Firstname" format
        authors = []
        if author_text:
            for part in author_text.split(";"):
                part = part.strip()
                if part:
                    authors.append({"name": part, "birth_year": None, "death_year": None})

        results.append({
            "id": book_id,
            "title": title,
            "authors": authors,
            "subjects": [],
            "bookshelves": [],
            "languages": ["en"],
            "copyright": False,
            "download_count": 0,
            "formats": {
                "text/plain; charset=utf-8": _gutenberg_text_url(book_id),
                "image/jpeg": f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.cover.medium.jpg",
            },
        })

    # Try to get total count from the results header
    count_tag = soup.select_one("span.results")
    total = len(results)
    if count_tag:
        m = re.search(r"(\d[\d,]*)", count_tag.get_text())
        if m:
            total = int(m.group(1).replace(",", ""))

    return {"count": total, "next": None, "previous": None, "results": results}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_books(
    query: str = "",
    topic: str | None = None,
    language: str = "en",
    page: int = 1,
) -> dict[str, Any]:
    """
    Search Project Gutenberg books.

    Tries gutendex.com first (richer metadata). If it times out or errors,
    falls back to scraping gutenberg.org search directly.

    Returns a gutendex-compatible dict: {count, next, previous, results}.
    """
    # --- Try gutendex first (fast path) ---
    try:
        params: dict[str, Any] = {"languages": language, "page": page}
        if query:
            params["search"] = query
        if topic:
            params["topic"] = topic

        with _session() as s:
            r = s.get(f"{_GUTENDEX_URL}/books", params=params, timeout=_TIMEOUT_API)

        if r.ok:
            return r.json()
    except Exception:
        pass  # Fall through to Gutenberg scraper

    # --- Fallback: scrape gutenberg.org directly ---
    search_query = query or (topic or "")
    params = {
        "query": search_query,
        "submit_search": "Go!",
    }
    if topic:
        # Gutenberg's search understands subject keywords
        params["query"] = f"{query} {topic}".strip()

    with _session() as s:
        r = s.get(f"{_GUTENBERG_URL}/ebooks/search/", params=params, timeout=30)

    r.raise_for_status()
    return _parse_gutenberg_search_html(r.text, search_query)


def get_book_metadata(book_id: int) -> dict[str, Any]:
    """
    Get metadata for a single book.

    Tries gutendex first, falls back to a minimal constructed metadata dict
    pointing at the standard Gutenberg download URLs.
    """
    # --- Try gutendex ---
    try:
        with _session() as s:
            r = s.get(f"{_GUTENDEX_URL}/books/{book_id}", timeout=_TIMEOUT_API)
        if r.ok:
            return r.json()
    except Exception:
        pass

    # --- Fallback: construct metadata from known URL patterns ---
    # Fetch the Gutenberg book page to get title/author
    meta = _scrape_book_page(book_id)
    return meta


def _scrape_book_page(book_id: int) -> dict[str, Any]:
    """Scrape basic metadata from a Gutenberg book page."""
    with _session() as s:
        r = s.get(f"{_GUTENBERG_URL}/ebooks/{book_id}", timeout=30)

    soup = BeautifulSoup(r.text, "lxml")

    # Title
    title_tag = soup.select_one("h1[itemprop='name']") or soup.select_one("td[itemprop='headline']")
    title = title_tag.get_text(strip=True) if title_tag else f"Book {book_id}"

    # Author
    author_tags = soup.select("a[itemprop='creator']")
    authors = [{"name": a.get_text(strip=True), "birth_year": None, "death_year": None}
               for a in author_tags]

    return {
        "id": book_id,
        "title": title,
        "authors": authors,
        "subjects": [],
        "bookshelves": [],
        "languages": ["en"],
        "copyright": False,
        "download_count": 0,
        "formats": {
            "text/plain; charset=utf-8": _gutenberg_text_url(book_id),
            # Also try the /files/ path as alternative
            "text/plain; charset=us-ascii": f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt",
            "image/jpeg": f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.cover.medium.jpg",
        },
    }


def download_book_text(book_id: int, cache_dir: Path) -> str:
    """
    Download and cache the plain-text version of a book.

    Tries the standard Gutenberg cache URL first, then falls back to
    the /files/ path. Result is cleaned and cached locally.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{book_id}.txt"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    # Get metadata to find the best text URL
    metadata = get_book_metadata(book_id)
    formats = metadata.get("formats", {})

    # Build candidate URLs in preference order
    candidates = []
    text_url = _pick_text_url(formats)
    if text_url:
        candidates.append(text_url)
    # Always include these fallbacks
    candidates += [
        _gutenberg_text_url(book_id),
        f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt",
        f"https://www.gutenberg.org/files/{book_id}/{book_id}.txt",
    ]
    # Deduplicate preserving order
    seen = set()
    candidates = [u for u in candidates if not (u in seen or seen.add(u))]

    last_error = None
    for url in candidates:
        try:
            with _session() as s:
                r = s.get(url, timeout=_TIMEOUT_BOOK)
            if r.ok and len(r.content) > 1000:
                encoding = r.encoding or "utf-8"
                try:
                    raw = r.content.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    raw = r.content.decode("latin-1")
                cleaned = text_cleaner.clean_text(raw)
                cache_path.write_text(cleaned, encoding="utf-8")
                return cleaned
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        f"Could not download book {book_id}. "
        f"Tried {len(candidates)} URLs. Last error: {last_error}"
    )


def get_cover_url(book_metadata: dict[str, Any]) -> str | None:
    """Extract cover image URL from metadata."""
    formats = book_metadata.get("formats", {})
    return formats.get("image/jpeg")
