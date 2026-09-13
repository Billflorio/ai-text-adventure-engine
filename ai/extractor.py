"""
ai/extractor.py

Multi-pass chapter-aware story bible extraction.

Pipeline:
    1. detect_chapters() splits the book into chapters
    2. Per-chapter micro-extraction (one LLM call per chapter batch)
    3. Programmatic merge + LLM synthesis into a unified story bible

The content profile is injected into every LLM call so content filtering
happens during extraction itself.
"""
from __future__ import annotations

import json
import logging
import re
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai.model_router import ModelRouter
    from engine.content_profile import ContentProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema returned by extract_story_bible()
# ---------------------------------------------------------------------------
STORY_BIBLE_SCHEMA = {
    "title": "string",
    "author": "string",
    "setting": "string — one or two sentences describing the overall world/era",
    "tone": "string — e.g. 'whimsical, surreal, comedic'",
    "detected_audience": "string — one of: children_under_8, children_8_12, young_adult, adult",
    "detected_reading_level": "string — e.g. 'grade_4' or 'college'",
    "detected_content_flags": "array of strings — e.g. ['mild_peril', 'romantic_themes']",
    "suggested_content_profile": "string — one of: Strictly Clean, Family, Teen, Adult",
    "suggested_difficulty": "string — one of: easy, medium, hard, scholar",
    "summary": "string — 3-5 sentence plot summary",
    "characters": [
        {
            "id": "slug e.g. alice",
            "name": "Full Name",
            "role": "protagonist | antagonist | ally | guide | minor",
            "description": "physical description",
            "personality": "personality and speech patterns",
            "first_appears": "chapter or scene name",
        }
    ],
    "locations": [
        {
            "id": "slug e.g. rabbit_hole",
            "name": "Location Name",
            "description": "2-3 sentence atmospheric description",
            "connects_to": ["list of location id slugs"],
            "characters_here": ["list of character id slugs"],
            "items_here": ["list of item id slugs"],
            "key_event": "the main story event that happens here",
            "chapter_number": "which chapter this location is most prominent in",
        }
    ],
    "inventory_items": [
        {
            "id": "slug",
            "name": "Item Name",
            "description": "what it is and why it matters",
            "from_book": True,
        }
    ],
    "key_events": [
        "ordered list of major plot events as short strings"
    ],
    "narrative_acts": [
        {
            "act_number": 1,
            "title": "Act title",
            "chapter_range": "chapters 1-5",
            "summary": "what happens in this act",
            "locations": ["location_ids in this act"],
            "climax_event": "the turning point of this act",
        }
    ],
}


# ---------------------------------------------------------------------------
# Per-chapter micro-extraction prompt
# ---------------------------------------------------------------------------

_CHAPTER_SYSTEM = textwrap.dedent("""\
    You are a literary analyst extracting structured data from a single chapter
    of a book.  Be faithful to the source material.  Extract real characters,
    real locations, real items.  Do not invent content not in the text.

    Return ONLY valid JSON matching the schema provided.  No prose outside JSON.
""")

_CHAPTER_EXTRACT_SCHEMA = {
    "chapter_number": "int",
    "chapter_title": "string",
    "locations": [
        {
            "id": "slug",
            "name": "Location Name",
            "description": "1-2 sentence atmospheric description",
            "key_event": "the main story event that happens here",
        }
    ],
    "characters_present": [
        {
            "id": "slug",
            "name": "Full Name",
            "role": "protagonist | antagonist | ally | guide | minor",
            "description": "brief physical/personality description",
        }
    ],
    "items_mentioned": [
        {
            "id": "slug",
            "name": "Item Name",
            "description": "what it is and why it matters to the story",
        }
    ],
    "events": ["ordered list of major events in this chapter"],
    "content_flags": ["list of content flags: mild_peril, violence, romance, etc."],
}


