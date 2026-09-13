"""
ai/game_generator.py

Takes a story bible (from extractor.py) and generates a full playable game
world using act-based generation with difficulty-scaled room counts and
puzzle complexity.

Architecture:
    1. Calculate target room count from chapters × difficulty multiplier
    2. Group bible's narrative_acts (or create them from events)
    3. Generate each act's rooms in a separate LLM call
    4. Stitch acts together with connecting exits
    5. Hydrate into Pydantic models with full item metadata
"""
from __future__ import annotations

import json
import logging
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from engine.game_state import (
    Character,
    GameWorld,
    InventoryItem,
    Location,
    StoryObstacle,
)

if TYPE_CHECKING:
    from ai.model_router import ModelRouter
    from engine.content_profile import ContentProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Difficulty configuration
# ---------------------------------------------------------------------------

DIFFICULTY_CONFIG = {
    "easy": {
        "room_multiplier": 1.5,
        "obstacles_per_act": 1,
        "items_per_obstacle": 1,
        "obstacle_desc": (
            "Challenges should be simple and linear. Each obstacle requires "
            "exactly ONE item to overcome, and that item should be found in "
            "the SAME room or an ADJACENT room. No backtracking needed."
        ),
    },
    "medium": {
        "room_multiplier": 2.0,
        "obstacles_per_act": 2,
        "items_per_obstacle": 1,
        "obstacle_desc": (
            "Challenges should require light exploration. Items needed to overcome "
            "obstacles may be found 1-2 rooms away, requiring the player to "
            "explore nearby areas. Occasional backtracking is expected."
        ),
    },
    "hard": {
        "room_multiplier": 2.5,
        "obstacles_per_act": 3,
        "items_per_obstacle": 2,
        "obstacle_desc": (
            "Challenges should require significant exploration and planning. "
            "Obstacles may require 2 items from different parts of the map. "
            "Some items are only available after talking to NPCs or overcoming "
            "earlier obstacles. Players must explore branching paths."
        ),
    },
    "scholar": {
        "room_multiplier": 3.0,
        "obstacles_per_act": 4,
        "items_per_obstacle": 3,
        "obstacle_desc": (
            "Challenges should be deeply layered and multi-step. Obstacles "
            "require 2-4 items, some of which must be COMBINED to create "
            "solution items. NPCs provide critical clues. Players must "
            "revisit rooms as the world state changes. Include at least one "
            "obstacle that requires combining two items into a new item."
        ),
    },
}


def _calculate_room_count(chapter_count: int, difficulty: str) -> int:
    """Calculate total rooms based on chapter count and difficulty.

    Formula: clamp(round(min(chapters, 12) × multiplier), 8, 35)
    """
    config = DIFFICULTY_CONFIG.get(difficulty, DIFFICULTY_CONFIG["medium"])
    base = min(chapter_count, 12)
    total = round(base * config["room_multiplier"])
    return max(8, min(total, 35))


# ---------------------------------------------------------------------------
# Generation prompt
# ---------------------------------------------------------------------------

_GENERATOR_SYSTEM = textwrap.dedent("""\
    You are an AI Dungeon Master generating a procedural text adventure from
    a story bible. Your job is to translate the book's narrative into a
    static map with natural, diegetic challenges and obstacles.

    CRITICAL RULE: Do NOT generate literal "game puzzles" (like jigsaw puzzles,
    sliding tiles, riddles, or math problems) unless they are literally
    described in the book's plot. The challenges MUST be natural situational
    obstacles that fit the narrative (e.g., "The door is locked", "The captain
    refuses to sail without payment", "The guard is blocking the path", "The
    wagon wheel is broken").

    The game should be different on every generation, featuring unique
    situational challenges inspired by the book's events. The player will NOT
    be quizzed with trivia. 

    Return ONLY valid JSON. No prose outside the JSON.
""")


