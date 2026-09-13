"""
file_loader.py
~~~~~~~~~~~~~~
Loaders for user-uploaded book files.

Supported formats
-----------------
- ``.txt``  -- plain-text (UTF-8 with latin-1 fallback)
- ``.pdf``  -- PDF via PyMuPDF (``fitz``)
- ``.epub`` -- EPUB via ``ebooklib`` + ``BeautifulSoup``

All loaders pass their output through :func:`text_cleaner.clean_text` before
returning, so callers always receive normalised, boilerplate-free text.
"""

from __future__ import annotations

from pathlib import Path

from loader import text_cleaner

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: File extensions understood by :func:`load_file`.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".txt", ".pdf", ".epub"})


# ---------------------------------------------------------------------------
# Internal per-format loaders
# ---------------------------------------------------------------------------


def _load_txt(path: Path) -> str:
    """Read a plain-text file, trying UTF-8 then falling back to latin-1.

    Parameters
    ----------
    path:
        Absolute or relative path to the ``.txt`` file.

    Returns
    -------
    str
        Cleaned text content.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="latin-1")
    return text_cleaner.clean_text(raw)


def _load_pdf(path: Path) -> str:
    """Extract text from a PDF file using PyMuPDF.

    Each page's text is extracted individually and joined with newlines.

    Parameters
    ----------
    path:
        Absolute or relative path to the ``.pdf`` file.

    Returns
    -------
    str
        Cleaned concatenated text from all pages.

    Raises
    ------
    ImportError
        If PyMuPDF (``fitz``) is not installed.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is required to load PDF files. "
            "Install it with: pip install pymupdf"
        ) from exc

    pages: list[str] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            pages.append(page.get_text())

    raw = "\n".join(pages)
    return text_cleaner.clean_text(raw)


def _load_epub(path: Path) -> str:
    """Extract text from an EPUB file using ebooklib and BeautifulSoup.

    All ``ITEM_DOCUMENT`` spine items are processed; HTML tags are stripped
    before the text is passed to the cleaner.

    Parameters
    ----------
    path:
        Absolute or relative path to the ``.epub`` file.

    Returns
    -------
    str
        Cleaned plain-text extracted from the EPUB.

    Raises
    ------
    ImportError
        If ``ebooklib`` or ``beautifulsoup4`` are not installed.
    """
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as exc:
        raise ImportError(
            "ebooklib is required to load EPUB files. "
            "Install it with: pip install ebooklib"
        ) from exc

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise ImportError(
            "beautifulsoup4 is required to load EPUB files. "
            "Install it with: pip install beautifulsoup4"
        ) from exc

    book = epub.read_epub(str(path))
    sections: list[str] = []

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html_content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_content, "html.parser")
        sections.append(soup.get_text(separator="\n"))

    raw = "\n\n".join(sections)
    return text_cleaner.clean_text(raw)


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

#: Maps file suffixes to their loader functions.
_LOADERS = {
    ".txt": _load_txt,
    ".pdf": _load_pdf,
    ".epub": _load_epub,
}


def load_file(path: Path) -> str:
    """Load a book file and return cleaned plain text.

    Dispatches to the appropriate internal loader based on the file's suffix.

    Parameters
    ----------
    path:
        Path to the book file.  Must have a suffix in
        :data:`SUPPORTED_EXTENSIONS`.

    Returns
    -------
    str
        Cleaned text content of the book.

    Raises
    ------
    ValueError
        If the file's suffix is not in :data:`SUPPORTED_EXTENSIONS`.
    FileNotFoundError
        If *path* does not exist on disk.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Book file not found: {path}")

    suffix = path.suffix.lower()
    loader = _LOADERS.get(suffix)

    if loader is None:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file type {suffix!r}. "
            f"Supported extensions are: {supported}"
        )

    return loader(path)
