"""Provider STT Meta Omnilingual ASR (CTC) pour le ghomala' (bbj_Latn).

Meta Omnilingual ASR couvre bbj_Latn nativement (1600+ langues, Apache 2.0).
Checkpoint CTC officiel : ``facebook/omniASR-CTC-300M``
(dépôt github ``facebookresearch/omnilingual-asr``).

Contraintes machine (i5 11e, GPU 2 Go inutilisable) : 100 % CPU.
Priorité des backends, explicite et exposée via la clé ``backend`` :
1. sherpa-onnx (ONNX int8, idéal CPU) si importable ;
2. transformers (checkpoint CTC PyTorch) sinon.

Chargement LAZY : aucun import lourd (sherpa_onnx, transformers, torch,
numpy) au sommet du module, aucun poids chargé à l'import ni au
constructeur. Si aucun backend n'est utilisable (driver ou modèle absent),
``transcribe`` lève une erreur EXPLICITE avec les commandes de
téléchargement — jamais de substitution silencieuse, jamais de crash import.

Téléchargement du modèle (à lancer par l'usager, réseau requis, ~365 Mo) ::

    pip install sherpa-onnx huggingface_hub
    huggingface-cli download \\
        csukuangfj/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12 \\
        model.int8.onnx tokens.txt --local-dir /models/omnilingual

Repli transformers (checkpoint PyTorch officiel, CPU) ::

    pip install transformers torch --index-url https://download.pytorch.org/whl/cpu
    python -c "from huggingface_hub import snapshot_download; \\
        snapshot_download('facebook/omniASR-CTC-300M')"
"""
from __future__ import annotations

import os
import struct
import tempfile
import wave
from typing import Any

try:  # importé via « app.stt_omnilingual » (tests, moteur)
    from app.stt_providers import (
        STT_SAMPLE_RATE_HZ,
        BaseSTTProvider,
        SUPPORTED_VOICE_LANGUAGES,
        normalize_to_wav,
    )
except ImportError:  # pragma: no cover - contexte paquet relatif
    try:
        from .stt_providers import (
            STT_SAMPLE_RATE_HZ,
            BaseSTTProvider,
            SUPPORTED_VOICE_LANGUAGES,
            normalize_to_wav,
        )
    except ImportError:  # pragma: no cover - dossier app/ sur sys.path
        from stt_providers import (  # type: ignore[no-redef]
            STT_SAMPLE_RATE_HZ,
            BaseSTTProvider,
            SUPPORTED_VOICE_LANGUAGES,
            normalize_to_wav,
        )

#: Checkpoint CTC officiel Meta (repli transformers, 100 % CPU).
#: Override ENV : OMNI_CTC_HF_MODEL (mapping > ENV > ce défaut, cf. __init__).
OMNI_CTC_HF_REPO = "facebook/omniASR-CTC-300M"

#: Export ONNX int8 officiel k2-fsa/sherpa-onnx (prioritaire, idéal CPU).
OMNI_CTC_ONNX_REPO = (
    "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12"
)
#: Dépôt ONNX complet, overridable (miroir local/nas) via OMNI_CTC_ONNX_REPO.
OMNI_CTC_ONNX_REPO_FULL = os.getenv(
    "OMNI_CTC_ONNX_REPO", f"csukuangfj/{OMNI_CTC_ONNX_REPO}")

#: Commandes exactes à lancer par l'usager (rappelées dans les erreurs).
OMNI_CTC_ONNX_DOWNLOAD_CMD = (
    "huggingface-cli download "
    f"{OMNI_CTC_ONNX_REPO_FULL} model.int8.onnx tokens.txt "
    "--local-dir /models/omnilingual"
)
OMNI_CTC_HF_DOWNLOAD_CMD = (
    "python -c \"from huggingface_hub import snapshot_download; "
    f"snapshot_download('{OMNI_CTC_HF_REPO}')\""
)

DEFAULT_CTC_ONNX_MODEL = "/models/omnilingual/model.int8.onnx"
DEFAULT_CTC_TOKENS = "/models/omnilingual/tokens.txt"

CTC_BACKENDS = ("auto", "sherpa", "transformers")


