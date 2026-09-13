"""
engine/content_profile.py
--------------------------
Content profile system for the AI Book-to-Game Engine.

A ContentProfile wraps the per-user profile dictionary stored in ``config.json``
and exposes helper methods that translate content-level / dial settings into
concrete instruction strings that are injected into AI system prompts, image
generation prompts, and comprehension-question generation calls.

Profile dict shape (from config.json ``profiles.users.<name>``):
    {
        'display_name': 'Default',
        'content_level': 2,          # 1-5 (see LEVEL_LABELS)
        'dials': {
            'violence':        'implied',   # none | implied | described | graphic
            'romance':         'none',      # none | fade_to_black | descriptive | explicit
            'language':        'clean',     # clean | mild | strong
            'substance_use':   'omit',      # omit | acknowledge | portray
            'religious_tone':  'neutral',   # neutral | reverent | secular
            'horror_darkness': 'softened',  # softened | as_written | amplified
        },
        'difficulty': 'medium',      # easy | medium | hard | scholar
    }
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEVEL_LABELS: dict[int, str] = {
    1: "Strictly Clean",
    2: "Family",
    3: "Teen",
    4: "Adult",
    5: "Explicit",
}

# Dial options, in increasing intensity order (used for boundary checks).
_VIOLENCE_LEVELS    = ("none", "implied", "described", "graphic")
_ROMANCE_LEVELS     = ("none", "fade_to_black", "descriptive", "explicit")
_LANGUAGE_LEVELS    = ("clean", "mild", "strong")
_SUBSTANCE_LEVELS   = ("omit", "acknowledge", "portray")
_RELIGIOUS_TONES    = ("neutral", "reverent", "secular")
_HORROR_LEVELS      = ("softened", "as_written", "amplified")


# ---------------------------------------------------------------------------
# ContentProfile
# ---------------------------------------------------------------------------

class ContentProfile:
    """Wraps a user profile dict and generates AI-instruction strings.

    Parameters
    ----------
    profile_dict:
        The raw profile dictionary as loaded from ``config.json``.

    Raises
    ------
    ValueError
        If ``content_level`` is not in the range 1-5.
    """

    def __init__(self, profile_dict: dict[str, Any]) -> None:
        self._data = profile_dict

        level = int(profile_dict.get("content_level", 2))
        if level not in LEVEL_LABELS:
            raise ValueError(
                f"content_level must be 1-5, got {level!r}. "
                f"Valid levels: {list(LEVEL_LABELS)}"
            )
        self._level = level
        self._dials: dict[str, str] = dict(profile_dict.get("dials", {}))
        self._difficulty: str = profile_dict.get("difficulty", "medium")
        self._display_name: str = profile_dict.get("display_name", "Default")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable name for this profile."""
        return self._display_name

    @property
    def content_level(self) -> int:
        """Numeric content level (1 = Strictly Clean ... 5 = Explicit)."""
        return self._level

    @property
    def dials(self) -> dict[str, str]:
        """Copy of the dial settings dict."""
        return dict(self._dials)

    @property
    def difficulty(self) -> str:
        """Comprehension / gameplay difficulty (easy | medium | hard | scholar)."""
        return self._difficulty

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dial(self, key: str, default: str = "") -> str:
        """Return the value of a named dial, lower-cased."""
        val = self._dials.get(key)
        if not val and key == "religious":
            val = self._dials.get("religion")
        if not val:
            val = default
        return (val or "").lower()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def get_dial_constraints(level: int) -> dict[str, list[str]]:
        """Return the allowed dial values for each dial at the given content level.

        The content level acts as a hard ceiling on dial intensity.
        """
        ALL_VIOLENCE = ["none", "implied", "described", "graphic"]
        ALL_ROMANCE = ["none", "fade_to_black", "descriptive", "explicit"]
        ALL_LANGUAGE = ["clean", "mild", "strong"]
        ALL_SUBSTANCE = ["omit", "acknowledge", "portray"]
        ALL_RELIGIOUS = ["neutral", "reverent", "secular"]
        ALL_HORROR = ["softened", "as_written", "amplified"]

        constraints = {
            1: {  # Strictly Clean
                "violence": ["none"],
                "romance": ["none"],
                "language": ["clean"],
                "substance_use": ["omit"],
                "religious_tone": ALL_RELIGIOUS,
                "horror_darkness": ["softened"],
            },
            2: {  # Family
                "violence": ["none", "implied"],
                "romance": ["none"],
                "language": ["clean"],
                "substance_use": ["omit"],
                "religious_tone": ALL_RELIGIOUS,
                "horror_darkness": ["softened"],
            },
            3: {  # Teen
                "violence": ["none", "implied", "described"],
                "romance": ["none", "fade_to_black"],
                "language": ["clean", "mild"],
                "substance_use": ["omit", "acknowledge"],
                "religious_tone": ALL_RELIGIOUS,
                "horror_darkness": ["softened", "as_written"],
            },
            4: {  # Adult
                "violence": ALL_VIOLENCE,
                "romance": ["none", "fade_to_black", "descriptive"],
                "language": ALL_LANGUAGE,
                "substance_use": ALL_SUBSTANCE,
                "religious_tone": ALL_RELIGIOUS,
                "horror_darkness": ALL_HORROR,
            },
            5: {  # Explicit
                "violence": ALL_VIOLENCE,
                "romance": ALL_ROMANCE,
                "language": ALL_LANGUAGE,
                "substance_use": ALL_SUBSTANCE,
                "religious_tone": ALL_RELIGIOUS,
                "horror_darkness": ALL_HORROR,
            },
        }
        try:
            level = int(level)
        except (ValueError, TypeError):
            pass
        return constraints.get(level, constraints[2])

    def clamp_dials_to_level(self) -> dict[str, str]:
        """Return a copy of dials with values clamped to the content level ceiling."""
        constraints = self.get_dial_constraints(self._level)
        clamped = {}
        for key, allowed in constraints.items():
            current = self._dial(key) or self._dial(key.split('_')[0], allowed[0])
            if current in allowed:
                clamped[key] = current
            else:
                clamped[key] = allowed[-1]  # max allowed
        return clamped

    def build_system_prompt_injection(self) -> str:
        """Return a paragraph of content instructions for AI system prompts.

        The returned string should be prepended or injected into every system
        prompt sent to the language model so it knows what content is and is
        not acceptable for this user profile.

        Returns
        -------
        str
            A self-contained paragraph of instructions.
        """
        level = self._level

        violence  = self._dial("violence",        "none")
        romance   = self._dial("romance",          "none")
        language  = self._dial("language",         "clean")
        substance = self._dial("substance_use") or self._dial("substance", "omit")
        religious = self._dial("religious_tone") or self._dial("religion", "neutral")
        horror    = self._dial("horror_darkness") or self._dial("horror", "softened")

        # -- Violence ---------------------------------------------------
        if violence == "none":
            violence_instr = (
                "Never depict, describe, or imply any act of violence, harm, "
                "or physical conflict. Redirect confrontations toward peaceful "
                "resolution, dialogue, or off-screen outcomes."
            )
        elif violence == "implied":
            violence_instr = (
                "Violence may be implied but must never be described in detail. "
                "Consequences of conflict (injury, danger) may be mentioned "
                "briefly; graphic wounds, suffering, or death must be omitted."
            )
        elif violence == "described":
            violence_instr = (
                "Violence may be described in moderate, realistic detail "
                "appropriate to dramatic fiction. Avoid gratuitous gore or "
                "torture; focus on narrative consequence rather than shock."
            )
        else:  # graphic
            violence_instr = (
                "Violence may be depicted graphically and realistically as the "
                "source material warrants, including combat wounds, death, and "
                "visceral consequences."
            )

        # -- Romance / Intimacy -----------------------------------------
        if romance == "none":
            romance_instr = (
                "Omit all romantic and sexual content. Characters may express "
                "platonic affection; do not depict flirtation, kissing, or "
                "intimate physical contact."
            )
        elif romance == "fade_to_black":
            romance_instr = (
                "Romantic attraction and courtship may be portrayed. Intimate "
                "scenes must fade to black before any explicit physical detail; "
                "imply the outcome without description."
            )
        elif romance == "descriptive":
            romance_instr = (
                "Romantic and intimate scenes may be depicted with sensory "
                "description up to a tasteful, non-explicit level. Avoid "
                "pornographic language or clinical anatomical detail."
            )
        else:  # explicit
            romance_instr = (
                "Adult romantic and sexual content may be portrayed explicitly "
                "as the source material or narrative context requires."
            )

        # -- Language ---------------------------------------------------
        if language == "clean":
            language_instr = (
                "Use only family-safe language. No profanity, slurs, or crude "
                "expressions of any kind."
            )
        elif language == "mild":
            language_instr = (
                "Mild expletives (e.g., 'damn', 'hell') are acceptable where "
                "characterisation demands it. Avoid strong profanity or slurs."
            )
        else:  # strong
            language_instr = (
                "Strong language and profanity may be used where they serve "
                "character voice or dramatic authenticity."
            )

        # -- Substance Use ----------------------------------------------
        if substance == "omit":
            substance_instr = (
                "Omit all references to alcohol, tobacco, drugs, or substance "
                "use. Replace such elements with non-substance alternatives."
            )
        elif substance == "acknowledge":
            substance_instr = (
                "Substance use may be acknowledged as part of the world or "
                "characters, but must not be glorified, instructed, or depicted "
                "approvingly."
            )
        else:  # portray
            substance_instr = (
                "Substance use may be portrayed realistically, including its "
                "effects and consequences, as narrative context requires."
            )

        # -- Religious Tone ---------------------------------------------
        if religious == "reverent":
            religious_instr = (
                "Maintain a reverent, morally constructive tone consistent with "
                "traditional religious values. Redirect any morally ambiguous "
                "source material toward themes of virtue, consequence, and "
                "redemption. Treat references to faith, prayer, and scripture "
                "with respect and seriousness."
            )
        elif religious == "secular":
            religious_instr = (
                "Maintain a secular tone. Avoid invoking religious beliefs, "
                "prayer, or faith-based framing unless directly quoting source "
                "material. Keep moral framing grounded in humanistic values."
            )
        else:  # neutral
            religious_instr = (
                "Maintain a religiously neutral tone. Do not promote or "
                "disparage any faith tradition; respect the religious context "
                "present in the source material without editorialising."
            )

        # -- Horror / Darkness ------------------------------------------
        if horror == "softened":
            horror_instr = (
                "Soften dark, frightening, or horror elements from the source "
                "material. Reduce tension, remove disturbing imagery, and ensure "
                "that sinister themes resolve reassuringly."
            )
        elif horror == "as_written":
            horror_instr = (
                "Preserve the horror and darkness of the source material as "
                "written, without amplification or softening."
            )
        else:  # amplified
            horror_instr = (
                "The horror and atmospheric darkness of the source material may "
                "be amplified for heightened dramatic effect."
            )

        # -- Top-level framing by content level -------------------------
        if level == 1:
            top = (
                "Content must be strictly family-safe and suitable for young "
                "children. Never depict or imply romantic, sexual, or violent "
                "content."
            )
        elif level == 2:
            top = (
                "Content must be family-friendly and suitable for all ages, "
                "including young readers."
            )
        elif level == 3:
            top = (
                "Content is appropriate for teen audiences (roughly 13+). "
                "Mature themes may be explored thoughtfully but must not cross "
                "into adult territory."
            )
        elif level == 4:
            top = (
                "Content is intended for adult audiences. Mature themes, "
                "complex moral situations, and realistic depictions are welcome "
                "where narratively justified."
            )
        else:  # 5
            top = (
                "Content is intended for mature adult audiences with no "
                "significant content restrictions beyond those imposed by "
                "the specific dial settings below."
            )

        parts = [
            f"[CONTENT POLICY -- {LEVEL_LABELS[level].upper()}]",
            top,
            f"Violence: {violence_instr}",
            f"Romance/Intimacy: {romance_instr}",
            f"Language: {language_instr}",
            f"Substance use: {substance_instr}",
            f"Religious tone: {religious_instr}",
            f"Horror/Darkness: {horror_instr}",
            (
                "When adapting source material that conflicts with the above "
                "rules, creatively reframe, summarise, or redirect the content "
                "rather than reproducing it verbatim. Never break character to "
                "apologise; simply apply the policy silently."
            ),
        ]
        return "\n".join(parts)

    def build_image_prompt_suffix(self) -> str:
        """Return style instructions to append to image generation prompts.

        The returned string should be appended (with a comma separator) to any
        image prompt before it is sent to the image backend.

        Returns
        -------
        str
            A comma-separated list of style descriptors.
        """
        level  = self._level
        horror = self._dial("horror_darkness") or self._dial("horror", "softened")

        if level == 1:
            style = (
                "child-friendly storybook illustration, watercolor style, "
                "bright cheerful colors, soft edges, wholesome, no violence, "
                "no scary imagery, suitable for young children"
            )
        elif level == 2:
            style = (
                "family-friendly digital illustration, warm inviting palette, "
                "slightly stylized, clean composition, suitable for all ages"
            )
        elif level == 3:
            style = (
                "semi-realistic digital art, dynamic composition, muted "
                "dramatic palette, teen-appropriate, no explicit content"
            )
        elif level == 4:
            style = (
                "realistic detailed illustration, cinematic lighting, mature "
                "artistic style, rich color grading"
            )
        else:  # 5
            style = (
                "mature artistic style, highly detailed, cinematic realism, "
                "uncensored creative expression"
            )

        if horror == "amplified":
            style += (
                ", atmospheric horror, deep shadows, high contrast, "
                "unsettling mood"
            )
        elif horror == "softened" and level <= 2:
            style += ", bright safe background, no threatening imagery"

        return style

    def build_comprehension_instructions(self) -> str:
        """Return instructions for comprehension question generation.

        The returned string is injected into the prompt used to generate
        comprehension gate questions so the model calibrates difficulty and
        hint verbosity appropriately.

        Returns
        -------
        str
            A paragraph of instructions for question generation.
        """
        difficulty = self._difficulty.lower()

        if difficulty == "easy":
            return (
                "Generate comprehension questions that are simple, direct, and "
                "clearly answerable from a single sentence in the text. "
                "Questions should ask about obvious facts: who a character is, "
                "where a scene takes place, or what a character does. "
                "Accepted answer keywords should be common words that any "
                "reader would naturally use. Hints should be generous, "
                "pointing to the exact paragraph where the answer appears."
            )
        elif difficulty == "medium":
            return (
                "Generate comprehension questions that require the reader to "
                "recall and connect ideas across a chapter. Questions may ask "
                "about character motivations, the significance of objects, or "
                "the outcome of events. Accepted keywords should reflect "
                "natural paraphrase. Hints should reference the chapter and "
                "scene without giving away the answer directly."
            )
        elif difficulty == "hard":
            return (
                "Generate comprehension questions that require inference, "
                "thematic understanding, or synthesis across multiple chapters. "
                "Questions should probe character intent, foreshadowing, "
                "symbolism, or cause-and-effect chains that are not immediately "
                "obvious. Accepted keywords should be precise. Hints should be "
                "minimal -- pointing only to the general chapter without "
                "indicating which passage to re-read."
            )
        else:  # scholar
            return (
                "Generate rigorous scholarly comprehension questions that "
                "require deep analytical thinking: authorial intent, narrative "
                "structure, literary devices, historical or cultural context, "
                "and thematic complexity. Questions should be open-ended enough "
                "to demand a thoughtful multi-keyword response. "
                "Accepted keywords should include domain-specific literary "
                "terms where appropriate. Hints should be Socratic -- asking a "
                "guiding question rather than pointing to a passage -- to "
                "encourage the reader to reason to the answer independently."
            )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ContentProfile(name={self._display_name!r}, "
            f"level={self._level} ({LEVEL_LABELS[self._level]}), "
            f"difficulty={self._difficulty!r})"
        )
