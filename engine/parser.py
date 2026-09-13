"""
engine/parser.py
-----------------
Player input parser for the AI Book-to-Game Engine.

Provides a simple verb-noun parser that normalises free-text player commands
into structured dicts understood by the game loop.

Example usage::

    result = parse("Go North")
    # {'verb': 'go', 'noun': 'north', 'raw': 'Go North'}

    result = parse("pick up the lantern")
    # {'verb': 'take', 'noun': 'lantern', 'raw': 'pick up the lantern'}
"""

from __future__ import annotations

import re
import string
from typing import Final


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

HELP_TEXT: Final[str] = """
Available commands
==================
  go <direction>      Move in a direction (north, south, east, west, up, down).
                      Shortcuts: n, s, e, w, u, d
  look [target]       Describe your surroundings, or examine a specific thing.
  take <item>         Pick up an item.                    Aliases: pick, grab, get
  drop <item>         Drop an item from your inventory.   Aliases: leave, put
  talk <character>    Start a conversation with a character.
                      Aliases: speak, ask, chat, greet
  inventory           Show your current inventory.        Aliases: i, items, bag
  read <item>         Read a book, note, or inscription.
  use <item>          Use an item from your inventory.
  save                Save the current game.
  load                Load a saved game.
  help                Show this help text.               Alias: ?
  quit                Exit the game.                     Aliases: exit, bye, q
""".strip()


# ---------------------------------------------------------------------------
# Verb alias table
# ---------------------------------------------------------------------------

# Maps every accepted surface form -> canonical verb.
_VERB_ALIASES: Final[dict[str, str]] = {
    # movement
    "go":      "go",
    "walk":    "go",
    "move":    "go",
    "head":    "go",
    "travel":  "go",
    "enter":   "go",
    "exit":    "go",
    "north":   "go",
    "south":   "go",
    "east":    "go",
    "west":    "go",
    "up":      "go",
    "down":    "go",
    # look
    "look":    "look",
    "examine": "look",
    "inspect": "look",
    "describe": "look",
    "l":       "look",
    "x":       "look",
    # take
    "take":    "take",
    "pick":    "take",
    "grab":    "take",
    "get":     "take",
    # drop
    "drop":    "drop",
    "leave":   "drop",
    "put":     "drop",
    # talk
    "talk":    "talk",
    "speak":   "talk",
    "ask":     "talk",
    "chat":    "talk",
    "greet":   "talk",
    # inventory
    "inventory": "inventory",
    "i":         "inventory",
    "items":     "inventory",
    "bag":       "inventory",
    "pockets":   "inventory",
    # help
    "help":    "help",
    "?":       "help",
    # save / load
    "save":    "save",
    "load":    "load",
    # quit
    "quit":    "quit",
    "bye":     "quit",
    "q":       "quit",
    # read
    "read":    "read",
    # use
    "use":     "use",
    # cheat
    "cheat":   "cheat",
    "skip":    "cheat",
}

# Direction words that, when used alone as the entire command, expand to 'go <dir>'.
_DIRECTION_SHORTCUTS: Final[dict[str, str]] = {
    "n":      "north",
    "s":      "south",
    "e":      "east",
    "w":      "west",
    "u":      "up",
    "d":      "down",
    "north":  "north",
    "south":  "south",
    "east":   "east",
    "west":   "west",
    "up":     "up",
    "down":   "down",
}

# Filler words stripped from the noun portion so 'pick up the lantern'
# becomes noun='lantern'.
_STOP_WORDS: Final[frozenset[str]] = frozenset({
    "the", "a", "an", "at", "to", "up", "on", "in",
    "into", "with", "from", "of", "my",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(text: str) -> dict[str, str]:
    """Parse a raw player input string into a structured command dict.

    Parameters
    ----------
    text:
        The raw string typed by the player.

    Returns
    -------
    dict
        A dict with three keys:

        ``verb``
            Canonical verb string (``'go'``, ``'look'``, ``'take'``, …),
            or ``'unknown'`` if the verb was not recognised.
        ``noun``
            The remainder of the command after stripping filler words, or an
            empty string when no noun is present.
        ``raw``
            The original unmodified input string.
    """
    raw: str = text

    # 1. Normalise: lowercase, strip leading/trailing whitespace.
    normalised = text.lower().strip()

    # 1a. Handle bare '?' before punctuation is stripped.
    if normalised == "?":
        return {"verb": "help", "noun": "", "raw": raw}

    # 2. Remove punctuation (except apostrophes, which can appear in names).
    normalised = re.sub(r"[^\w\s']", " ", normalised)

    # 3. Collapse internal whitespace.
    normalised = re.sub(r"\s+", " ", normalised).strip()

    if not normalised:
        return {"verb": "unknown", "noun": "", "raw": raw}

    tokens = normalised.split()
    first = tokens[0]

    # 4. Handle bare direction shortcuts ('n', 's', 'nw', etc.)
    if len(tokens) == 1 and first in _DIRECTION_SHORTCUTS:
        return {"verb": "go", "noun": _DIRECTION_SHORTCUTS[first], "raw": raw}

    # 5. Map first token to canonical verb.
    verb = _VERB_ALIASES.get(first, "unknown")

    # 6. For bare direction words used as the verb (e.g. 'north', 'up'),
    #    the noun becomes the direction itself.
    if verb == "go" and first in _DIRECTION_SHORTCUTS:
        # e.g. 'north quickly' -> go north (ignore extra tokens)
        noun = _DIRECTION_SHORTCUTS[first]
        return {"verb": verb, "noun": noun, "raw": raw}

    # 7. Build noun from remaining tokens, filtering stop words.
    rest = tokens[1:]
    noun_tokens = [t for t in rest if t not in _STOP_WORDS]
    noun = " ".join(noun_tokens)

    return {"verb": verb, "noun": noun, "raw": raw}