def generate_game_world(
    bible: dict,
    router: "ModelRouter",
    profile: "ContentProfile",
    progress_callback: Any = None,
) -> GameWorld:
    """Generate a full GameWorld from a story bible.

    Uses act-based generation: splits the bible into narrative acts and
    generates each act's rooms in a separate LLM call, then stitches them
    together.
    """
    difficulty = profile.difficulty
    config = DIFFICULTY_CONFIG.get(difficulty, DIFFICULTY_CONFIG["medium"])

    # Calculate room count from chapter count
    chapter_count = len(bible.get("narrative_acts", [])) or 1
    # Use number of locations in bible as secondary signal
    bible_locations = len(bible.get("locations", []))
    effective_chapters = max(chapter_count, bible_locations // 2, 3)
    total_rooms = _calculate_room_count(effective_chapters, difficulty)

    logger.info(
        "Generating world: %d rooms (difficulty=%s, chapters=%d)",
        total_rooms, difficulty, effective_chapters,
    )

    # Get narrative acts from bible, or create default acts
    acts = bible.get("narrative_acts", [])
    if not acts or len(acts) < 2:
        acts = _create_default_acts(bible, total_rooms)

    # Distribute rooms across acts
    rooms_per_act = _distribute_rooms(total_rooms, len(acts))

    # Generate each act
    all_rooms: dict[str, dict] = {}
    all_characters: dict[str, dict] = {}
    all_items: dict[str, dict] = {}
    all_obstacles: dict[str, dict] = {}
    last_act_exit_room: str | None = None

    content_injection = profile.build_system_prompt_injection()
    system = _GENERATOR_SYSTEM + "\n\n" + content_injection

    bible_str = json.dumps(bible, indent=1)
    if len(bible_str) > 12000:
        bible_str = bible_str[:12000] + "\n..."

    for act_idx, act in enumerate(acts):
        act_room_count = rooms_per_act[act_idx]
        if act_room_count < 1:
            continue

        if progress_callback:
            progress_callback(
                f"Generating Act {act_idx + 1}: {act.get('title', '')}",
                act_idx + 1,
                len(acts),
            )

        act_data = _generate_act(
            act=act,
            act_index=act_idx,
            total_acts=len(acts),
            room_count=act_room_count,
            bible_str=bible_str,
            difficulty=difficulty,
            config=config,
            router=router,
            system_prompt=system,
            connect_from_room=last_act_exit_room,
        )

        act_rooms = act_data.get("locations", {})
        all_rooms.update(act_rooms)
        all_characters.update(act_data.get("characters", {}))
        all_items.update(act_data.get("items", {}))
        all_obstacles.update(act_data.get("obstacles", {}))

        # Track last room for inter-act connections
        if act_rooms:
            last_act_exit_room = list(act_rooms.keys())[-1]

    # Build the complete world
    starting = bible.get("starting_location_id", "")
    if not starting or starting not in all_rooms:
        starting = list(all_rooms.keys())[0] if all_rooms else ""

    raw_world = {
        "book_title": bible.get("title", "Unknown"),
        "book_author": bible.get("author", "Unknown"),
        "story_summary": bible.get("summary", ""),
        "starting_location_id": starting,
        "locations": all_rooms,
        "characters": all_characters,
        "items": all_items,
        "obstacles": all_obstacles,
    }

    return _hydrate_world(raw_world)


def _create_default_acts(bible: dict, total_rooms: int) -> list[dict]:
    """Create 3 default narrative acts if the bible doesn't have them."""
    events = bible.get("key_events", [])
    locations = bible.get("locations", [])

    # Split events into 3 acts
    third = max(len(events) // 3, 1)
    return [
        {
            "act_number": 1,
            "title": "The Beginning",
            "summary": " ".join(events[:third]) if events else "The story begins.",
            "locations": [l.get("id", "") for l in locations[:len(locations)//3]],
            "climax_event": events[third - 1] if events else "",
        },
        {
            "act_number": 2,
            "title": "The Journey",
            "summary": " ".join(events[third:2*third]) if events else "The adventure continues.",
            "locations": [l.get("id", "") for l in locations[len(locations)//3:2*len(locations)//3]],
            "climax_event": events[2*third - 1] if len(events) > third else "",
        },
        {
            "act_number": 3,
            "title": "The Resolution",
            "summary": " ".join(events[2*third:]) if events else "The story concludes.",
            "locations": [l.get("id", "") for l in locations[2*len(locations)//3:]],
            "climax_event": events[-1] if events else "",
        },
    ]


def _distribute_rooms(total_rooms: int, num_acts: int) -> list[int]:
    """Distribute rooms across acts, giving more to middle acts."""
    if num_acts <= 0:
        return []
    if num_acts == 1:
        return [total_rooms]

    base = total_rooms // num_acts
    remainder = total_rooms % num_acts
    distribution = [base] * num_acts

    # Give extra rooms to middle acts (the meat of the story)
    mid = num_acts // 2
    for i in range(remainder):
        distribution[mid + i % num_acts] += 1

    # Ensure at least 2 rooms per act
    for i in range(len(distribution)):
        distribution[i] = max(2, distribution[i])

    return distribution


def _generate_act(
    act: dict,
    act_index: int,
    total_acts: int,
    room_count: int,
    bible_str: str,
    difficulty: str,
    config: dict,
    router: "ModelRouter",
    system_prompt: str,
    connect_from_room: str | None,
) -> dict:
    """Generate one act's worth of rooms, characters, items, and obstacles."""
    obstacles_count = config["obstacles_per_act"]
    items_per_obs = config["items_per_obstacle"]
    obstacle_desc = config["obstacle_desc"]

    connection_rule = ""
    if connect_from_room:
        connection_rule = (
            f'\n- The FIRST location in this act MUST have an exit connecting '
            f'back to "{connect_from_room}" from the previous act (use direction '
            f'"south" or "west" for the backward connection).'
        )

    combination_schema = ""
    if difficulty == "scholar":
        combination_schema = textwrap.dedent("""\
            "item_combinations": {
              "<combination_id>": {
                "item1_id": "first item to combine",
                "item2_id": "second item to combine",
                "produces_id": "the new item created",
                "produces_name": "New Item Name",
                "produces_description": "what the combined item is"
              }
            },
        """)

    prompt = textwrap.dedent(f"""\
        Generate Act {act_index + 1} of {total_acts} for this text adventure game.

        STORY BIBLE (summary):
        {bible_str}

        THIS ACT:
        Title: {act.get('title', f'Act {act_index + 1}')}
        Summary: {act.get('summary', '')}
        Key event: {act.get('climax_event', '')}

        Generate a JSON object with this structure:
        {{
          "locations": {{
            "<location_id>": {{
              "id": "<location_id>",
              "name": "Location Name",
              "description": "Rich 2-4 sentence description in second person (You see...). DO NOT mention obstacles.",
              "image_path": null,
              "exits": {{"north": "other_id", "east": "..."}},
              "characters_present": ["character_id"],
              "items_present": ["item_id"],
              "visited": false
            }}
          }},
          "characters": {{
            "<character_id>": {{
              "id": "<character_id>",
              "name": "Character Name",
              "role": "protagonist|antagonist|ally|guide|minor",
              "description": "...",
              "personality": "...",
              "location_id": "<location_id>",
              "dialogue_history": []
            }}
          }},
          "items": {{
            "<item_id>": {{
              "id": "<item_id>",
              "name": "Item Name",
              "description": "what it is and why it matters",
              "from_book": true
            }}
          }},
          {combination_schema}
          "obstacles": {{
            "<obstacle_id>": {{
              "id": "<obstacle_id>",
              "location_id": "<location_id>",
              "obstacle_description": "A diegetic description of what blocks progress",
              "solution_theme": "How to solve it (e.g. 'Use the silver key on the locked door')",
              "passed": false
            }}
          }}
        }}

        RULES:
        - Generate exactly {room_count} locations for this act
        - Generate exactly {obstacles_count} obstacles
        - Each obstacle should require {items_per_obs} item(s) to solve
        - {obstacle_desc}
        - Exits MUST be bidirectional (if A goes north to B, B goes south to A)
        - The protagonist from the bible should NOT appear as an NPC
        - Location IDs should be unique slug strings (e.g. "dark_cave_act2")
        - Item IDs should be unique slug strings{connection_rule}

        Generate the act JSON now:
    """)

    try:
        raw = router.complete_json(prompt, system_prompt=system_prompt)
    except Exception as exc:
        logger.error("Act %d generation failed: %s", act_index + 1, exc)
        raw = {"locations": {}, "characters": {}, "items": {}, "obstacles": {}}

    # Handle item combinations for Scholar difficulty
    if difficulty == "scholar" and "item_combinations" in raw:
        _apply_combinations(raw)

    return raw


def _apply_combinations(raw: dict) -> None:
    """Process item_combinations from Scholar difficulty into item metadata."""
    combinations = raw.pop("item_combinations", {})
    items = raw.setdefault("items", {})

    for _combo_id, combo in combinations.items():
        item1_id = combo.get("item1_id", "")
        item2_id = combo.get("item2_id", "")
        produces_id = combo.get("produces_id", "")
        produces_name = combo.get("produces_name", "Combined Item")
        produces_desc = combo.get("produces_description", "")

        # Mark items as combinable
        if item1_id in items:
            items[item1_id].setdefault("combines_with", []).append(item2_id)
            items[item1_id]["produces"] = produces_id
        if item2_id in items:
            items[item2_id].setdefault("combines_with", []).append(item1_id)
            items[item2_id]["produces"] = produces_id

        # Add the produced item to the items registry (not placed in world)
        if produces_id and produces_id not in items:
            items[produces_id] = {
                "id": produces_id,
                "name": produces_name,
                "description": produces_desc,
                "from_book": False,
                "combines_with": [],
                "produces": "",
            }


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------


def _hydrate_world(raw: dict) -> GameWorld:
    """Convert raw generator JSON into typed GameWorld model."""
    locations = {}
    for loc_id, loc_data in raw.get("locations", {}).items():
        try:
            locations[loc_id] = Location(**loc_data)
        except Exception as exc:
            logger.warning("Skipping invalid location %s: %s", loc_id, exc)

    # Enforce bidirectional exits
    opposites = {
        "north": "south", "south": "north",
        "east": "west", "west": "east",
        "up": "down", "down": "up",
    }
    for loc_id, loc in locations.items():
        for direction, dest_id in list(loc.exits.items()):
            if dest_id in locations and direction in opposites:
                opp = opposites[direction]
                if opp not in locations[dest_id].exits:
                    locations[dest_id].exits[opp] = loc_id

    characters = {}
    for char_id, char_data in raw.get("characters", {}).items():
        try:
            characters[char_id] = Character(**char_data)
        except Exception as exc:
            logger.warning("Skipping invalid character %s: %s", char_id, exc)

    items = {}
    for item_id, item_data in raw.get("items", {}).items():
        try:
            items[item_id] = InventoryItem(**item_data)
        except Exception as exc:
            logger.warning("Skipping invalid item %s: %s", item_id, exc)

    obstacles = {}
    for obs_id, obs_data in raw.get("obstacles", {}).items():
        try:
            obstacles[obs_id] = StoryObstacle(**obs_data)
        except Exception as exc:
            logger.warning("Skipping invalid obstacle %s: %s", obs_id, exc)

    return GameWorld(
        book_title=raw.get("book_title", "Unknown"),
        book_author=raw.get("book_author", "Unknown"),
        story_summary=raw.get("story_summary", ""),
        starting_location_id=raw.get("starting_location_id", ""),
        locations=locations,
        characters=characters,
        obstacles=obstacles,
        items=items,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def save_game_world(world: GameWorld, games_dir: Path, book_id: str) -> Path:
    """Persist the generated game world to disk."""
    path = games_dir / f"{book_id}_world.json"
    path.write_text(world.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_game_world(games_dir: Path, book_id: str) -> GameWorld | None:
    """Load a previously generated game world."""
    path = games_dir / f"{book_id}_world.json"
    if not path.exists():
        return None
    return GameWorld.model_validate_json(path.read_text(encoding="utf-8"))
