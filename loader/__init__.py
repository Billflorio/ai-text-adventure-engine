"""
loader
~~~~~~
Book-loading layer for the AI Book-to-Game Engine.

Sub-modules
-----------
text_cleaner  -- Raw text cleaning and chunking utilities.
gutenberg     -- Gutendex API client for Project Gutenberg books.
file_loader   -- Loader for user-uploaded TXT / PDF / EPUB files.
"""

from loader.file_loader import SUPPORTED_EXTENSIONS, load_file
from loader.gutenberg import (
    TOPIC_ADVENTURE,
    TOPIC_CHILDREN,
    TOPIC_HORROR,
    TOPIC_MYSTERY,
    TOPIC_ROMANCE,
    download_book_text,
    get_book_metadata,
    get_cover_url,
    search_books,
)
from loader.text_cleaner import chunk_text, clean_text

__all__ = [
    # text_cleaner
    "clean_text",
    "chunk_text",
    # gutenberg
    "search_books",
    "get_book_metadata",
    "download_book_text",
    "get_cover_url",
    "TOPIC_CHILDREN",
    "TOPIC_ADVENTURE",
    "TOPIC_MYSTERY",
    "TOPIC_ROMANCE",
    "TOPIC_HORROR",
    # file_loader
    "load_file",
    "SUPPORTED_EXTENSIONS",
]
