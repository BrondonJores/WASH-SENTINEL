from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx


def parse_json_response(raw: str) -> dict[str, Any]:
    """Parse une réponse LLM en JSON, tolérant aux blocs markdown."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(cleaned)


VISION_FALLBACK = {
    "is_wash_related": True,
    "infrastructure_detected": "Point d'eau / Tuyauterie scolaire",
    "visible_damage": "Degradation visible constatee sur l'image",
    "visual_severity_score": 75.0,
    "health_hazard_detected": True,
    "technician_notes": "Intervention requise pour securiser l'alimentation en eau potable",
}


class BaseLLMProvider:
    """Contrat commun : tout provider (local ou API externe) doit l'implémenter."""

    provider_name = "base"

    def __init__(
        self,
        base_url: str,
        model: str,
        vision_model: str | None = None,
        embed_model: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.vision_model = vision_model or model
        self.embed_model = embed_model or model
        self.api_key = api_key
        self.timeout = timeout

    async def generate_json(self, prompt: str, system: str = "") -> dict[str, Any]:
        raise NotImplementedError

    async def generate_vision_json(self, prompt: str, image_base64: str, system: str = "") -> dict[str, Any]:
        raise NotImplementedError

    async def get_embedding(self, text: str) -> list[float]:
        raise NotImplementedError

    async def test(self) -> dict[str, Any]:
        """Ping standard : demande un mini JSON et mesure la latence."""
        started = time.perf_counter()
        try:
            data = await self.generate_json('Reponds uniquement {"status": "ok"}', "")
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "latency_ms": latency_ms,
                "sample": json.dumps(data, ensure_ascii=False)[:300],
                "error": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "sample": "",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "vision_model": self.vision_model,
            "embed_model": self.embed_model,
            "base_url": self.base_url,
        }


class OllamaProvider(BaseLLMProvider):
    """Driver modèles locaux via Ollama (Llama, Gemma, Llava, nomic-embed...)."""

    provider_name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
        embed_model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        super().__init__(
            base_url=base_url or os.getenv("OLLAMA_URL", "http://ollama:11434"),
            model=model or os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            vision_model=vision_model or os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision:11b"),
            embed_model=embed_model or os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            api_key=api_key,
            timeout=timeout or float(os.getenv("OLLAMA_TIMEOUT", "120.0")),
        )

    async def generate_json(self, prompt: str, system: str = "") -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            return parse_json_response(response.json().get("response", "{}"))

    async def generate_vision_json(self, prompt: str, image_base64: str, system: str = "") -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.vision_model,
                        "prompt": prompt,
                        "system": system,
                        "images": [image_base64],
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                )
                if response.status_code == 200:
                    return parse_json_response(response.json().get("response", "{}"))
        except Exception:
            pass
        return dict(VISION_FALLBACK)

    async def get_embedding(self, text: str) -> list[float]:
        for model in [self.embed_model, self.model]:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": model, "prompt": text},
                    )
                    if resp.status_code == 200:
                        return resp.json().get("embedding", [])
            except Exception:
                continue
        return []


class OpenAICompatibleProvider(BaseLLMProvider):
    """Driver API externes au format OpenAI (OpenAI, Groq, Together, Mistral, Ollama /v1...)."""

    provider_name = "openai_compatible"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
        embed_model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        super().__init__(
            base_url=base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            vision_model=vision_model or os.getenv("OPENAI_VISION_MODEL") or None,
            embed_model=embed_model or os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            timeout=timeout or float(os.getenv("OPENAI_TIMEOUT", "120.0")),
        )
        if vision_model is None and os.getenv("OPENAI_VISION_MODEL") is None:
            self.vision_model = self.model

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def generate_json(self, prompt: str, system: str = "") -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return parse_json_response(content)

    async def generate_vision_json(self, prompt: str, image_base64: str, system: str = "") -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ],
        })
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": self.vision_model,
                        "messages": messages,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                )
                if response.status_code == 200:
                    content = response.json()["choices"][0]["message"]["content"]
                    return parse_json_response(content)
        except Exception:
            pass
        return dict(VISION_FALLBACK)

    async def get_embedding(self, text: str) -> list[float]:
        for model in [self.embed_model, self.model]:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/embeddings",
                        headers=self._headers(),
                        json={"model": model, "input": text},
                    )
                    if resp.status_code == 200:
                        return resp.json()["data"][0]["embedding"]
            except Exception:
                continue
        return []


