from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from typing import Any

import httpx


# --- LOT 5 : robustesse réseau overridable par ENV (défauts historiques) ---

def _env_int(name: str, default: int) -> int:
    """Override ENV typé ; défaut historique inchangé si absent/invalide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float_list(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
    """Override ENV '1.0,2.0,4.0' -> tuple ; défaut si absent/invalide/vide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        values = tuple(float(v) for v in raw.split(",") if v.strip())
    except ValueError:
        return default
    return values if values else default


def _env_int_set(name: str, default: frozenset[int]) -> frozenset[int]:
    """Override ENV '408,429,500' -> frozenset ; défaut si absent/invalide."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        values = frozenset(int(v) for v in raw.split(",") if v.strip())
    except ValueError:
        return default
    return values if values else default


#: Nombre max de tentatives POST (terrain : Ollama froid, 5xx/429 transitoires).
#: Override ENV : LLM_RETRY_MAX_ATTEMPTS (défaut historique 3).
RETRY_MAX_ATTEMPTS = _env_int("LLM_RETRY_MAX_ATTEMPTS", 3)
#: Pauses exponentielles entre réessais (tuple : _retry_delay indexe/slice).
#: Override ENV : LLM_RETRY_BACKOFF_SECONDS="1.0,2.0,4.0".
RETRY_BACKOFF_SECONDS = _env_float_list(
    "LLM_RETRY_BACKOFF_SECONDS", (1.0, 2.0, 4.0))
#: Statuts HTTP transitoires réessayés (jamais les autres 4xx métier).
#: Override ENV : LLM_RETRYABLE_STATUS_CODES="408,429,500,502,503,504".
RETRYABLE_STATUS_CODES = _env_int_set(
    "LLM_RETRYABLE_STATUS_CODES", frozenset({408, 429, 500, 502, 503, 504}))
#: Timeout du warmup (déjà ENV via LLM_WARMUP_TIMEOUT, défaut historique 15s).
WARMUP_TIMEOUT_SECONDS_DEFAULT = 15.0
#: Parallélisme borné du batch embeddings sans endpoint natif (vieux serveurs).
#: Override ENV : LLM_EMBED_CONCURRENCY (défaut historique 4).
EMBED_BATCH_CONCURRENCY = _env_int("LLM_EMBED_CONCURRENCY", 4)

#: Température unique des 6 appels génération (JSON/vision/chat × 2 drivers) :
#: quasi-déterministe, exigé par les schémas stricts (extracteur, vision...).
LLM_TEMPERATURE = 0.1

#: Timeout par défaut des appels LLM (génération/chat), en secondes.
LLM_DEFAULT_TIMEOUT_SECONDS = 120.0
#: Timeout des appels embeddings (rapides, batch natif ou gather borné).
LLM_EMBED_TIMEOUT_SECONDS = 30.0
#: Timeout appliqué aux profils de test sans timeout explicite (page Settings).
PROVIDER_TEST_TIMEOUT_DEFAULT = 30.0

#: Défauts Ollama partagés __init__ + UI PROVIDER_TYPES (zéro duplication).
DEFAULT_OLLAMA_BASE_URL = "http://ollama:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"
#: Défauts API compatible-OpenAI partagés __init__ + UI (zéro duplication).
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_EMBED_MODEL = "text-embedding-3-small"

#: Nom de la variable du modèle vision Ollama (lue aussi par ImageAnalyzer).
VISION_MODEL_ENV_VAR = "OLLAMA_VISION_MODEL"
#: Défaut vision UNIQUE (LOT 5 : moondream partout, provider + ImageAnalyzer).
#: Choix documenté : tests/test_image_vision.py épingle resolve_vision_model()
#: == "moondream" (vert sans toucher aux tests), et la doc déploiement cible
#: 2 Go VRAM (moondream ~1,7 Go ; llama3.2-vision:11b ~7,9 Go n'y passe pas).
#: Grosses machines : OLLAMA_VISION_MODEL=llama3.2-vision:11b (défaut hist.).
DEFAULT_VISION_MODEL = "moondream"

#: Modèle de génération d'image par défaut (API Meta, présumé format OpenAI).
#: Override ENV : OPENAI_IMAGE_MODEL (l'usager validera en live avec sa clé).
DEFAULT_IMAGE_MODEL = "muse-image-1.0"
#: Nom de la variable du modèle d'image.
IMAGE_MODEL_ENV_VAR = "OPENAI_IMAGE_MODEL"
#: Chemin relatif de génération d'images (POST {base}/images/generations).
#: Override ENV : OPENAI_IMAGE_GENERATIONS_PATH (lu à chaque appel).
IMAGE_GENERATIONS_PATH_DEFAULT = "images/generations"
#: Nom de la variable du chemin de génération d'images.
IMAGE_GENERATIONS_PATH_ENV_VAR = "OPENAI_IMAGE_GENERATIONS_PATH"
#: Timeout de génération d'image (s) : les modèles diffusion sont lents.
IMAGE_GENERATION_TIMEOUT_SECONDS = 120.0


class NotSupportedError(RuntimeError):
    """Capacité absente du provider (ex. génération d'image en local)."""


class _OldEmbedApiError(Exception):
    """Signal interne : endpoint batch natif absent (404 = vieux serveur)."""


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


def _image_generations_path() -> str:
    """Chemin images/generations : défaut OpenAI, configurable via ENV (lu à chaque appel)."""
    raw = (os.getenv(IMAGE_GENERATIONS_PATH_ENV_VAR, IMAGE_GENERATIONS_PATH_DEFAULT) or "").strip().strip("/")
    return raw or IMAGE_GENERATIONS_PATH_DEFAULT


def _image_model() -> str:
    """Modèle d'image : ENV dédiée, sinon défaut Meta (lu à chaque appel)."""
    raw = (os.getenv(IMAGE_MODEL_ENV_VAR, "") or "").strip()
    return raw or DEFAULT_IMAGE_MODEL


def parse_json_response(raw: str) -> dict[str, Any]:
    """Parse une réponse LLM en JSON, tolérant aux blocs markdown."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(cleaned)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_fences(raw: str) -> str:
    """Contenu du premier bloc markdown clôturé, ou le texte inchangé."""
    match = _FENCE_RE.search(raw)
    return match.group(1).strip() if match else raw


def repair_json_response(raw: str) -> dict[str, Any]:
    """Parse JSON tolérant : fences, prose autour, virgules traînantes.

    Répare uniquement la syntaxe (jamais de défauts sémantiques) : JSON
    direct, puis contenu des fences markdown, puis premier bloc équilibré
    {...}, puis suppression des virgules traînantes. En échec, relève
    l'erreur d'origine (pas de JSON plausible-mais-faux).
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as original:
        fenced = _strip_fences(raw)
        if fenced != raw:
            try:
                return json.loads(fenced)
            except json.JSONDecodeError:
                pass
        for block in _iter_json_blocks(raw):
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue
        scrubbed = _TRAILING_COMMA_RE.sub(r"\1", raw)
        if scrubbed != raw:
            try:
                return json.loads(scrubbed)
            except json.JSONDecodeError:
                pass
            for block in _iter_json_blocks(scrubbed):
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    continue
        raise original


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


def _run_validator(validator: Any, data: dict[str, Any]) -> tuple[bool, Exception | None]:
    """Valide un JSON réparé : classe pydantic (model_validate) ou callable."""
    checker = getattr(validator, "model_validate", None)
    try:
        if callable(checker):
            checker(data)
            return True, None
        if callable(validator):
            return (True, None) if validator(data) else (
                False, ValueError("contenu rejeté par le validateur"))
        return True, None
    except Exception as exc:
        return False, exc


def _attach_raw(exc: json.JSONDecodeError, raw: str) -> json.JSONDecodeError:
    """Attache le brut à l'erreur pour la réparation (parse inchangé)."""
    exc.raw_content = raw  # type: ignore[attr-defined]
    return exc


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
            try:
                data = repair_json_response(candidate)
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
        timeout: float = LLM_DEFAULT_TIMEOUT_SECONDS,
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
        self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """POST JSON avec retry exponentiel borné sur erreurs transitoires uniquement.

        Réessaie (max RETRY_MAX_ATTEMPTS, pauses RETRY_BACKOFF_SECONDS) sur :
        timeouts, erreurs de connexion, 408/429/5xx. Ne réessaie JAMAIS sur les
        autres 4xx (erreurs métier : réponse retournée telle quelle à l'appelant).
        En cas d'épuisement, lève RuntimeError avec un message FR actionnable.
        `timeout` surcharge le timeout du client pour cet appel (None = défaut).
        """
        last_status: int | None = None
        last_exc: Exception | None = None
        async with self._async_client(timeout=timeout) as client:
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

    async def generate_json_repaired(
        self,
        prompt: str,
        system: str = "",
        validator: Any = None,
        retries: int = 1,
    ) -> dict[str, Any]:
        """generate_json + réparation syntaxique + validation optionnelle.

        Sur JSON malformé, répare le brut (fences/prose/virgules) au lieu
        d'échouer ; `validator` (classe pydantic ou callable) peut rejeter
        le contenu. Un seul réessai LLM avec consigne « JSON only » en cas
        d'échec persistant, puis l'erreur honnête remonte (jamais de
        contenu inventé). `repair_used` est journalisé pour le suivi.
        """
        suffix = "\n(reply with JSON only, no prose)"
        current = prompt
        last_error: Exception | None = None
        for _ in range(1 + max(0, int(retries))):
            data: dict[str, Any] | None = None
            try:
                data = await self.generate_json(current, system)
            except json.JSONDecodeError as exc:
                last_error = exc
                raw = getattr(exc, "raw_content", None)
                if raw is not None:
                    try:
                        data = repair_json_response(raw)
                    except json.JSONDecodeError:
                        data = None
                    else:
                        print(f"[{self.provider_name}] JSON réparé (repair_used).")
                        last_error = None
            if data is not None and validator is not None:
                ok, detail = _run_validator(validator, data)
                if not ok:
                    last_error = detail
                    data = None
            if data is not None:
                return data
            current = prompt + suffix
        if isinstance(last_error, json.JSONDecodeError):
            raise last_error
        raise RuntimeError(
            f"LLM '{self.model}' ({self.provider_name}) : réponse JSON inexploitable "
            f"après réessai ({last_error}). Reformulez ou changez de modèle."
        )

    async def generate_vision_json(self, prompt: str, image_base64: str, system: str = "") -> dict[str, Any]:
        raise NotImplementedError

    async def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes:
        """Génère une image -> octets bruts. Défaut : non supporté (drivers cloud uniquement)."""
        raise NotSupportedError(
            f"{self.provider_name} ne génère pas d'images : génération d'image cloud uniquement "
            "(profil 'openai_compatible' + clé API)."
        )

    async def get_embedding(self, text: str) -> list[float]:
        raise NotImplementedError

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch par défaut : unitaires parallélisés bornés (vieux serveurs).

        Les providers à batch natif le surchargent. Ordre préservé.
        """
        if not texts:
            return []
        sem = asyncio.Semaphore(EMBED_BATCH_CONCURRENCY)

        async def one(text: str) -> list[float]:
            async with sem:
                return await self.get_embedding(text)

        return list(await asyncio.gather(*(one(t) for t in texts)))

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

    async def chat_with_image(
        self,
        messages: list[dict[str, Any]],
        image_base64: str,
        image_mime: str = "image/jpeg",
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Conversation en voyant la photo jointe (même retour que chat()).

        Implémentation par défaut : NotImplementedError — l'appelant
        (boucle agent) replie alors sur le chat texte avec le résumé
        déterministe de l'analyse vision. Ne jamais laisser fuir
        l'exception jusqu'à l'utilisateur : repli texte, jamais de crash.
        """
        raise NotImplementedError(
            f"{self.provider_name} ne supporte pas la vision dans le chat."
        )

    def format_tool_result(self, name: str, result: Any, call_id: str | None = None) -> dict[str, Any]:
        """Forme le message d'observation d'outil au format natif du provider."""
        raise NotImplementedError


def _openai_multimodal_messages(
    messages: list[dict[str, Any]], image_base64: str, image_mime: str
) -> list[dict[str, Any]]:
    """Copie des messages dont le dernier user devient multimodal (fonction pure).

    Contenu OpenAI : [{"type": "text", ...}, {"type": "image_url", ...}].
    Sans message user texte : liste inchangée (jamais de crash).
    """
    mime = image_mime if image_mime and "/" in image_mime else "image/jpeg"
    converted = [dict(m) for m in messages]
    for message in reversed(converted):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            message["content"] = [
                {"type": "text", "text": message["content"]},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_base64}"}},
            ]
            break
    return converted


