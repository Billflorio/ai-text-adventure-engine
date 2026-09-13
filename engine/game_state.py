"""
engine/game_state.py
---------------------
Game world and player state management for the AI Book-to-Game Engine.

Pydantic v2 models define the full save-file schema. ``GameStateManager``
provides new-game creation, save/load, and save-slot enumeration backed by
JSON files on disk.

Typical usage::

    manager = GameStateManager(saves_dir=Path("data/saves"))
    save = manager.new_game(world, start_loc="loc_hobbit_hole", profile_name="Default")
    manager.save(save, slot="slot1")
    save = manager.load("slot1")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Character(BaseModel):
    """An NPC or major character extracted from the source book."""

    id: str
    name: str
    role: str                          # e.g. 'protagonist', 'antagonist', 'mentor'
    description: str
    personality: str
    location_id: str | None = None     # None means the character is 'off-screen'
    dialogue_history: list[str] = Field(default_factory=list)


class Location(BaseModel):
    """A navigable place in the game world."""

    id: str
    name: str
    description: str
    image_path: str | None = None
    exits: dict[str, str] = Field(default_factory=dict)          # direction -> location_id
    characters_present: list[str] = Field(default_factory=list)  # character ids
    items_present: list[str] = Field(default_factory=list)       # item ids
    visited: bool = False


class InventoryItem(BaseModel):
    """An item the player can carry."""
    id: str
    name: str
    description: str
    from_book: bool = True
    combines_with: list[str] = Field(default_factory=list)  # item IDs this can combine with
    produces: str = ""  # item ID produced when combined


class StoryObstacle(BaseModel):
    """A diegetic obstacle blocking progress, requiring an action to overcome."""

    id: str
    location_id: str
    obstacle_description: str
    solution_theme: str
    passed: bool = False


class GameWorld(BaseModel):
    """Static generated data about the game world."""
    book_title: str
    book_author: str
    story_summary: str
    starting_location_id: str = ""
    locations: dict[str, Location]
    characters: dict[str, Character]
    obstacles: dict[str, StoryObstacle]
    items: dict[str, InventoryItem] = Field(default_factory=dict)


class PlayerState(BaseModel):
    """Mutable player state that changes as the game is played."""

    current_location_id: str
    inventory: list[InventoryItem] = Field(default_factory=list)
    score: int = 0
    obstacles_passed: list[str] = Field(default_factory=list)
    move_count: int = 0


class SaveFile(BaseModel):
    """Top-level container persisted to disk for each save slot."""

    world: GameWorld
    player: PlayerState
    profile_name: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# GameStateManager
# ---------------------------------------------------------------------------

class GameStateManager:
    """Manages creation, persistence, and retrieval of save files.

    Save files are stored as pretty-printed JSON files inside ``saves_dir``.
    Each save slot maps to a single file named ``<slot>.json``.

    Parameters
    ----------
    saves_dir:
        Directory where save files are stored. Created automatically if it
        does not exist.
    """

    def __init__(self, saves_dir: Path) -> None:
        self.saves_dir = Path(saves_dir)
        self.saves_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _slot_path(self, slot: str) -> Path:
        """Return the filesystem path for a given save slot."""
        # Sanitise slot name to avoid path-traversal issues.
        safe = "".join(c for c in slot if c.isalnum() or c in ("-", "_"))
        if not safe:
            safe = "autosave"
        return self.saves_dir / f"{safe}.json"

    @staticmethod
    def _utcnow() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def new_game(
        self,
        world: GameWorld,
        player_start_location: str,
        profile_name: str,
    ) -> SaveFile:
        """Create a fresh save file for a new game.

        Parameters
        ----------
        world:
            The fully constructed :class:`GameWorld` for the book.
        player_start_location:
            The ``id`` of the :class:`Location` where the player begins.
        profile_name:
            Name of the active :class:`ContentProfile`.

        Returns
        -------
        SaveFile
            A new save file with an empty player state.

        Raises
        ------
        ValueError
            If ``player_start_location`` is not a valid location id in ``world``.
        """
        if player_start_location not in world.locations:
            raise ValueError(
                f"Start location {player_start_location!r} not found in world. "
                f"Available: {list(world.locations)}"
            )
        now = self._utcnow()
        player = PlayerState(current_location_id=player_start_location)
        return SaveFile(
            world=world,
            player=player,
            profile_name=profile_name,
            created_at=now,
            updated_at=now,
        )

    def save(self, save: SaveFile, slot: str = "autosave") -> Path:
        """Persist a :class:`SaveFile` to disk.

        Parameters
        ----------
        save:
            The save file to write.
        slot:
            Slot name (alphanumeric, hyphens, underscores only). Defaults to
            ``'autosave'``.

        Returns
        -------
        Path
            The path where the save file was written.
        """
        save.updated_at = self._utcnow()
        path = self._slot_path(slot)
        path.write_text(
            save.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, slot: str = "autosave") -> SaveFile:
        """Load a :class:`SaveFile` from disk.

        Parameters
        ----------
        slot:
            Slot name to load.

        Returns
        -------
        SaveFile
            The deserialised save file.

        Raises
        ------
        FileNotFoundError
            If no save file exists for ``slot``.
        """
        path = self._slot_path(slot)
        if not path.exists():
            raise FileNotFoundError(
                f"No save file found for slot {slot!r} at {path}"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return SaveFile.model_validate(data)

    def list_saves(self) -> list[dict[str, str]]:
        """Return a summary of all save slots on disk.

        Returns
        -------
        list of dict
            Each dict has keys ``slot``, ``book_title``, and ``updated_at``.
            Slots that cannot be parsed are silently skipped.
        """
        results: list[dict[str, str]] = []
        for path in sorted(self.saves_dir.glob("*.json")):
            try:
                data: dict[str, Any] = json.loads(
                    path.read_text(encoding="utf-8")
                )
                results.append({
                    "slot": path.stem,
                    "book_title": data.get("world", {}).get("book_title", "Unknown"),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:  # noqa: BLE001
                continue
        return results
