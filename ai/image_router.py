"""
ai/image_router.py
==================
Unified image-generation interface for the AI Book-to-Game Engine.

Abstracts over multiple image backends so the rest of the engine never needs
to know which provider is in use.  The ``config`` dict passed to
:class:`ImageRouter` should come from the ``image`` key of ``config.json``.

Supported backends
------------------
* ``none``              - disabled; :meth:`generate` always returns ``None``
* ``automatic1111``     - AUTOMATIC1111 / Forge Stable Diffusion web UI
* ``comfyui``           - ComfyUI with default KSampler workflow
* ``dalle3``            - OpenAI DALL-E 3 cloud API
* ``openai_compatible`` - any OpenAI-Images-compatible endpoint
"""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Any

import requests


class ImageRouter:
    """Unified image generation interface.

    Parameters
    ----------
    config:
        Dictionary with keys ``backend``, ``base_url``, ``api_key``,
        ``width``, ``height``, ``steps``, ``cfg_scale``, and ``checkpoint``.
    """

    SUPPORTED_BACKENDS: tuple[str, ...] = (
        "none",
        "automatic1111",
        "comfyui",
        "dalle3",
        "openai_compatible",
        "gemini",
    )

    def __init__(self, config: dict[str, Any]) -> None:
        self._backend: str = config.get("backend", "none").lower()
        self._base_url: str = (config.get("base_url") or "").rstrip("/")
        self._api_key: str | None = config.get("api_key") or None
        self._width: int = int(config.get("width", 768))
        self._height: int = int(config.get("height", 512))
        self._steps: int = int(config.get("steps", 25))
        self._cfg_scale: float = float(config.get("cfg_scale", 7.0))
        self._checkpoint: str | None = config.get("checkpoint") or None

        if self._backend not in self.SUPPORTED_BACKENDS:
            raise ValueError(
                f"Unknown image backend {self._backend!r}. "
                f"Supported: {self.SUPPORTED_BACKENDS}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        save_path: Path | None = None,
    ) -> Path | None:
        """Generate an image from *prompt* and return the saved path.

        Parameters
        ----------
        prompt:
            Positive (subject / style) prompt text.
        negative_prompt:
            Negative prompt text.  Not supported by DALL-E 3 - silently
            ignored for that backend.
        save_path:
            Where to save the output PNG.  If ``None`` a filename is
            generated automatically in the current working directory.

        Returns
        -------
        Path | None
            Absolute path to the saved PNG, or ``None`` if the backend is
            ``"none"``.
        """
        if self._backend == "none":
            return None

        if save_path is None:
            save_path = Path(f"image_{uuid.uuid4().hex[:8]}.png")
        save_path = save_path.resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)

        dispatch = {
            "automatic1111":     self._generate_a1111,
            "comfyui":           self._generate_comfyui,
            "dalle3":            self._generate_dalle,
            "openai_compatible": self._generate_openai_compatible,
            "gemini":            self._generate_gemini,
        }
        return dispatch[self._backend](prompt, negative_prompt, save_path)

    def test_connection(self) -> tuple[bool, str]:
        """Probe the configured backend and return ``(success, message)``.

        Returns
        -------
        tuple[bool, str]
            ``(True, description)`` if the backend is reachable /
            authenticated; ``(False, error_msg)`` otherwise.
        """
        if self._backend == "none":
            return True, "Image backend is disabled ('none')."

        dispatch = {
            "automatic1111":     self._test_a1111,
            "comfyui":           self._test_comfyui,
            "dalle3":            self._test_dalle,
            "openai_compatible": self._test_openai_compatible,
            "gemini":            self._test_gemini,
        }
        try:
            return dispatch[self._backend]()
        except Exception as exc:
            return False, f"Unexpected error during connection test: {exc}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _save_bytes(data: bytes, path: Path) -> Path:
        """Write *data* to *path* and return *path*."""
        path.write_bytes(data)
        return path

    def _download_url(self, url: str, save_path: Path) -> Path:
        """Stream-download *url* and save to *save_path*."""
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        with save_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
        return save_path

    # ------------------------------------------------------------------
    # AUTOMATIC1111 / Forge backend
    # ------------------------------------------------------------------

    def _generate_a1111(
        self, prompt: str, negative_prompt: str, save_path: Path
    ) -> Path:
        url = f"{self._base_url}/sdapi/v1/txt2img"
        payload: dict[str, Any] = {
            "prompt":          prompt,
            "negative_prompt": negative_prompt,
            "width":           self._width,
            "height":          self._height,
            "steps":           self._steps,
            "cfg_scale":       self._cfg_scale,
        }
        if self._checkpoint:
            payload["override_settings"] = {
                "sd_model_checkpoint": self._checkpoint
            }

        resp = requests.post(url, json=payload, timeout=300)
        resp.raise_for_status()
        data = resp.json()

        images: list[str] = data.get("images", [])
        if not images:
            raise RuntimeError("AUTOMATIC1111 returned no images in response.")

        image_bytes = base64.b64decode(images[0])
        return self._save_bytes(image_bytes, save_path)

    def _test_a1111(self) -> tuple[bool, str]:
        url = f"{self._base_url}/sdapi/v1/options"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        model = resp.json().get("sd_model_checkpoint", "unknown")
        return True, f"AUTOMATIC1111 reachable. Active checkpoint: {model}"

    # ------------------------------------------------------------------
    # ComfyUI backend
    # ------------------------------------------------------------------

    def _build_comfyui_workflow(
        self, prompt: str, negative_prompt: str
    ) -> dict[str, Any]:
        """Return a minimal ComfyUI API workflow for txt2img.

        Node layout
        -----------
        4  CheckpointLoaderSimple
        6  CLIPTextEncode (positive)
        7  CLIPTextEncode (negative)
        3  KSampler
        8  VAEDecode
        9  SaveImage
        """
        checkpoint = self._checkpoint or "v1-5-pruned-emaonly.ckpt"
        seed = int(uuid.uuid4().int % (2**32))
        return {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width":      self._width,
                    "height":     self._height,
                    "batch_size": 1,
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": negative_prompt, "clip": ["4", 1]},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed":         seed,
                    "steps":        self._steps,
                    "cfg":          self._cfg_scale,
                    "sampler_name": "euler",
                    "scheduler":    "normal",
                    "denoise":      1.0,
                    "model":        ["4", 0],
                    "positive":     ["6", 0],
                    "negative":     ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "aig_", "images": ["8", 0]},
            },
        }

    def _generate_comfyui(
        self, prompt: str, negative_prompt: str, save_path: Path
    ) -> Path:
        # 1. Submit the workflow
        workflow = self._build_comfyui_workflow(prompt, negative_prompt)
        client_id = uuid.uuid4().hex
        submit_resp = requests.post(
            f"{self._base_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            timeout=30,
        )
        submit_resp.raise_for_status()
        prompt_id: str = submit_resp.json()["prompt_id"]

        # 2. Poll history until the job is complete
        history_url = f"{self._base_url}/history/{prompt_id}"
        max_wait_seconds = 300
        poll_interval = 2.0
        elapsed = 0.0

        while elapsed < max_wait_seconds:
            time.sleep(poll_interval)
            elapsed += poll_interval

            hist_resp = requests.get(history_url, timeout=15)
            hist_resp.raise_for_status()
            history = hist_resp.json()

            if prompt_id not in history:
                continue  # not done yet

            outputs = history[prompt_id].get("outputs", {})

            for _node_id, node_output in outputs.items():
                images: list[dict[str, str]] = node_output.get("images", [])
                if not images:
                    continue
                img_info  = images[0]
                filename  = img_info["filename"]
                subfolder = img_info.get("subfolder", "")
                img_type  = img_info.get("type", "output")

                # 3. Download the finished image
                params: dict[str, str] = {
                    "filename": filename,
                    "type":     img_type,
                }
                if subfolder:
                    params["subfolder"] = subfolder

                view_resp = requests.get(
                    f"{self._base_url}/view",
                    params=params,
                    timeout=60,
                )
                view_resp.raise_for_status()
                return self._save_bytes(view_resp.content, save_path)

        raise TimeoutError(
            f"ComfyUI job {prompt_id!r} did not complete within "
            f"{max_wait_seconds}s."
        )

    def _test_comfyui(self) -> tuple[bool, str]:
        resp = requests.get(f"{self._base_url}/system_stats", timeout=10)
        resp.raise_for_status()
        python_ver = (
            resp.json().get("system", {}).get("python_version", "unknown")
        )
        return True, f"ComfyUI reachable. Python: {python_ver}"

    # ------------------------------------------------------------------
    # DALL-E 3 backend
    # ------------------------------------------------------------------

    def _get_openai_images_client(self, *, openai_compatible: bool = False):
        """Return a configured ``openai.OpenAI`` client."""
        import openai  # lazy import

        kwargs: dict[str, Any] = {"api_key": self._api_key or "not-needed"}
        if openai_compatible and self._base_url:
            base = self._base_url
            if not base.endswith("/v1"):
                base = base + "/v1"
            kwargs["base_url"] = base
        return openai.OpenAI(**kwargs)

    def _generate_dalle(
        self, prompt: str, negative_prompt: str, save_path: Path
    ) -> Path:
        # DALL-E 3 does not accept a negative prompt; silently ignored
        client = self._get_openai_images_client()
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            quality="standard",
            n=1,
        )
        image_url: str = response.data[0].url
        return self._download_url(image_url, save_path)

    def _test_dalle(self) -> tuple[bool, str]:
        import openai  # lazy import

        client = openai.OpenAI(api_key=self._api_key or "")
        models = [m.id for m in client.models.list() if "dall-e" in m.id]
        return True, f"OpenAI reachable. DALL-E models available: {models}"

    # ------------------------------------------------------------------
    # OpenAI-compatible image backend
    # ------------------------------------------------------------------

    def _generate_openai_compatible(
        self, prompt: str, negative_prompt: str, save_path: Path
    ) -> Path:
        client = self._get_openai_images_client(openai_compatible=True)
        size = f"{self._width}x{self._height}"
        response = client.images.generate(
            model=self._checkpoint or "default",
            prompt=prompt,
            size=size,
            quality="standard",
            n=1,
        )
        image_url: str = response.data[0].url
        return self._download_url(image_url, save_path)

    def _test_openai_compatible(self) -> tuple[bool, str]:
        resp = requests.get(f"{self._base_url}/v1/models", timeout=10)
        resp.raise_for_status()
        ids = [
            m.get("id", "?")
            for m in resp.json().get("data", [])[:5]
        ]
        return True, f"OpenAI-compatible image endpoint reachable. Models: {ids}"

    # ------------------------------------------------------------------
    # Gemini backend
    # ------------------------------------------------------------------

    def _generate_gemini(
        self, prompt: str, negative_prompt: str, save_path: Path
    ) -> Path:
        model = self._checkpoint or 'gemini-3.1-flash-image'
        if not model.startswith('models/'):
            model = f'models/{model}'

        url = f'https://generativelanguage.googleapis.com/v1beta/{model}:generateContent'
        headers = {'x-goog-api-key': self._api_key or ''}
        
        full_prompt = prompt
        if negative_prompt:
            full_prompt += f'\n\nNegative prompt: {negative_prompt}'

        payload = {
            'contents': [{'parts': [{'text': full_prompt}]}]
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        
        data = resp.json()
        candidates = data.get('candidates', [])
        if not candidates:
            raise RuntimeError(f'No predictions returned from Gemini. Raw response: {data}')
            
        parts = candidates[0].get('content', {}).get('parts', [])
        b64_img = None
        for part in parts:
            if 'inlineData' in part:
                b64_img = part['inlineData'].get('data')
                break

        if not b64_img:
            raise RuntimeError(f'No image bytes in Gemini prediction: {parts}')
            
        return self._save_bytes(base64.b64decode(b64_img), save_path)

    def _test_gemini(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, 'API key missing for Gemini.'
        model = self._checkpoint or 'imagen-3.0-generate-001'
        if not model.startswith('models/'):
            model = f'models/{model}'
        
        # Test API key validity by listing standard models
        # We don't GET the specific model because experimental/unlisted models like nano-banana return 404 on GET
        url = f'https://generativelanguage.googleapis.com/v1beta/models?key={self._api_key}'
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return True, f'Gemini reachable. API key is valid. Will use {model} at runtime.'
        return False, f'Gemini error: HTTP {resp.status_code} {resp.text}'