def _ollama_image_messages(
    messages: list[dict[str, Any]], image_base64: str
) -> list[dict[str, Any]]:
    """Copie des messages dont le dernier user porte images:[b64] (fonction pure).

    Format /api/chat natif Ollama. Sans message user : inchangé.
    """
    converted = [dict(m) for m in messages]
    for message in reversed(converted):
        if message.get("role") == "user":
            message["images"] = [image_base64]
            break
    return converted


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
            base_url=base_url or os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_BASE_URL),
            model=model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            vision_model=vision_model or os.getenv(VISION_MODEL_ENV_VAR, DEFAULT_VISION_MODEL),
            embed_model=embed_model or os.getenv("OLLAMA_EMBED_MODEL", DEFAULT_OLLAMA_EMBED_MODEL),
            api_key=api_key,
            timeout=timeout or float(os.getenv("OLLAMA_TIMEOUT", str(LLM_DEFAULT_TIMEOUT_SECONDS))),
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
                "options": {"temperature": LLM_TEMPERATURE},
            },
        )
        raise_for_ollama(response, self.model)
        content = response.json().get("response", "{}")
        try:
            return parse_json_response(content)
        except json.JSONDecodeError as exc:
            raise _attach_raw(exc, content) from exc

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
                "options": {"temperature": LLM_TEMPERATURE},
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

    async def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes:
        """Ollama ne génère pas d'images : refus propre, jamais de crash obscur."""
        raise NotSupportedError(
            "Ollama ne génère pas d'images : génération d'image cloud uniquement "
            "(basculez sur un profil 'openai_compatible' avec clé API)."
        )

    async def get_embedding(self, text: str) -> list[float]:
        """Embeddings Ollama : batch natif, sinon unitaires ; lève en FR sinon.

        Essaie embed_model puis model (repli conservé), mais ne renvoie plus []
        silencieusement : l'appelant décide du repli (Jaccard, abstention RAG...).
        """
        return (await self.get_embeddings([text]))[0]

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch Ollama : /api/embed natif, sinon gather borné (vieux serveurs)."""
        if not texts:
            return []
        errors: list[str] = []
        for model in [self.embed_model, self.model]:
            try:
                return await self._embed_batch_native(model, texts)
            except _OldEmbedApiError:
                # 404 = endpoint absent (vieux serveur), pas le modèle : repli.
                return await self._embed_batch_gather(model, texts)
            except RuntimeError as exc:
                errors.append(f"{model} : {exc}")
        raise RuntimeError(
            f"Embeddings indisponibles (modèles essayés : {self.embed_model}, {self.model}) — "
            f"{'; '.join(errors)}. Vérifiez 'ollama list' / 'ollama pull {self.embed_model}' puis réessayez."
        )

    async def _embed_batch_native(
        self, model: str, texts: list[str]
    ) -> list[list[float]]:
        response = await self._post_with_retry(
            f"{self.base_url}/api/embed",
            {"model": model, "input": list(texts)},
            timeout=LLM_EMBED_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            body = response.text.lower()
            if "model" in body and "not found" in body:
                # Modèle absent : passer au modèle suivant (message FR dédié).
                raise_for_ollama(response, model)
            raise _OldEmbedApiError(model)
        raise_for_ollama(response, model)
        try:
            vectors = response.json()["embeddings"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"{model} : réponse sans embeddings ({exc})")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError(
                f"{model} : batch incomplet ({len(vectors) if isinstance(vectors, list) else '?'}"
                f"/{len(texts)} vecteurs)")
        return vectors

    async def _embed_batch_gather(
        self, model: str, texts: list[str]
    ) -> list[list[float]]:
        """Repli vieux serveurs : unitaires parallélisés, un seul client."""
        sem = asyncio.Semaphore(EMBED_BATCH_CONCURRENCY)
        errors: list[str] = []

        async def one(client: httpx.AsyncClient, text: str) -> list[float] | None:
            async with sem:
                try:
                    resp = await client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": model, "prompt": text},
                    )
                except Exception as exc:  # noqa: BLE001 - agrégée, levée après
                    errors.append(f"{type(exc).__name__} {str(exc)[:120]}")
                    return None
                if resp.status_code != 200:
                    errors.append(f"HTTP {resp.status_code}")
                    return None
                try:
                    return resp.json()["embedding"]
                except KeyError:
                    errors.append("réponse sans embedding")
                    return None

        async with self._async_client(timeout=LLM_EMBED_TIMEOUT_SECONDS) as client:
            vectors = await asyncio.gather(*(one(client, t) for t in texts))
        if any(v is None for v in vectors) or len(vectors) != len(texts):
            raise RuntimeError(
                f"{model} : batch unitaire incomplet ({'; '.join(errors[:3]) or 'sans détail'})")
        return [v for v in vectors if v is not None]


    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return await self._chat_with_model(messages, tools, self.model)

    async def chat_with_image(
        self,
        messages: list[dict[str, Any]],
        image_base64: str,
        image_mime: str = "image/jpeg",
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Chat /api/chat en voyant la photo (dernier user + images:[b64]).

        Utilise le modèle vision (le modèle texte ne sait pas voir).
        `image_mime` accepté pour le contrat, sans usage (b64 brut suffit).
        """
        _ = image_mime
        return await self._chat_with_model(
            _ollama_image_messages(messages, image_base64), tools, self.vision_model
        )

    async def _chat_with_model(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
        model: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": LLM_TEMPERATURE},
        }
        if tools:
            payload["tools"] = tools
        try:
            response = await self._post_with_retry(f"{self.base_url}/api/chat", payload)
            raise_for_ollama(response, model)
        except httpx.HTTPStatusError as exc:
            if not tools or exc.response.status_code != 400:
                raise
            # Petit modèle sans function-calling (ex. gemma 1B/2B) :
            # on rejoue sans outils plutôt que d'échouer.
            print(f"[ollama] {model} refuse les outils (400), repli sans tools.")
            payload = {k: v for k, v in payload.items() if k != "tools"}
            response = await self._post_with_retry(f"{self.base_url}/api/chat", payload)
            raise_for_ollama(response, model)
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
            base_url=base_url or os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            model=model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            vision_model=vision_model or os.getenv("OPENAI_VISION_MODEL") or None,
            embed_model=embed_model or os.getenv("OPENAI_EMBED_MODEL", DEFAULT_OPENAI_EMBED_MODEL),
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            timeout=timeout or float(os.getenv("OPENAI_TIMEOUT", str(LLM_DEFAULT_TIMEOUT_SECONDS))),
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
                "temperature": LLM_TEMPERATURE,
                "response_format": {"type": "json_object"},
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        try:
            return parse_json_response(content)
        except json.JSONDecodeError as exc:
            raise _attach_raw(exc, content) from exc

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
                "temperature": LLM_TEMPERATURE,
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

    async def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes:
        """Génère une image (format OpenAI POST {base}/images/generations) -> octets bruts.

        Payload {"model", "prompt", "size"} ; modèle via OPENAI_IMAGE_MODEL
        (défaut muse-image-1.0), chemin via OPENAI_IMAGE_GENERATIONS_PATH.
        Réponse b64_json décodée directement, réponse url téléchargée
        (data-URL sans réseau, http(s) via GET). Timeout 120 s, erreurs FR.
        """
        if not (prompt or "").strip():
            raise ValueError("generate_image : prompt vide, image impossible.")
        model = _image_model()
        url = f"{self.base_url}/{_image_generations_path()}"
        response = await self._post_with_retry(
            url,
            {"model": model, "prompt": prompt.strip(),
             "size": (size or "").strip() or "1024x1024"},
            headers=self._headers(),
            timeout=IMAGE_GENERATION_TIMEOUT_SECONDS,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(
                f"Génération d'image refusée ({response.status_code}) : clé API "
                "invalide ou sans droit image. Vérifiez la clé, puis réessayez."
            )
        if response.status_code == 404:
            raise RuntimeError(
                f"Génération d'image introuvable (404 sur {url}) : chemin ou "
                f"modèle '{model}' inconnu. Vérifiez "
                f"{IMAGE_GENERATIONS_PATH_ENV_VAR} et {IMAGE_MODEL_ENV_VAR}, "
                "puis réessayez."
            )
        if response.is_error:
            body = " ".join(response.text.split())[:300]
            raise RuntimeError(
                f"Génération d'image échouée (HTTP {response.status_code}) : "
                f"{body or 'sans détail'}. Vérifiez le prompt, le modèle, "
                "le quota, puis réessayez."
            )
        try:
            items = response.json().get("data") or []
            first = items[0] if items else {}
        except (ValueError, AttributeError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "Génération d'image : réponse inattendue (JSON sans 'data'). "
                "Vérifiez le fournisseur, puis réessayez."
            ) from exc
        if not isinstance(first, dict):
            raise RuntimeError(
                "Génération d'image : réponse inattendue ('data[0]' illisible). "
                "Vérifiez le fournisseur, puis réessayez."
            )
        if first.get("b64_json"):
            try:
                return base64.b64decode(first["b64_json"], validate=True)
            except ValueError as exc:
                raise RuntimeError(
                    "Génération d'image : 'b64_json' illisible (base64 invalide). "
                    "Réessayez."
                ) from exc
        remote = str(first.get("url") or "").strip()
        if remote.startswith("data:") and ";base64," in remote:
            try:
                return base64.b64decode(remote.split(";base64,", 1)[1], validate=True)
            except ValueError as exc:
                raise RuntimeError(
                    "Génération d'image : data-URL illisible (base64 invalide). "
                    "Réessayez."
                ) from exc
        if remote.startswith(("http://", "https://")):
            try:
                async with self._async_client(
                    timeout=IMAGE_GENERATION_TIMEOUT_SECONDS
                ) as client:
                    download = await client.get(remote)
            except Exception as exc:  # noqa: BLE001 - traduite en FR explicite
                raise RuntimeError(
                    f"Téléchargement de l'image impossible "
                    f"({remote[:80]}...) : {type(exc).__name__}. "
                    "Vérifiez le réseau, puis réessayez."
                ) from exc
            if download.status_code != 200 or not download.content:
                raise RuntimeError(
                    f"Téléchargement de l'image échoué "
                    f"(HTTP {download.status_code}). Réessayez."
                )
            return bytes(download.content)
        raise RuntimeError(
            "Génération d'image : réponse sans 'b64_json' ni 'url'. "
            "Vérifiez le fournisseur, puis réessayez."
        )

    async def get_embedding(self, text: str) -> list[float]:
        """Embeddings API externe : batch natif ; lève en FR explicite sinon."""
        return (await self.get_embeddings([text]))[0]

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch natif /embeddings (input tableau), avec retry transitoires."""
        if not texts:
            return []
        errors: list[str] = []
        for model in [self.embed_model, self.model]:
            try:
                response = await self._post_with_retry(
                    f"{self.base_url}/embeddings",
                    {"model": model, "input": list(texts)},
                    headers=self._headers(),
                    timeout=LLM_EMBED_TIMEOUT_SECONDS,
                )
                if response.status_code != 200:
                    errors.append(f"{model} : HTTP {response.status_code}")
                    continue
                items = response.json()["data"]
                vectors = [it["embedding"] for it in
                           sorted(items, key=lambda d: d.get("index", 0))]
                if len(vectors) != len(texts):
                    errors.append(
                        f"{model} : batch incomplet ({len(vectors)}/{len(texts)})")
                    continue
                return vectors
            except (KeyError, IndexError, TypeError) as exc:
                errors.append(f"{model} : réponse sans embedding ({type(exc).__name__})")
            except RuntimeError as exc:
                # Retry épuisé (serveur down/surchargé) : vers le message final.
                errors.append(f"{model} : {exc}")
                continue
            except Exception as exc:
                errors.append(f"{model} : {type(exc).__name__} {str(exc)[:150]}")
        raise RuntimeError(
            f"Embeddings indisponibles (modèles essayés : {self.embed_model}, {self.model}) — "
            f"{'; '.join(errors)}. Vérifiez le modèle, la clé API et l'URL, puis réessayez."
        )


    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return await self._chat_with_model(messages, tools, self.model)

    async def chat_with_image(
        self,
        messages: list[dict[str, Any]],
        image_base64: str,
        image_mime: str = "image/jpeg",
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Chat /chat/completions en voyant la photo (contenu multimodal).

        Dernier message user -> content=[{type:text},{type:image_url,...}].
        Utilise le modèle vision (= modèle texte par défaut).
        """
        return await self._chat_with_model(
            _openai_multimodal_messages(messages, image_base64, image_mime),
            tools, self.vision_model,
        )

    async def _chat_with_model(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
        model: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": LLM_TEMPERATURE}
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
        "timeout": float(profile.get("timeout") or PROVIDER_TEST_TIMEOUT_DEFAULT),
    }
    provider_cls = PROVIDER_REGISTRY.get(provider, OllamaProvider)
    return provider_cls(**kwargs)


# LOT 5 : les `default:` UI sont générés depuis les MÊMES ENV que les
# __init__ (zéro duplication de valeur : un seul DEFAULT_* par champ).
PROVIDER_TYPES: list[dict[str, Any]] = [
    {
        "id": "ollama",
        "label": "Ollama (modèle local)",
        "description": "Modèles hébergés localement : Llama, Gemma, Llava, nomic-embed. Gratuit, privé, sans clé API.",
        "api_key_required": False,
        "fields": [
            {"name": "base_url", "label": "URL Ollama", "type": "url", "default": os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_BASE_URL), "required": True},
            {"name": "model", "label": "Modèle texte", "type": "text", "default": os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL), "required": True},
            {"name": "vision_model", "label": "Modèle vision", "type": "text", "default": os.getenv(VISION_MODEL_ENV_VAR, DEFAULT_VISION_MODEL), "required": False},
            {"name": "embed_model", "label": "Modèle embeddings", "type": "text", "default": os.getenv("OLLAMA_EMBED_MODEL", DEFAULT_OLLAMA_EMBED_MODEL), "required": False},
        ],
    },
    {
        "id": "openai_compatible",
        "label": "API externe (format OpenAI)",
        "description": "OpenAI, Groq, Together, Mistral, ou tout endpoint compatible /v1. Nécessite une clé API.",
        "api_key_required": True,
        "fields": [
            {"name": "base_url", "label": "URL de base (/v1)", "type": "url", "default": os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL), "required": True},
            {"name": "model", "label": "Modèle texte", "type": "text", "default": os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL), "required": True},
            {"name": "vision_model", "label": "Modèle vision", "type": "text", "default": os.getenv("OPENAI_VISION_MODEL", ""), "required": False},
            {"name": "embed_model", "label": "Modèle embeddings", "type": "text", "default": os.getenv("OPENAI_EMBED_MODEL", DEFAULT_OPENAI_EMBED_MODEL), "required": False},
        ],
    },
]
