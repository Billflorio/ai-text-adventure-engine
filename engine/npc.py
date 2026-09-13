"""
engine/npc.py

LLM-backed NPC dialogue system. Each NPC responds in-character based on
their description, personality, and knowledge of the story world.
Responses are filtered through the active content profile.
"""
from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.model_router import ModelRouter
    from engine.content_profile import ContentProfile
    from engine.game_state import Character, GameWorld, PlayerState


_NPC_SYSTEM_TEMPLATE = textwrap.dedent("""\
    You are roleplaying as {name} from the book "{book_title}".

    CHARACTER DESCRIPTION: {description}
    PERSONALITY & SPEECH STYLE: {personality}
    YOUR ROLE IN THE STORY: {role}

    WORLD CONTEXT: {story_summary}

    RULES:
    - Stay completely in character. Speak as {name} would speak.
    - You know about the events of the story up to this point.
    - Keep responses concise — 1-4 sentences. This is an interactive game.
    - Do not mention that you are an AI or that this is a game.
    - If asked about something outside your character's knowledge, deflect in-character.
    - Do not repeat yourself verbatim from previous exchanges.

    {profile_injection}
""")


def get_npc_response(
    character: "Character",
    player_message: str,
    world: "GameWorld",
    player_state: "PlayerState",
    router: "ModelRouter",
    profile: "ContentProfile",
    context_turns: int = 6,
) -> str:
    """
    Get an in-character response from an NPC.

    Args:
        character: The Character model for the NPC being spoken to.
        player_message: What the player said.
        world: The full game world (for context).
        player_state: Current player state.
        router: Configured ModelRouter.
        profile: Active content profile.
        context_turns: How many past dialogue turns to include.

    Returns:
        NPC's response as a string.
    """
    system = _NPC_SYSTEM_TEMPLATE.format(
        name=character.name,
        book_title=world.book_title,
        description=character.description,
        personality=character.personality,
        role=character.role,
        story_summary=world.story_summary,
        profile_injection=profile.build_system_prompt_injection(),
    )

    # Build conversation history
    history = character.dialogue_history[-context_turns:] if character.dialogue_history else []
    history_text = "\n".join(history) if history else ""

    # Build inventory context
    inv_names = [item.name for item in player_state.inventory]
    inv_text = f"The player is carrying: {', '.join(inv_names)}." if inv_names else ""

    prompt = textwrap.dedent(f"""\
        {history_text}

        {inv_text}

        The player says to you: "{player_message}"

        Respond as {character.name}:
    """).strip()

    response = router.complete(prompt, system_prompt=system, temperature=0.85)

    # Log to dialogue history (keep last 20 turns)
    character.dialogue_history.append(f"Player: {player_message}")
    character.dialogue_history.append(f"{character.name}: {response}")
    if len(character.dialogue_history) > 20:
        character.dialogue_history = character.dialogue_history[-20:]

    return response


def get_narrator_response(
    action: str,
    location_description: str,
    world: "GameWorld",
    router: "ModelRouter",
    profile: "ContentProfile",
) -> str:
    """
    Generate a narrator description for a specific action or event.
    Used for atmospheric descriptions, action results, etc.

    Args:
        action: What just happened (e.g. 'player opened the wardrobe').
        location_description: Current location's base description.
        world: Game world context.
        router: ModelRouter.
        profile: Content profile.

    Returns:
        Short narrative description (1-3 sentences).
    """
    system = textwrap.dedent(f"""\
        You are the narrator for a text adventure game based on "{world.book_title}".
        Write in second person (You...). Be evocative but brief — 1-3 sentences.
        Match the tone of the source material.
        {profile.build_system_prompt_injection()}
    """)

    prompt = f"Current location: {location_description}\n\nEvent: {action}\n\nDescribe what happens:"

    return router.complete(prompt, system_prompt=system, temperature=0.75)