# ---------------------------------------------------------------------------
# Synthesis prompt
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = textwrap.dedent("""\
    You are a literary analyst and game designer.  You have been given
    per-chapter extraction data from a complete novel.  Your job is to
    synthesise this into a unified story bible for a text adventure game.

    Merge duplicate characters and locations.  Build a chronological timeline.
    Divide the story into 3-5 narrative acts.

    Return ONLY valid JSON matching the schema provided.
""")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_story_bible(
    text: str | list[str],
    router: "ModelRouter",
    profile: "ContentProfile",
    known_title: str = "",
    known_author: str = "",
    progress_callback: Any = None,
) -> dict:
    """Extract a story bible from book text using multi-pass chapter extraction.

    Args:
        text: Full book text as string, or list of chunks for long books.
        router: Configured ModelRouter instance.
        profile: Active content profile.
        known_title: Title hint (from Gutenberg metadata).
        known_author: Author hint (from Gutenberg metadata).
        progress_callback: Optional callable(step: str, current: int, total: int)
            for progress reporting.

    Returns:
        Story bible dict.
    """
    from loader.text_cleaner import detect_chapters

    # Reassemble text if given as chunks
    if isinstance(text, list):
        full_text = "\n\n".join(text)
    else:
        full_text = text

    # --- Phase 1: Detect chapters ---
    chapters = detect_chapters(full_text)
    logger.info("Detected %d chapters in book", len(chapters))

    if progress_callback:
        progress_callback("Detected chapters", 0, len(chapters))

    # --- Phase 2: Per-chapter micro-extraction ---
    chapter_extractions = []
    content_injection = profile.build_system_prompt_injection()
    system_prompt = _CHAPTER_SYSTEM + "\n\n" + content_injection

    # Batch short chapters together (target ~12k chars per LLM call)
    batches = _batch_chapters(chapters, max_batch_chars=12_000)
    logger.info("Processing %d chapter batches", len(batches))

    for batch_idx, batch in enumerate(batches):
        if progress_callback:
            ch_nums = [ch["number"] for ch in batch]
            total_ch = len(chapters)
            if ch_nums[0] == ch_nums[-1]:
                msg = f"Extracting chapter {ch_nums[0]} of {total_ch}"
            else:
                msg = f"Extracting chapters {ch_nums[0]}-{ch_nums[-1]} of {total_ch}"
            
            progress_callback(msg, batch_idx + 1, len(batches))

        extraction = _extract_chapter_batch(batch, router, system_prompt, known_title)
        if isinstance(extraction, list):
            chapter_extractions.extend(extraction)
        else:
            chapter_extractions.append(extraction)

    logger.info("Extracted data from %d chapter batches", len(chapter_extractions))

    # --- Phase 3: Programmatic merge ---
    merged = _merge_extractions(chapter_extractions)

    # --- Phase 4: LLM synthesis into final bible ---
    if progress_callback:
        progress_callback("Scratching My Balls Scribbling the Walls", len(batches), len(batches))

    bible = _synthesize_bible(
        merged, router, profile, known_title, known_author
    )

    return bible


def _batch_chapters(
    chapters: list[dict], max_batch_chars: int = 12_000
) -> list[list[dict]]:
    """Group chapters into batches that fit within max_batch_chars."""
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_size = 0

    for ch in chapters:
        ch_size = ch["char_count"]
        if current_size + ch_size > max_batch_chars and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_size = 0

        # If a single chapter exceeds the limit, truncate it
        if ch_size > max_batch_chars:
            truncated = dict(ch)
            truncated["text"] = ch["text"][:max_batch_chars]
            truncated["char_count"] = max_batch_chars
            current_batch.append(truncated)
            current_size += max_batch_chars
        else:
            current_batch.append(ch)
            current_size += ch_size

    if current_batch:
        batches.append(current_batch)

    return batches


def _extract_chapter_batch(
    batch: list[dict],
    router: "ModelRouter",
    system_prompt: str,
    known_title: str,
) -> list[dict]:
    """Run micro-extraction on a batch of chapters."""
    schema_str = json.dumps(_CHAPTER_EXTRACT_SCHEMA, indent=2)

    # Build the chapter text for the prompt
    chapter_sections = []
    for ch in batch:
        header = f"--- CHAPTER {ch['number']}: {ch['title']} ---"
        chapter_sections.append(f"{header}\n{ch['text']}")

    combined_text = "\n\n".join(chapter_sections)

    title_hint = f"Book: {known_title}\n\n" if known_title else ""

    prompt = textwrap.dedent(f"""\
        {title_hint}Analyze the following chapter(s) and extract structured data.

        SCHEMA TO FOLLOW (return one JSON object per chapter in an array):
        {schema_str}

        RULES:
        - Extract ALL locations where scenes take place
        - Extract ALL named characters who appear or are mentioned
        - Extract ALL notable objects/items that could be game-relevant
        - List key events in chronological order
        - Use short lowercase slug IDs (e.g. "dark_forest", "old_man")
        - Be specific: use the book's actual names and terminology
        - If multiple chapters are provided, return an array of extraction objects

        CHAPTER TEXT:
        ---
        {combined_text}
        ---

        Return the extraction JSON now:
    """)

    try:
        raw = router.complete_json(prompt, system_prompt=system_prompt)
        # Normalise: if a single dict was returned, wrap in list
        if isinstance(raw, dict):
            return [raw]
        return raw if isinstance(raw, list) else [raw]
    except Exception as exc:
        logger.warning("Chapter extraction failed: %s", exc)
        # Return empty extraction so we don't lose progress
        return [
            {
                "chapter_number": batch[0]["number"],
                "chapter_title": batch[0]["title"],
                "locations": [],
                "characters_present": [],
                "items_mentioned": [],
                "events": [],
                "content_flags": [],
            }
        ]


