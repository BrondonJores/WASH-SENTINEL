from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx


# --- Robustesse réseau (terrain : Ollama froid, timeouts, 5xx/429 transitoires) ---
RETRY_MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
WARMUP_TIMEOUT_SECONDS_DEFAULT = 15.0


def _is_retryable_status(status_code: int) -> bool:
    """True si le statut HTTP est transitoire (timeout/rate-limit/serveur)."""
    return status_code in RETRYABLE_STATUS_CODES


def _is_retryable_exception(exc: BaseException) -> bool:
    """True si l'exception réseau est transitoire (timeout/connexion)."""
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


def _warmup_timeout_seconds() -> float:
    """Timeout du warmup : explicite, configurable via LLM_WARMUP_TIMEOUT."""
    try:
        return float(os.getenv("LLM_WARMUP_TIMEOUT", str(WARMUP_TIMEOUT_SECONDS_DEFAULT)))
    except ValueError:
        return WARMUP_TIMEOUT_SECONDS_DEFAULT


def parse_json_response(raw: str) -> dict[str, Any]:
    """Parse une réponse LLM en JSON, tolérant aux blocs markdown."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(cleaned)


def raise_for_ollama(response: httpx.Response, model: str) -> None:
    """Traduit les erreurs HTTP d'Ollama en messages actionnables.

    Ollama répond 404 quand le modèle demandé n'est pas téléchargé :
    sans traduction, l'UI affiche une 500 brute incompréhensible.
    Pour les autres erreurs, le corps de réponse d'Ollama (qui contient
    la vraie raison, ex. {"error": ...}) est inclus dans le message.
    On préserve HTTPStatusError pour ne pas casser le repli sans-tools.
    """
    if response.status_code == 404:
        raise RuntimeError(
            f"Modèle Ollama '{model}' introuvable (404). "
            "Vérifiez 'ollama list' ou activez un autre profil depuis Réglages IA."
        )
    if response.is_error:
        body = " ".join(response.text.split())[:300]
        raise httpx.HTTPStatusError(
            f"Ollama {response.status_code} pour '{model}': {body or 'sans détail'}.",
            request=response.request,
            response=response,
        )
    response.raise_for_status()


def _iter_json_blocks(text: str) -> list[str]:
    """Yield les blocs {...} équilibrés de premier niveau (ignore le reste)."""
    blocks: list[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    blocks.append(text[start:i + 1])
                    start = -1
    return blocks


def extract_text_tool_calls(content: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repli poor-man's tool calling : certains petits modèles (ex. qwen 3B)
    émettent l'appel d'outil en JSON texte au lieu du champ natif `tool_calls`.

    Ne convertit que les noms d'outils connus (définitions fournies).
    """
    known: set[str] = set()
    for t in tools or []:
        fn = (t.get("function") or {}) if isinstance(t, dict) else {}
        if isinstance(fn, dict) and fn.get("name"):
            known.add(fn["name"])
    if not known or not content:
        return []
    for candidate in _iter_json_blocks(content):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        calls: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name not in known:
                continue
            args = item.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"id": None, "name": name, "arguments": args if isinstance(args, dict) else {}})
        if calls:
            return calls
    return []


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
        # Hook de test : transport httpx injectable (MockTransport), None en prod.
        self._transport: httpx.AsyncBaseTransport | None = None

    def _async_client(self, timeout: float | None = None) -> httpx.AsyncClient:
        """Client HTTP du provider : timeout explicite + transport injectable (tests)."""
        kwargs: dict[str, Any] = {"timeout": self.timeout if timeout is None else timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    def _retry_delay(self, failed_attempt: int) -> float:
        """Délai exponentiel avant réessai (1s, 2s, 4s...). failed_attempt est 1-based."""
        idx = max(0, min(failed_attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1))
        return RETRY_BACKOFF_SECONDS[idx]

    def _final_transient_message(
        self, *, last_status: int | None, last_exc: Exception | None
    ) -> str:
        """Message final FR actionnable après épuisement des réessais."""
        base = (
            f"LLM '{self.model}' ({self.provider_name}, {self.base_url}) "
            f"injoignable après {RETRY_MAX_ATTEMPTS} tentatives"
        )
        if isinstance(last_exc, httpx.TimeoutException):
            return (
                f"{base} : délai dépassé (timeout {self.timeout}s). "
                "Le modèle est peut-être froid (premier chargement) ou le serveur surchargé. "
                "Vérifiez que le serveur répond, réveillez-le via POST /v1/admin/warmup, puis réessayez."
            )
        if isinstance(last_exc, httpx.ConnectError):
            return (
                f"{base} : connexion impossible. "
                f"Vérifiez que le serveur LLM est démarré et que l'URL {self.base_url} est correcte "
                "(ex. 'ollama serve', 'ollama list'), puis réessayez."
            )
        if last_status == 429:
            return (
                f"{base} : quota / limite de débit dépassée (429). "
                "Patientez quelques secondes, réduisez la fréquence des appels ou vérifiez "
                "votre quota côté fournisseur, puis réessayez."
            )
        if last_status == 408:
            return (
                f"{base} : délai côté serveur (408). "
                "Le modèle met trop longtemps à répondre (froid/surchargé) ; "
                "réveillez-le via POST /v1/admin/warmup puis réessayez."
            )
        if last_status is not None and last_status >= 500:
            return (
                f"{base} : erreur serveur distante ({last_status}). "
                "Le fournisseur est surchargé ou en panne ; patientez puis réessayez, "
                "et vérifiez l'état du serveur et vos logs."
            )
        detail = last_exc if last_exc is not None else last_status
        return f"{base} : échec transitoire ({detail}). Patientez puis réessayez."

    async def _post_with_retry(
        self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """POST JSON avec retry exponentiel borné sur erreurs transitoires uniquement.

        Réessaie (max RETRY_MAX_ATTEMPTS, pauses RETRY_BACKOFF_SECONDS) sur :
        timeouts, erreurs de connexion, 408/429/5xx. Ne réessaie JAMAIS sur les
        autres 4xx (erreurs métier : réponse retournée telle quelle à l'appelant).
        En cas d'épuisement, lève RuntimeError avec un message FR actionnable.
        """
        last_status: int | None = None
        last_exc: Exception | None = None
        async with self._async_client() as client:
            for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    last_status, last_exc = None, exc
                else:
                    if not _is_retryable_status(response.status_code):
                        return response
                    last_status, last_exc = response.status_code, None
                if attempt < RETRY_MAX_ATTEMPTS:
                    await asyncio.sleep(self._retry_delay(attempt))
        raise RuntimeError(
            self._final_transient_message(last_status=last_status, last_exc=last_exc)
        )

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

    async def warmup(self) -> dict[str, Any]:
        """Pré-chauffe le provider (Ollama froid) par un appel léger, sans générer.

        Retourne {"ok", "latency_ms", "error", "provider", "model"} : ne lève
        jamais, pour un usage direct depuis POST /v1/admin/warmup.
        """
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "vision_model": self.vision_model,
            "embed_model": self.embed_model,
            "base_url": self.base_url,
        }

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Conversation avec function-calling natif.

        Retourne {"raw": message assistant natif, "content": str,
        "tool_calls": [{"id", "name", "arguments"}]}.
        """
        raise NotImplementedError

    def format_tool_result(self, name: str, result: Any, call_id: str | None = None) -> dict[str, Any]:
        """Forme le message d'observation d'outil au format natif du provider."""
        raise NotImplementedError


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
        response = await self._post_with_retry(
            f"{self.base_url}/api/generate",
            {
                "model": self.model,
                "prompt": prompt,
                "system": system,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.1},
            },
        )
        raise_for_ollama(response, self.model)
        return parse_json_response(response.json().get("response", "{}"))

    async def generate_vision_json(self, prompt: str, image_base64: str, system: str = "") -> dict[str, Any]:
        """Vision Ollama : lève une erreur FR actionnable, jamais de score inventé.

        Réessaie les pannes transitoires via _post_with_retry (comme generate_json),
        puis lève : 404 modèle absent (hint 'ollama pull'), autre HTTP (corps inclus),
        réponse non-JSON. ImageAnalyzer convertit en repli « vision indisponible ».
        """
        response = await self._post_with_retry(
            f"{self.base_url}/api/generate",
            {
                "model": self.vision_model,
                "prompt": prompt,
                "system": system,
                "images": [image_base64],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.1},
            },
        )
        try:
            raise_for_ollama(response, self.vision_model)
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc} Essayez 'ollama pull {self.vision_model}'."
            ) from exc
        try:
            return parse_json_response(response.json().get("response", "{}"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Modèle vision '{self.vision_model}' : réponse non-JSON ({exc}). "
                "Réessayez ou changez de modèle vision."
            ) from exc

    async def get_embedding(self, text: str) -> list[float]:
        """Embeddings Ollama : lève une erreur FR explicite si aucun modèle ne répond.

        Essaie embed_model puis model (repli conservé), mais ne renvoie plus []
        silencieusement : l'appelant décide du repli (Jaccard, abstention RAG...).
        """
        errors: list[str] = []
        for model in [self.embed_model, self.model]:
            try:
                async with self._async_client(timeout=30.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": model, "prompt": text},
                    )
                if resp.status_code != 200:
                    errors.append(f"{model} : HTTP {resp.status_code}")
                    continue
                return resp.json()["embedding"]
            except KeyError as exc:
                errors.append(f"{model} : réponse sans embedding ({exc})")
            except Exception as exc:
                errors.append(f"{model} : {type(exc).__name__} {str(exc)[:150]}")
        raise RuntimeError(
            f"Embeddings indisponibles (modèles essayés : {self.embed_model}, {self.model}) — "
            f"{'; '.join(errors)}. Vérifiez 'ollama list' / 'ollama pull {self.embed_model}' puis réessayez."
        )


    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if tools:
            payload["tools"] = tools
        try:
            response = await self._post_with_retry(f"{self.base_url}/api/chat", payload)
            raise_for_ollama(response, self.model)
        except httpx.HTTPStatusError as exc:
            if not tools or exc.response.status_code != 400:
                raise
            # Petit modèle sans function-calling (ex. gemma 1B/2B) :
            # on rejoue sans outils plutôt que d'échouer.
            print(f"[ollama] {self.model} refuse les outils (400), repli sans tools.")
            payload = {k: v for k, v in payload.items() if k != "tools"}
            response = await self._post_with_retry(f"{self.base_url}/api/chat", payload)
            raise_for_ollama(response, self.model)
        msg = response.json().get("message", {})
        calls: list[dict[str, Any]] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"id": None, "name": fn.get("name", ""), "arguments": args if isinstance(args, dict) else {}})
        content = msg.get("content", "") or ""
        if not calls and tools:
            calls = extract_text_tool_calls(content, tools)
            if calls:
                content = ""
        return {"raw": msg, "content": content, "tool_calls": calls}

    def format_tool_result(self, name: str, result: Any, call_id: str | None = None) -> dict[str, Any]:
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"role": "tool", "content": content}

    async def warmup(self) -> dict[str, Any]:
        """Réveille un serveur Ollama froid via GET /api/tags (léger, sans génération).

        Ne charge aucun modèle : un simple appel liste suffit à sortir le
        serveur de veille et à valider l'URL. Ne lève jamais : retourne
        {"ok", "latency_ms", "error", "provider", "model"} avec un message
        FR actionnable en cas d'échec.
        """
        started = time.perf_counter()
        timeout = min(self.timeout, _warmup_timeout_seconds())
        try:
            async with self._async_client(timeout=timeout) as client:
                response = await client.get(f"{self.base_url}/api/tags")
        except httpx.TimeoutException:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": (
                    f"Délai dépassé (timeout {timeout}s) au réveil de '{self.model}'. "
                    "Le serveur est froid ou surchargé ; réessayez dans quelques secondes."
                ),
                "provider": self.provider_name,
                "model": self.model,
            }
        except httpx.ConnectError:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": (
                    f"Connexion impossible à {self.base_url}. "
                    "Vérifiez 'ollama serve', 'ollama list' et l'URL configurée, puis réessayez."
                ),
                "provider": self.provider_name,
                "model": self.model,
            }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "provider": self.provider_name,
                "model": self.model,
            }
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 200:
            return {
                "ok": True,
                "latency_ms": latency_ms,
                "error": None,
                "provider": self.provider_name,
                "model": self.model,
            }
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "error": (
                f"Ollama {response.status_code} sur /api/tags pour '{self.model}'. "
                f"Vérifiez 'ollama serve' et l'URL {self.base_url}."
            ),
            "provider": self.provider_name,
            "model": self.model,
        }

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
        response = await self._post_with_retry(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            headers=self._headers(),
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
        response = await self._post_with_retry(
            f"{self.base_url}/chat/completions",
            {
                "model": self.vision_model,
                "messages": messages,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            headers=self._headers(),
        )
        if response.status_code != 200:
            body = " ".join(response.text.split())[:300]
            raise RuntimeError(
                f"Vision '{self.vision_model}' ({self.provider_name}) : HTTP {response.status_code} — "
                f"{body or 'sans détail'}. Vérifiez le modèle, la clé API et l'URL, puis réessayez."
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            return parse_json_response(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Modèle vision '{self.vision_model}' : réponse inattendue ({type(exc).__name__}). "
                "Réessayez ou vérifiez le modèle vision."
            ) from exc

    async def get_embedding(self, text: str) -> list[float]:
        """Embeddings API externe : lève une erreur FR explicite si aucun modèle ne répond.

        Essaie embed_model puis model (repli conservé), mais ne renvoie plus []
        silencieusement : l'appelant décide du repli (Jaccard, abstention RAG...).
        """
        errors: list[str] = []
        for model in [self.embed_model, self.model]:
            try:
                async with self._async_client(timeout=30.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/embeddings",
                        headers=self._headers(),
                        json={"model": model, "input": text},
                    )
                if resp.status_code != 200:
                    errors.append(f"{model} : HTTP {resp.status_code}")
                    continue
                return resp.json()["data"][0]["embedding"]
            except (KeyError, IndexError, TypeError) as exc:
                errors.append(f"{model} : réponse sans embedding ({type(exc).__name__})")
            except Exception as exc:
                errors.append(f"{model} : {type(exc).__name__} {str(exc)[:150]}")
        raise RuntimeError(
            f"Embeddings indisponibles (modèles essayés : {self.embed_model}, {self.model}) — "
            f"{'; '.join(errors)}. Vérifiez le modèle, la clé API et l'URL, puis réessayez."
        )


    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.1}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        response = await self._post_with_retry(
            f"{self.base_url}/chat/completions", payload, headers=self._headers()
        )
        response.raise_for_status()
        msg = response.json()["choices"][0]["message"]
        calls: list[dict[str, Any]] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"id": tc.get("id"), "name": fn.get("name", ""), "arguments": args if isinstance(args, dict) else {}})
        raw = {"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls")}
        return {"raw": raw, "content": msg.get("content") or "", "tool_calls": calls}

    def format_tool_result(self, name: str, result: Any, call_id: str | None = None) -> dict[str, Any]:
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": call_id, "content": content}

    async def warmup(self) -> dict[str, Any]:
        """Valide une API compatible-OpenAI via GET /models (léger, sans génération).

        Un simple appel liste suffit à valider l'URL, la clé API et la
        connectivité, sans consommer de quota de génération. Ne lève jamais :
        retourne {"ok", "latency_ms", "error", "provider", "model"} avec un
        message FR actionnable en cas d'échec.
        """
        started = time.perf_counter()
        timeout = min(self.timeout, _warmup_timeout_seconds())
        try:
            async with self._async_client(timeout=timeout) as client:
                response = await client.get(
                    f"{self.base_url}/models", headers=self._headers()
                )
        except httpx.TimeoutException:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": (
                    f"Délai dépassé (timeout {timeout}s) au réveil de '{self.model}'. "
                    "Le fournisseur est lent ou surchargé ; réessayez dans quelques secondes."
                ),
                "provider": self.provider_name,
                "model": self.model,
            }
        except httpx.ConnectError:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": (
                    f"Connexion impossible à {self.base_url}. "
                    "Vérifiez l'URL de base, votre réseau et la clé API, puis réessayez."
                ),
                "provider": self.provider_name,
                "model": self.model,
            }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "provider": self.provider_name,
                "model": self.model,
            }
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 200:
            return {
                "ok": True,
                "latency_ms": latency_ms,
                "error": None,
                "provider": self.provider_name,
                "model": self.model,
            }
        if response.status_code in (401, 403):
            return {
                "ok": False,
                "latency_ms": latency_ms,
                "error": (
                    f"Authentification refusée ({response.status_code}) pour '{self.model}'. "
                    "Vérifiez la clé API configurée, puis réessayez."
                ),
                "provider": self.provider_name,
                "model": self.model,
            }
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "error": (
                f"Fournisseur {response.status_code} sur /models pour '{self.model}'. "
                f"Vérifiez l'URL {self.base_url} et l'état du fournisseur."
            ),
            "provider": self.provider_name,
            "model": self.model,
        }

PROVIDER_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "openai": OpenAICompatibleProvider,
    "external": OpenAICompatibleProvider,
}
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

    provider_cls = PROVIDER_REGISTRY.get(provider, OllamaProvider)
    return provider_cls(
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
    provider_cls = PROVIDER_REGISTRY.get(provider, OllamaProvider)
    return provider_cls(**kwargs)


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
