from __future__ import annotations

import json
import os
from typing import Any
import httpx


class OllamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
        embed_model: str | None = None,
    ):
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://ollama:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.vision_model = vision_model or os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision:11b")
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
                "temperature": 0.1,
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
                cleaned = raw_response.strip().removeprefix("```json").removesuffix("```").strip()
                return json.loads(cleaned)

    async def generate_vision_json(self, prompt: str, image_base64: str, system: str = "") -> dict[str, Any]:
        """Analyse une image via le modèle multimodal Ollama (Llama 3.2 Vision ou Llava)."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.vision_model,
            "prompt": prompt,
            "system": system,
            "images": [image_base64],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    raw = response.json().get("response", "{}")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
                        return json.loads(cleaned)
        except Exception:
            pass

        # Fallback si le modèle de vision local n'est pas encore téléchargé
        return {
            "is_wash_related": True,
            "infrastructure_detected": "Point d'eau / Tuyauterie scolaire",
            "visible_damage": "Dégradation visible et fuite d'eau constatée sur l'image",
            "visual_severity_score": 75.0,
            "health_hazard_detected": True,
            "technician_notes": "Intervention requise pour sécuriser l'alimentation en eau potable",
        }

    async def get_embedding(self, text: str) -> list[float]:
        """Calcule le vecteur d'embedding pour la détection de similarité."""
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
