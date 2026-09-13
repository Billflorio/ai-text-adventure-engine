"""
ai/image_generator.py

Generates scene art for each game location using the configured image backend.
Images are cached — a location is only generated once per game world.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.image_router import ImageRouter
    from engine.content_profile import ContentProfile


# Negative prompt used for all generations (can be tuned per profile)
_BASE_NEGATIVE = (
    "blurry, bad anatomy, text, watermark, signature, logo, "
    "ugly, deformed, low quality, jpeg artifacts"
)


def generate_location_image(
    location_id: str,
    location_name: str,
    location_description: str,
    book_title: str,
    tone: str,
    router: "ImageRouter",
    profile: "ContentProfile",
    images_dir: Path,
) -> Path | None:
    """
    Generate (or return cached) scene art for a game location.

    Args:
        location_id: Unique slug for the location.
        location_name: Human-readable name.
        location_description: Atmospheric description from game world.
        book_title: Source book title (for context).
        tone: Book tone string e.g. 'whimsical, adventurous'.
        router: Configured ImageRouter.
        profile: Active content profile (controls art style).
        images_dir: Directory to cache images in.

    Returns:
        Path to saved image, or None if image backend is disabled.
    """
    # Use deterministic filename based on location_id
    safe_id = "".join(c for c in location_id if c.isalnum() or c == "_")
    image_path = images_dir / f"{safe_id}.png"

    # Return cached image if it exists
    if image_path.exists():
        return image_path

    # Build prompt
    style_suffix = profile.build_image_prompt_suffix()
    prompt = (
        f"Scene from '{book_title}': {location_name}. "
        f"{location_description} "
        f"Tone: {tone}. "
        f"{style_suffix}"
    )

    # Negative prompt from profile level
    negative = _BASE_NEGATIVE
    if profile.content_level <= 2:
        negative += ", adult content, violence, scary, disturbing"

    result_path = router.generate(
        prompt=prompt,
        negative_prompt=negative,
        save_path=image_path,
    )
    return result_path


def generate_all_location_images(
    world_dict: dict,
    bible: dict,
    router: "ImageRouter",
    profile: "ContentProfile",
    images_dir: Path,
    progress_callback=None,
) -> dict[str, Path | None]:
    """
    Generate images for all locations in the game world.

    Args:
        world_dict: Raw game world dict (or GameWorld.model_dump()).
        bible: Story bible dict (for tone).
        router: ImageRouter instance.
        profile: Active content profile.
        images_dir: Cache directory.
        progress_callback: Optional callable(current, total, location_name).

    Returns:
        Dict mapping location_id -> image Path (or None).
    """
    locations = world_dict.get("locations", {})
    tone = bible.get("tone", "adventurous")
    book_title = world_dict.get("book_title", "")
    results: dict[str, Path | None] = {}

    total = len(locations)
    for i, (loc_id, loc_data) in enumerate(locations.items()):
        if progress_callback:
            progress_callback(i, total, loc_data.get("name", loc_id))

        path = generate_location_image(
            location_id=loc_id,
            location_name=loc_data.get("name", loc_id),
            location_description=loc_data.get("description", ""),
            book_title=book_title,
            tone=tone,
            router=router,
            profile=profile,
            images_dir=images_dir,
        )
        results[loc_id] = path

    return results
