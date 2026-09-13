"""
ai/model_router.py
==================
Unified LLM interface for the AI Book-to-Game Engine.

Abstracts over multiple LLM backends so the rest of the engine never needs
to know which provider is in use.  The ``config`` dict passed to
:class:`ModelRouter` should come from the ``llm`` key of ``config.json``.

Supported backends
------------------
* ``ollama``            - local Ollama server (no API key needed)
* ``lmstudio``          - LM Studio local server (OpenAI-compatible)
* ``openai``            - OpenAI cloud API
* ``anthropic``         - Anthropic Claude API
* ``gemini``            - Google Gemini API
* ``openai_compatible`` - any OpenAI-compatible endpoint
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL | re.IGNORECASE,
)
_JSON_BARE_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _extract_json(text: str) -> str:
    """Return the first JSON object/array found in *text*.

    Checks in order:

    1. Markdown code-fence (```json ... ```)
    2. First bare ``{...}`` or ``[...]`` block
    3. The raw *text* itself (let the caller's json.loads raise)
    """
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        return fence_match.group(1).strip()

    bare_match = _JSON_BARE_RE.search(text)
    if bare_match:
        return bare_match.group(1).strip()

    return text.strip()


def _json_instruction(schema_hint: str) -> str:
    """Return a prompt suffix that instructs the model to reply with JSON."""
    base = (
        "\n\nRespond with ONLY a valid JSON object - no prose, no markdown fences, "
        "no explanation."
    )
    if schema_hint:
        base += f"\n\nExpected JSON shape:\n{schema_hint}"
    return base


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Unified LLM completion interface.

    Parameters
    ----------
    config:
        Dictionary with keys ``backend``, ``model``, ``base_url``,
        ``api_key``, ``max_tokens``, and ``temperature``.
    """

    SUPPORTED_BACKENDS: tuple[str, ...] = (
        "ollama",
        "lmstudio",
        "openai",
        "anthropic",
        "gemini",
        "openai_compatible",
    )

    def __init__(self, config: dict[str, Any]) -> None:
        self._backend: str = config.get("backend", "ollama").lower()
        self._model: str = config.get("model", "")
        self._base_url: str = (config.get("base_url") or "").rstrip("/")
        self._api_key: str | None = config.get("api_key") or None
        self._max_tokens: int = int(config.get("max_tokens", 4096))
        self._temperature: float = float(config.get("temperature", 0.7))

        if self._backend not in self.SUPPORTED_BACKENDS:
            raise ValueError(
                f"Unknown backend {self._backend!r}. "
                f"Supported: {self.SUPPORTED_BACKENDS}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float | None = None,
    ) -> str:
        """Return a plain-text completion for *prompt*.

        Parameters
        ----------
        prompt:
            The user message / instruction.
        system_prompt:
            Optional system / persona message prepended to the conversation.
        temperature:
            Override the config temperature for this call only.
        """
        temp = temperature if temperature is not None else self._temperature
        dispatch = {
            "ollama":            self._complete_ollama,
            "lmstudio":          self._complete_openai_sdk,
            "openai":            self._complete_openai_sdk,
            "anthropic":         self._complete_anthropic,
            "gemini":            self._complete_gemini,
            "openai_compatible": self._complete_openai_sdk,
        }
        return dispatch[self._backend](prompt, system_prompt, temp)

    def complete_json(
        self,
        prompt: str,
        system_prompt: str = "",
        schema_hint: str = "",
    ) -> dict[str, Any]:
        """Return a parsed JSON dict for *prompt*.

        Appends a JSON-response instruction to the prompt, calls
        :meth:`complete`, then extracts and parses the JSON from the
        model response (handling markdown code fences automatically).

        Parameters
        ----------
        prompt:
            The user message / instruction.
        system_prompt:
            Optional system message.
        schema_hint:
            Optional example / description of the expected JSON structure,
            appended to the JSON instruction for models that benefit from it.

        Raises
        ------
        ValueError
            If the model response cannot be parsed as JSON after all
            extraction attempts.  The raw response is included in the
            exception message.
        """
        augmented_prompt = prompt + _json_instruction(schema_hint)
        raw = self.complete(augmented_prompt, system_prompt=system_prompt)
        candidate = _extract_json(raw)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            # Robust auto-close for truncated JSON
            c = candidate.strip()
            for i in range(len(c), max(0, len(c) - 2000), -1):
                test_str = c[:i].rstrip()
                if test_str.endswith(','):
                    test_str = test_str[:-1]
                
                open_braces = test_str.count('{') - test_str.count('}')
                open_brackets = test_str.count('[') - test_str.count(']')
                
                if open_brackets > 0:
                    test_str += ']' * open_brackets
                if open_braces > 0:
                    test_str += '}' * open_braces
                    
                try:
                    return json.loads(test_str)
                except json.JSONDecodeError:
                    continue
                    
            raise ValueError(
                f"Model response could not be parsed as JSON.\n"
                f"Raw response:\n{raw}"
            ) from exc

    def test_connection(self) -> tuple[bool, str]:
        """Probe the configured backend and return ``(success, message)``.

        Returns
        -------
        tuple[bool, str]
            ``(True, description)`` if the backend is reachable /
            authenticated; ``(False, error_msg)`` otherwise.
        """
        dispatch = {
            "ollama":            self._test_ollama,
            "lmstudio":          self._test_openai_sdk,
            "openai":            self._test_openai_sdk,
            "anthropic":         self._test_anthropic,
            "gemini":            self._test_gemini,
            "openai_compatible": self._test_openai_sdk,
        }
        try:
            return dispatch[self._backend]()
        except Exception as exc:
            return False, f"Unexpected error during connection test: {exc}"

    # ------------------------------------------------------------------
    # Ollama backend
    # ------------------------------------------------------------------

    def _build_ollama_messages(
        self, prompt: str, system_prompt: str
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _complete_ollama(
        self, prompt: str, system_prompt: str, temperature: float
    ) -> str:
        url = f"{self._base_url}/api/chat"
        payload: dict[str, Any] = {
            "model":    self._model,
            "messages": self._build_ollama_messages(prompt, system_prompt),
            "stream":   False,
            "options":  {"temperature": temperature},
        }
        resp = requests.post(url, json=payload, timeout=900)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def _test_ollama(self) -> tuple[bool, str]:
        url = f"{self._base_url}/api/tags"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        models: list[str] = [
            m.get("name", "") for m in resp.json().get("models", [])
        ]
        model_list = ", ".join(models) if models else "(no models loaded)"
        return True, f"Ollama reachable. Available models: {model_list}"

    # ------------------------------------------------------------------
    # OpenAI-SDK backends  (openai / lmstudio / openai_compatible)
    # ------------------------------------------------------------------

    def _get_openai_client(self):
        """Return a configured ``openai.OpenAI`` client."""
        import openai  # lazy import - not required if backend not used

        kwargs: dict[str, Any] = {
            "api_key": self._api_key or "not-needed",
            "timeout": 900.0
        }
        if self._backend in ("lmstudio", "openai_compatible"):
            base = self._base_url
            if not base.endswith("/v1"):
                base = base + "/v1"
            kwargs["base_url"] = base
            if self._backend == "lmstudio":
                kwargs["api_key"] = "lm-studio"
        elif self._backend == "openai" and self._api_key:
            kwargs["api_key"] = self._api_key

        return openai.OpenAI(**kwargs)

    def _build_openai_messages(
        self, prompt: str, system_prompt: str
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _complete_openai_sdk(
        self, prompt: str, system_prompt: str, temperature: float
    ) -> str:
        client = self._get_openai_client()
        response = client.chat.completions.create(
            model=self._model,
            messages=self._build_openai_messages(prompt, system_prompt),
            max_tokens=self._max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    def _test_openai_sdk(self) -> tuple[bool, str]:
        client = self._get_openai_client()
        models = list(client.models.list())
        ids = [m.id for m in models[:5]]
        return True, f"OpenAI-compatible endpoint reachable. Sample models: {ids}"

    # ------------------------------------------------------------------
    # Anthropic backend
    # ------------------------------------------------------------------

    def _complete_anthropic(
        self, prompt: str, system_prompt: str, temperature: float
    ) -> str:
        import anthropic  # lazy import

        client = anthropic.Anthropic(api_key=self._api_key or "")
        kwargs: dict[str, Any] = {
            "model":       self._model,
            "max_tokens":  self._max_tokens,
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        message = client.messages.create(**kwargs)
        texts = [
            block.text
            for block in message.content
            if hasattr(block, "text")
        ]
        return "".join(texts)

    def _test_anthropic(self) -> tuple[bool, str]:
        import anthropic  # lazy import

        client = anthropic.Anthropic(api_key=self._api_key or "")
        msg = client.messages.create(
            model=self._model or "claude-3-haiku-20240307",
            max_tokens=8,
            messages=[{"role": "user", "content": "Hi"}],
        )
        return True, f"Anthropic reachable. Stop reason: {msg.stop_reason}"

    # ------------------------------------------------------------------
    # Gemini backend
    # ------------------------------------------------------------------

    def _complete_gemini(
        self, prompt: str, system_prompt: str, temperature: float
    ) -> str:
        import google.generativeai as genai  # lazy import

        genai.configure(api_key=self._api_key or "")
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=self._max_tokens,
            temperature=temperature,
        )
        system_instruction = system_prompt if system_prompt else None
        model = genai.GenerativeModel(
            model_name=self._model,
            generation_config=generation_config,
            system_instruction=system_instruction,
        )
        response = model.generate_content(prompt)
        return response.text

    def _test_gemini(self) -> tuple[bool, str]:
        import google.generativeai as genai  # lazy import

        genai.configure(api_key=self._api_key or "")
        available = [m.name for m in genai.list_models()]
        sample = available[:3] if available else ["(none)"]
        return True, f"Gemini reachable. Sample models: {sample}"