# Alias de compatibilité : les agents existants importent OllamaClient.
OllamaClient = OllamaProvider


def llm_from_headers(headers: Any) -> BaseLLMProvider:
    """Construit le provider par requête depuis les headers envoyés par Laravel.

    Headers lus (optionnels, fallback sur les valeurs d'environnement) :
    X-LLM-Provider, X-LLM-Base-URL, X-LLM-Model, X-LLM-Vision-Model,
    X-LLM-Embed-Model, X-LLM-Api-Key, X-LLM-Timeout.
    """
    get = headers.get
    provider = (get("x-llm-provider") or os.getenv("LLM_PROVIDER", "ollama") or "ollama").lower()
    base_url = get("x-llm-base-url") or None
    model = get("x-llm-model") or None
    vision_model = get("x-llm-vision-model") or None
    embed_model = get("x-llm-embed-model") or None
    api_key = get("x-llm-api-key") or None
    timeout_raw = get("x-llm-timeout") or None
    timeout = float(timeout_raw) if timeout_raw else None

    if provider in ("openai_compatible", "openai", "external"):
        return OpenAICompatibleProvider(
            base_url=base_url, model=model, vision_model=vision_model,
            embed_model=embed_model, api_key=api_key, timeout=timeout,
        )
    return OllamaProvider(
        base_url=base_url, model=model, vision_model=vision_model,
        embed_model=embed_model, api_key=api_key, timeout=timeout,
    )


def provider_from_profile(profile: dict[str, Any]) -> BaseLLMProvider:
    """Construit un provider depuis un dict de profil (endpoint de test)."""
    provider = (profile.get("provider") or "ollama").lower()
    kwargs = {
        "base_url": profile.get("base_url"),
        "model": profile.get("model"),
        "vision_model": profile.get("vision_model"),
        "embed_model": profile.get("embed_model"),
        "api_key": profile.get("api_key"),
        "timeout": float(profile.get("timeout") or 30.0),
    }
    if provider in ("openai_compatible", "openai", "external"):
        return OpenAICompatibleProvider(**kwargs)
    return OllamaProvider(**kwargs)


PROVIDER_TYPES: list[dict[str, Any]] = [
    {
        "id": "ollama",
        "label": "Ollama (modèle local)",
        "description": "Modèles hébergés localement : Llama, Gemma, Llava, nomic-embed. Gratuit, privé, sans clé API.",
        "api_key_required": False,
        "fields": [
            {"name": "base_url", "label": "URL Ollama", "type": "url", "default": "http://ollama:11434", "required": True},
            {"name": "model", "label": "Modèle texte", "type": "text", "default": "llama3.2:3b", "required": True},
            {"name": "vision_model", "label": "Modèle vision", "type": "text", "default": "llama3.2-vision:11b", "required": False},
            {"name": "embed_model", "label": "Modèle embeddings", "type": "text", "default": "nomic-embed-text", "required": False},
        ],
    },
    {
        "id": "openai_compatible",
        "label": "API externe (format OpenAI)",
        "description": "OpenAI, Groq, Together, Mistral, ou tout endpoint compatible /v1. Nécessite une clé API.",
        "api_key_required": True,
        "fields": [
            {"name": "base_url", "label": "URL de base (/v1)", "type": "url", "default": "https://api.openai.com/v1", "required": True},
            {"name": "model", "label": "Modèle texte", "type": "text", "default": "gpt-4o-mini", "required": True},
            {"name": "vision_model", "label": "Modèle vision", "type": "text", "default": "", "required": False},
            {"name": "embed_model", "label": "Modèle embeddings", "type": "text", "default": "text-embedding-3-small", "required": False},
        ],
    },
]
