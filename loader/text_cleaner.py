"""
text_cleaner.py
~~~~~~~~~~~~~~~
Utilities for cleaning raw book text and chunking it into LLM-friendly pieces.

Handles:
- Project Gutenberg header/footer boilerplate removal
- Table-of-contents stripping
- Whitespace normalisation
- Page-number line removal
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Gutenberg sentinel patterns
# ---------------------------------------------------------------------------

_PG_START_RE = re.compile(
    r"\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK\b.*",
    re.IGNORECASE,
)
_PG_END_RE = re.compile(
    r"\*{3}\s*END OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK\b.*",
    re.IGNORECASE,
)

# A line that looks like a bare page number: optional whitespace, digits only,
# optional trailing whitespace / Roman numerals.
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:[IVXLCDM]+|\d+)\s*$", re.IGNORECASE)

# Three or more consecutive blank lines.
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_gutenberg_boilerplate(text: str) -> str:
    """Remove Project Gutenberg header and footer blocks.

    Everything before (and including) the START sentinel and everything after
    (and including) the END sentinel is discarded.  If no sentinels are found
    the text is returned unchanged.
    """
    start_match = _PG_START_RE.search(text)
    if start_match:
        text = text[start_match.end():]

    end_match = _PG_END_RE.search(text)
    if end_match:
        text = text[: end_match.start()]

    return text


def _strip_table_of_contents(text: str) -> str:
    """Remove a leading table-of-contents block if one is detected.

    Detection heuristic: if the first 4 000 characters contain 3 or more
    lines that each match a "Chapter" heading pattern, that block is treated
    as a ToC and removed up to the first non-ToC paragraph.
    """
    # Only examine the opening portion of the text.
    preamble = text[:4000]
    chapter_lines = re.findall(
        r"^\s*(?:Chapter|CHAPTER|Chap\.?)\s+[\dIVXLCDM]+",
        preamble,
        re.MULTILINE | re.IGNORECASE,
    )

    if len(chapter_lines) < 3:
        return text  # No obvious ToC -- nothing to strip.

    # Find where the ToC block ends: the first blank line after the last ToC
    # chapter reference, then skip forward to real prose.
    last_chapter_match = None
    for m in re.finditer(
        r"^\s*(?:Chapter|CHAPTER|Chap\.?)\s+[\dIVXLCDM]+.*$",
        preamble,
        re.MULTILINE | re.IGNORECASE,
    ):
        last_chapter_match = m

    if last_chapter_match is None:
        return text

    # Find the next double-newline after the last ToC line.
    toc_end_pos = last_chapter_match.end()
    double_newline = text.find("\n\n", toc_end_pos)
    if double_newline == -1:
        return text

    return text[double_newline:].lstrip("\n")


def _remove_page_numbers(text: str) -> str:
    """Drop lines that consist solely of a page number (Arabic or Roman)."""
    lines = text.splitlines()
    filtered = [line for line in lines if not _PAGE_NUMBER_RE.match(line)]
    return "\n".join(filtered)


def _normalise_whitespace(text: str) -> str:
    """Collapse 3+ consecutive blank lines to 2 and normalise line endings."""
    # Normalise Windows / old-Mac line endings first.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse excessive blank lines.
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def clean_text(raw: str) -> str:
    """Clean raw book text.

    Steps applied in order:
    1. Strip Project Gutenberg header / footer boilerplate.
    2. Strip table of contents (if detected).
    3. Remove bare page-number lines.
    4. Normalise whitespace (collapse 3+ blank lines to 2, unify line endings).

    Parameters
    ----------
    raw:
        The raw text content of the book.

    Returns
    -------
    str
        Cleaned text, ready for further processing or LLM ingestion.
    """
    text = _strip_gutenberg_boilerplate(raw)
    text = _strip_table_of_contents(text)
    text = _remove_page_numbers(text)
    text = _normalise_whitespace(text)
    return text


def chunk_text(text: str, max_chars: int = 80_000) -> list[str]:
    """Split *text* into chunks of at most *max_chars* characters.

    Chunks are split on paragraph boundaries (double newlines) wherever
    possible so that LLM context windows receive coherent prose rather than
    mid-sentence cuts.  If a single paragraph exceeds *max_chars* it is split
    at the nearest whitespace before the limit.

    Parameters
    ----------
    text:
        The cleaned book text to chunk.
    max_chars:
        Maximum number of characters per chunk.  Defaults to 80 000, which
        fits comfortably inside a 32 k-token context window at ~4 chars/token.

    Returns
    -------
    list[str]
        Ordered list of text chunks.  Guaranteed to be non-empty even when
        *text* is an empty string (returns ['''''''']).
    """
    if not text:
        return [""]

    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # account for the '\n\n' separator

        if current_len + para_len > max_chars and current_parts:
            # Flush the current chunk.
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            current_len = 0

        if para_len > max_chars:
            # The paragraph itself is too long -- hard-split on whitespace.
            while para:
                space_idx = para.rfind(" ", 0, max_chars)
                if space_idx == -1:
                    # No whitespace found; force-cut at max_chars.
                    space_idx = max_chars
                chunks.append(para[:space_idx].strip())
                para = para[space_idx:].lstrip()
        else:
            current_parts.append(para)
            current_len += para_len

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


def detect_chapters(text: str, fallback_size: int = 15_000) -> list[dict]:
    """Split cleaned text into chapters using heading detection.
    
    Tries multiple heading patterns (Chapter X, CHAPTER X, Part X, etc).
    Filters out Table of Contents entries (chapters under 500 chars).
    Falls back to splitting at ~fallback_size character intervals on
    paragraph boundaries if no chapter headings are detected.
    
    Parameters
    ----------
    text:
        Cleaned book text.
    fallback_size:
        Target chunk size for fallback splitting when no chapters detected.
    
    Returns
    -------
    list[dict]
        Each dict has keys: 'number' (int), 'title' (str), 'text' (str),
        'char_count' (int).
    """
    import re
    
    # Heading patterns to try, in priority order
    _HEADING_PATTERNS = [
        # "Chapter 1", "CHAPTER I", "Chapter I.", "CHAPTER XIV - Title"
        r'\n\s*((?:CHAPTER|Chapter|Chap\.?)\s+[\dIVXLCDM]+[^\n]*)',
        # "Part 1", "PART II"
        r'\n\s*((?:PART|Part)\s+[\dIVXLCDM]+[^\n]*)',
        # "BOOK I", "Book 3"
        r'\n\s*((?:BOOK|Book)\s+[\dIVXLCDM]+[^\n]*)',
        # "Section 1"
        r'\n\s*((?:SECTION|Section)\s+[\dIVXLCDM]+[^\n]*)',
        # Bare Roman numeral on its own line (common in novellas)
        r'\n\s*([IVXLCDM]+)\s*\n',
    ]
    
    chapters = []
    
    for pattern in _HEADING_PATTERNS:
        matches = list(re.finditer(pattern, text))
        if len(matches) >= 2:  # need at least 2 headings to split
            for i, m in enumerate(matches):
                title = m.group(1).strip()
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                body = text[start:end].strip()
                chapters.append({
                    'number': i + 1,
                    'title': title,
                    'text': body,
                    'char_count': len(body),
                })
            # Filter out ToC entries (tiny "chapters" under 500 chars)
            real_chapters = [ch for ch in chapters if ch['char_count'] >= 500]
            if len(real_chapters) >= 2:
                # Re-number after filtering
                for i, ch in enumerate(real_chapters):
                    ch['number'] = i + 1
                return real_chapters
            chapters = []  # reset and try next pattern
    
    # Fallback: split on paragraph boundaries at ~fallback_size intervals
    if not chapters:
        paragraphs = text.split('\n\n')
        current_parts: list[str] = []
        current_len = 0
        chapter_num = 1
        
        for para in paragraphs:
            para_len = len(para) + 2
            if current_len + para_len > fallback_size and current_parts:
                body = '\n\n'.join(current_parts)
                chapters.append({
                    'number': chapter_num,
                    'title': f'Section {chapter_num}',
                    'text': body,
                    'char_count': len(body),
                })
                chapter_num += 1
                current_parts = []
                current_len = 0
            current_parts.append(para)
            current_len += para_len
        
        if current_parts:
            body = '\n\n'.join(current_parts)
            chapters.append({
                'number': chapter_num,
                'title': f'Section {chapter_num}',
                'text': body,
                'char_count': len(body),
            })
    
    return chapters