def _merge_extractions(extractions: list[dict]) -> dict:
    """Programmatically merge per-chapter extractions into a unified dataset.

    Deduplicates characters and locations by ID, collecting all unique entries.
    """
    all_characters: dict[str, dict] = {}
    all_locations: dict[str, dict] = {}
    all_items: dict[str, dict] = {}
    all_events: list[str] = []
    all_content_flags: set[str] = set()

    for ext in extractions:
        ch_num = ext.get("chapter_number", "?")

        for char in ext.get("characters_present", []):
            cid = char.get("id", "")
            if cid and cid not in all_characters:
                char["first_appears"] = f"Chapter {ch_num}"
                all_characters[cid] = char

        for loc in ext.get("locations", []):
            lid = loc.get("id", "")
            if lid and lid not in all_locations:
                loc["chapter_number"] = ch_num
                all_locations[lid] = loc

        for item in ext.get("items_mentioned", []):
            iid = item.get("id", "")
            if iid and iid not in all_items:
                all_items[iid] = item

        for event in ext.get("events", []):
            if isinstance(event, str) and event not in all_events:
                all_events.append(event)

        for flag in ext.get("content_flags", []):
            if isinstance(flag, str):
                all_content_flags.add(flag)

    return {
        "characters": list(all_characters.values()),
        "locations": list(all_locations.values()),
        "items": list(all_items.values()),
        "events": all_events,
        "content_flags": sorted(all_content_flags),
        "chapter_count": len(extractions),
    }


def _synthesize_bible(
    merged: dict,
    router: "ModelRouter",
    profile: "ContentProfile",
    known_title: str,
    known_author: str,
) -> dict:
    """Use one LLM call to synthesize merged data into the final story bible."""
    content_injection = profile.build_system_prompt_injection()
    system_prompt = _SYNTHESIS_SYSTEM + "\n\n" + content_injection

    schema_str = json.dumps(STORY_BIBLE_SCHEMA, indent=2)

    # Trim merged data if too large for context
    merged_str = json.dumps(merged, indent=1)
    if len(merged_str) > 15000:
        merged_str = merged_str[:15000] + "\n... (truncated)"

    title_hint = ""
    if known_title:
        title_hint = f"Title: {known_title}\n"
    if known_author:
        title_hint += f"Author: {known_author}\n"

    prompt = textwrap.dedent(f"""\
        {title_hint}
        Below is per-chapter extraction data from the COMPLETE novel
        ({merged['chapter_count']} chapters analysed).

        EXTRACTED DATA:
        {merged_str}

        Using this data, produce a unified story bible JSON.

        TARGET SCHEMA:
        {schema_str}

        RULES:
        - Merge duplicate characters (same person mentioned in different chapters)
        - Merge duplicate locations (same place referenced differently)
        - Build a chronological timeline of key_events covering the ENTIRE plot
        - Divide the story into 3-5 narrative_acts (setup, rising action, climax, etc.)
        - Each act should list which location IDs belong to it
        - Extract 5-15 inventory_items that could be used as game objects
        - The summary should cover the COMPLETE story arc, not just the beginning
        - detected_audience should reflect the book's actual target readership

        Return the story bible JSON now:
    """)

    try:
        bible = router.complete_json(prompt, system_prompt=system_prompt)
    except Exception as exc:
        logger.error("Bible synthesis failed: %s", exc)
        # Fall back to a minimal bible from merged data
        bible = {
            "title": known_title or "Unknown",
            "author": known_author or "Unknown",
            "setting": "",
            "tone": "",
            "detected_audience": "adult",
            "detected_reading_level": "college",
            "detected_content_flags": merged.get("content_flags", []),
            "suggested_content_profile": "Teen",
            "suggested_difficulty": "medium",
            "summary": " ".join(merged.get("events", [])[:5]),
            "characters": merged.get("characters", []),
            "locations": merged.get("locations", []),
            "inventory_items": merged.get("items", []),
            "key_events": merged.get("events", []),
            "narrative_acts": [],
        }

    # Ensure title/author are set even if LLM omitted them
    if known_title:
        bible.setdefault("title", known_title)
    if known_author:
        bible.setdefault("author", known_author)

    return bible


# ---------------------------------------------------------------------------
# Persistence helpers (unchanged)
# ---------------------------------------------------------------------------


def save_story_bible(bible: dict, games_dir: Path, book_id: str) -> Path:
    """Save story bible JSON to disk."""
    path = games_dir / f"{book_id}_bible.json"
    path.write_text(
        json.dumps(bible, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def load_story_bible(games_dir: Path, book_id: str) -> dict | None:
    """Load a previously saved story bible, or None if not found."""
    path = games_dir / f"{book_id}_bible.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
