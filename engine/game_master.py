import json
import textwrap
import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.content_profile import ContentProfile
    from engine.game_state import GameWorld


class GameMaster:
    """Evaluates complex player actions against diegetic story obstacles."""

    def __init__(self, router: object, profile: "ContentProfile") -> None:
        self._router = router
        self._profile = profile

    async def evaluate_action(
        self,
        action: str,
        location_desc: str,
        obstacle_data: dict[str, Any] | None,
        inventory: list[dict[str, Any]],
        world: "GameWorld"
    ) -> tuple[bool, str, list[str]]:
        """
        Ask the AI Dungeon Master to evaluate the player's action.
        """
        
        inv_str = ", ".join(i["name"] for i in inventory) if inventory else "Empty"
        
        obs_context = ""
        if obstacle_data:
            obs_context = (
                f"\nOBSTACLE PRESENT: {obstacle_data.get('obstacle_description')}\n"
                f"CANONICAL SOLUTION: {obstacle_data.get('solution_theme')}\n"
            )

        system_prompt = textwrap.dedent(f"""\
            You are the AI Dungeon Master for a text adventure based on "{world.book_title}".
            Your job is to evaluate the player's action and decide what happens.
            
            RULES:
            1. If there is an OBSTACLE PRESENT, the player is trying to overcome it.
               - Check if their action aligns with the CANONICAL SOLUTION or is a clever, physically possible alternative.
               - If it succeeds, set "passed": true.
               - If it fails, set "passed": false and provide a narrative description of the failure (include a subtle hint).
            2. If there is no obstacle, just evaluate the action normally (set "passed": true).
            3. Do not let the player do impossible things (e.g., flying, using items they don't have).
            4. Write the narrative in the second person ("You...").
            
            {self._profile.build_system_prompt_injection()}
        """)

        prompt = textwrap.dedent(f"""\
            Current Location: {location_desc}
            Player Inventory: {inv_str}
            {obs_context}
            
            Player Action: "{action}"
            
            Evaluate the action and return JSON matching this schema:
            {{
                "passed": boolean,
                "narrative": "What happens as a result of the action (1-3 sentences)",
                "mutations": ["remove_item: item_name"] // optional, use if an item is consumed
            }}
        """)

        try:
            raw: dict = await asyncio.to_thread(
                self._router.complete_json, prompt, system_prompt
            )
            passed = bool(raw.get("passed", False))
            narrative = str(raw.get("narrative", "You try, but nothing much happens."))
            mutations = raw.get("mutations", [])
            return passed, narrative, mutations
        except Exception as e:
            return False, f"The Dungeon Master frowns. (Error evaluating action: {e})", []