class OmnilingualCTCProvider(BaseSTTProvider):
    """Transcription ghomala' (bbj_Latn) via Meta Omnilingual ASR CTC, 100 % CPU."""

    driver_name = "omnilingual_ctc"

    def __init__(
        self,
        model: str | None = None,
        tokens: str | None = None,
        hf_model: str | None = None,
        backend: str = "auto",
        num_threads: int = 2,
        provider: str = "cpu",
        timeout: float = 180.0,
    ):
        backend = (backend or "auto").strip().lower()
        if backend not in CTC_BACKENDS:
            raise ValueError(
                f"Backend Omnilingual CTC inconnu : {backend!r} "
                f"(attendu : {', '.join(CTC_BACKENDS)})."
            )
        # Chemins ONNX : mapping > env dédiée > env historique > défaut.
        self.model = (
            model
            or os.getenv("OMNI_CTC_MODEL")
            or os.getenv("OMNI_STT_MODEL")
            or DEFAULT_CTC_ONNX_MODEL
        )
        self.tokens = (
            tokens
            or os.getenv("OMNI_CTC_TOKENS")
            or os.getenv("OMNI_STT_TOKENS")
            or DEFAULT_CTC_TOKENS
        )
        self.hf_model = (
            hf_model or os.getenv("OMNI_CTC_HF_MODEL") or OMNI_CTC_HF_REPO
        )
        self.backend = backend
        self.num_threads = num_threads
        self.provider = provider
        self.timeout = timeout
        # Handles paresseux : jamais chargés ici (ni à l'import du module).
        self._sherpa_recognizer: Any = None
        self._hf: Any = None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "OmnilingualCTCProvider":
        return cls(
            model=mapping.get("model") or None,
            tokens=mapping.get("tokens") or None,
            hf_model=mapping.get("hf_model") or mapping.get("hf") or None,
            backend=mapping.get("backend") or "auto",
            num_threads=int(mapping.get("threads") or 2),
            provider=mapping.get("provider") or "cpu",
            timeout=float(mapping.get("timeout") or 180.0),
        )

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info.update({"backend": self.backend, "model": self.model})
        return info

    # -- Chargement paresseux -------------------------------------------------

    @staticmethod
    def _import_sherpa() -> Any:
        """Module sherpa_onnx ou None (sonde, ne lève jamais)."""
        try:
            import sherpa_onnx

            return sherpa_onnx
        except ImportError:
            return None

    @staticmethod
    def _import_transformers() -> tuple[Any, Any] | None:
        """Modules (transformers, torch) ou None (sonde, ne lève jamais)."""
        try:
            import torch
            import transformers

            return transformers, torch
        except ImportError:
            return None

    def _load_sherpa(self) -> Any:
        """Charge (une fois) le recognizer sherpa-onnx int8, ou erreur explicite."""
        if self._sherpa_recognizer is not None:
            return self._sherpa_recognizer
        sherpa_onnx = self._import_sherpa()
        if sherpa_onnx is None:
            raise RuntimeError(
                "Omnilingual CTC indisponible : sherpa-onnx non installé "
                "(pip install sherpa-onnx ; 100 % CPU, aucune GPU requise)."
            )
        if not os.path.isfile(self.model):
            raise RuntimeError(
                f"Omnilingual CTC indisponible : modèle ONNX introuvable "
                f"({self.model}). Téléchargez-le avec : "
                f"{OMNI_CTC_ONNX_DOWNLOAD_CMD}"
            )
        if not os.path.isfile(self.tokens):
            raise RuntimeError(
                f"Omnilingual CTC indisponible : tokens introuvables "
                f"({self.tokens}). Téléchargez-les avec : "
                f"{OMNI_CTC_ONNX_DOWNLOAD_CMD}"
            )
        self._sherpa_recognizer = (
            sherpa_onnx.OfflineRecognizer.from_omnilingual_asr_ctc(
                model=self.model,
                tokens=self.tokens,
                num_threads=self.num_threads,
                provider=self.provider,
            )
        )
        return self._sherpa_recognizer

    def _load_transformers(self) -> Any:
        """Charge (une fois) le checkpoint CTC HF, ou erreur explicite."""
        if self._hf is not None:
            return self._hf
        probed = self._import_transformers()
        if probed is None:
            raise RuntimeError(
                "Omnilingual CTC indisponible : transformers/torch non installés "
                "(pip install transformers torch --index-url "
                "https://download.pytorch.org/whl/cpu ; 100 % CPU)."
            )
        transformers, _torch = probed
        try:
            processor = transformers.AutoProcessor.from_pretrained(self.hf_model)
            model = transformers.AutoModelForCTC.from_pretrained(self.hf_model)
            model.eval()
        except Exception as exc:
            raise RuntimeError(
                f"Omnilingual CTC indisponible : checkpoint {self.hf_model!r} "
                f"inaccessible ({exc}). Pré-téléchargez-le avec : "
                f"{OMNI_CTC_HF_DOWNLOAD_CMD}"
            ) from exc
        self._hf = (processor, model)
        return self._hf

    def _load(self) -> tuple[str, Any]:
        """Backend effectif : sherpa-onnx d'abord, transformers sinon.

        Retourne (nom_backend, handle). Lève une erreur EXPLICITE si aucun
        backend n'est utilisable — jamais de repli silencieux vers un autre
        moteur (ni Whisper, ni transcription vide).
        """
        errors: list[str] = []
        if self.backend in ("auto", "sherpa"):
            try:
                return "sherpa_onnx", self._load_sherpa()
            except RuntimeError as exc:
                if self.backend == "sherpa":
                    raise
                errors.append(str(exc))
        if self.backend in ("auto", "transformers"):
            try:
                return "transformers", self._load_transformers()
            except RuntimeError as exc:
                if self.backend == "transformers":
                    raise
                errors.append(str(exc))
        detail = " | ".join(errors) if errors else "aucun backend demandé"
        raise RuntimeError(f"Omnilingual CTC indisponible : {detail}.")

    # -- Décodage -------------------------------------------------------------

    @staticmethod
    def _read_wav_samples(wav_file: str) -> list[float]:
        """Échantillons flottants normalisés d'un WAV 16 kHz mono 16 bits."""
        with wave.open(wav_file, "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise RuntimeError(
                    "Format WAV inattendu après normalisation "
                    "(16 kHz mono 16 bits requis)."
                )
            raw = w.readframes(w.getnframes())
        count = len(raw) // 2
        return [s / 32768.0 for s in struct.unpack(f"<{count}h", raw[: count * 2])]

    def _decode_sherpa(self, recognizer: Any, samples: list[float]) -> str:
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "Omnilingual CTC indisponible : numpy non installé "
                "(pip install numpy)."
            ) from exc
        stream = recognizer.create_stream()
        stream.accept_waveform(STT_SAMPLE_RATE_HZ, np.array(samples, dtype=np.float32))
        recognizer.decode_stream(stream)
        return (stream.result.text or "").strip()

    def _decode_transformers(self, handle: Any, samples: list[float]) -> str:
        transformers_torch = self._import_transformers()
        if transformers_torch is None:  # pragma: no cover - _load l'a exigé
            raise RuntimeError("Omnilingual CTC indisponible : torch non installé.")
        _transformers, torch = transformers_torch
        processor, model = handle
        inputs = processor(samples, sampling_rate=STT_SAMPLE_RATE_HZ, return_tensors="pt")
        with torch.no_grad():
            logits = model(inputs.input_values).logits
        pred_ids = torch.argmax(logits, dim=-1)
        return (processor.batch_decode(pred_ids)[0] or "").strip()

    # -- Contrat BaseSTTProvider ----------------------------------------------

    def transcribe(
        self, audio_bytes: bytes, filename: str, language: str
    ) -> dict[str, Any]:
        # Le modèle CTC couvre bbj_Latn nativement, mais un code inconnu reste
        # un typo : échouer bruyamment plutôt que transcrire en langue mystère.
        if language not in SUPPORTED_VOICE_LANGUAGES:
            raise ValueError(f"Langue vocale non prise en charge : {language!r}.")
        backend_name, handle = self._load()
        with tempfile.TemporaryDirectory(prefix="wash-omni-ctc-") as tmpdir:
            wav_file = normalize_to_wav(audio_bytes, filename, tmpdir)
            samples = self._read_wav_samples(wav_file)
        if backend_name == "sherpa_onnx":
            text = self._decode_sherpa(handle, samples)
        else:
            text = self._decode_transformers(handle, samples)
        return {
            "transcript": text,
            "text": text,
            "language": language,
            # Pas de mapping : bbj_Latn est reconnu nativement par le CTC.
            "language_effective": language,
            "engine": self.driver_name,
            "backend": backend_name,
        }
