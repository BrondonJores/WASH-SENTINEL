from __future__ import annotations

import json
import os
from typing import Any
import httpx


class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, embed_model: str | None = None):
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://ollama:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.embed_model = embed_model or os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        self.timeout = float(os.getenv("OLLAMA_TIMEOUT", "120.0"))

    async def generate_json(self, prompt: str, system: str = "") -> dict[str, Any]:
        """Génère une réponse JSON contrainte depuis Llama via Ollama."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,  # Faible température pour une extraction déterministe
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_response = data.get("response", "{}")

            try:
                return json.loads(raw_response)
            except json.JSONDecodeError:
                # Nettoyage si jamais des balises markdown markdown subsistent
                cleaned = raw_response.strip().removeprefix("```json").removesuffix("```").strip()
                return json.loads(cleaned)

    async def get_embedding(self, text: str) -> list[float]:
        """Calcule le vecteur d'embedding pour la détection de similarité."""
        # 1. Tente avec le modèle d'embedding dédié (nomic-embed-text)
        # 2. Si échec, repli sur le modèle principal (Llama)
        for model in [self.embed_model, self.model]:
            try:
                url = f"{self.base_url}/api/embeddings"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, json={"model": model, "prompt": text})
                    if resp.status_code == 200:
                        return resp.json().get("embedding", [])
            except Exception:
                continue

        return []
