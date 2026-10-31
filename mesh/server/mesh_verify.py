"""Signatures Ed25519 des bundles mesh (V2 « signatures nœuds »).

Le checksum SHA-256 détecte la corruption, pas la malice. La signature prouve
que le bundle vient du détenteur de la clé du nœud origine.

Format (identique TS `mesh-sdk.ts#canonicalBytes`, PHP `MeshSignature`) :
- `signature` : Ed25519 détachée (64 o.), base64 STANDARD avec padding (88 car.).
- `node_pubkey` : clé publique Ed25519, base64 standard (44 car.), auto-annoncée
  (TOFU) ; INCLUSE dans les octets signés.
- Octets signés : JSON compact (séparateurs `,`/`:`), clés triées, UTF-8 brut
  (accents et slashs NON échappés), champs {checksum, hops, previous_node,
  copies_remaining, signature} exclus, valeurs None omises.

IMPORTANT — passer le dict JSON REÇU (chaînes intactes, dates ISO d'origine).
Ne jamais re-sérialiser des objets date parsés (`…Z` ≠ `…+00:00`). Les valeurs
datetime Python sont tolérées (normalisées en `…SS.sssZ`) pour le chemin
`model_dump(mode="python")`, mais le chemin brut reste la référence.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import date, datetime, timezone
from typing import Any, Mapping

SIGN_EXCLUDED = frozenset({"checksum", "hops", "previous_node", "copies_remaining", "signature"})

PUBLIC_KEY_BYTES = 32
SECRET_KEY_BYTES = 64  # format libsodium : seed 32 o. || pubkey 32 o.
SIGNATURE_BYTES = 64


def _canon_value(value: Any) -> Any:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def canonical_string(bundle: Mapping[str, Any]) -> str:
    """Forme canonique signée — à l'octet près comme TS et PHP."""
    payload = {k: _canon_value(v) for k, v in bundle.items() if k not in SIGN_EXCLUDED and v is not None}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_bytes(bundle: Mapping[str, Any]) -> bytes:
    """Octets UTF-8 de la forme canonique — l'entrée exacte d'Ed25519."""
    return canonical_string(bundle).encode("utf-8")


def _use_nacl() -> bool:
    try:
        import nacl.signing  # noqa: F401

        return True
    except ImportError:
        return False


def is_available() -> bool:
    """True si une implémentation Ed25519 est importable (nacl ou cryptography)."""
    if _use_nacl():
        return True
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401

        return True
    except ImportError:
        return False


def _require_backend() -> str:
    if _use_nacl():
        return "nacl"
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401

        return "cryptography"
    except ImportError:
        raise RuntimeError("Ni PyNaCl ni 'cryptography' installés : pip install -r requirements.txt (pynacl).")


def generate_keypair() -> tuple[str, str]:
    """Nouvelle paire Ed25519. Retourne (public_b64, secret_b64), base64 standard."""
    backend = _require_backend()
    if backend == "nacl":
        # PyNaCl ne manipule que le seed (32 o.) : le secret 64 o. exposé
        # reste au format libsodium (seed || pubkey) comme partout ailleurs.
        from nacl.signing import SigningKey

        sk = SigningKey.generate()
        seed, pub = sk.encode(), sk.verify_key.encode()
        return (
            base64.b64encode(pub).decode(),
            base64.b64encode(seed + pub).decode(),
        )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

    sk = Ed25519PrivateKey.generate()
    seed = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (base64.b64encode(pub).decode(), base64.b64encode(seed + pub).decode())


def _b64_strict(value: str) -> bytes:
    return base64.b64decode(value.encode(), validate=True)


def sign(bundle: Mapping[str, Any], secret_key_b64: str) -> str:
    """Signe les octets canoniques. Retourne la signature base64.

    Lève ValueError si la clé est invalide, RuntimeError sans backend crypto.
    """
    try:
        secret = _b64_strict(secret_key_b64)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("clé secrète base64 invalide") from exc
    if len(secret) != SECRET_KEY_BYTES:
        raise ValueError("clé secrète Ed25519 invalide (64 octets attendus)")
    message = canonical_bytes(bundle)
    if _require_backend() == "nacl":
        from nacl.signing import SigningKey

        return base64.b64encode(SigningKey(secret[:32]).sign(message).signature).decode()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(secret[:32]).sign(message)).decode()


def sign_bundle(bundle: Mapping[str, Any], secret_key_b64: str) -> dict[str, Any]:
    """Copie signée : pose `node_pubkey` (dérivée), (re)signe, pose `signature`."""
    try:
        secret = _b64_strict(secret_key_b64)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("clé secrète base64 invalide") from exc
    if len(secret) != SECRET_KEY_BYTES:
        raise ValueError("clé secrète Ed25519 invalide (64 octets attendus)")
    if _require_backend() == "nacl":
        from nacl.signing import SigningKey

        pub = SigningKey(secret[:32]).verify_key.encode()
    else:
        pub = secret[32:]  # format libsodium : seed || pubkey
    out = {k: v for k, v in bundle.items() if k != "signature"}
    out["node_pubkey"] = base64.b64encode(pub).decode()
    out["signature"] = sign(out, secret_key_b64)
    return out


def verify(bundle: Mapping[str, Any], public_key_b64: str | None = None) -> bool:
    """Vérifie la signature. Clé explicite prioritaire, sinon `node_pubkey`.

    Ne lève jamais sur un bundle adverse (échec fermé → False) ; lève
    RuntimeError uniquement si aucun backend crypto n'est installé — les
    appelants serveur doivent tester `is_available()` au démarrage.
    """
    _require_backend()
    try:
        key_b64 = public_key_b64 if public_key_b64 is not None else bundle.get("node_pubkey")
        sig_b64 = bundle.get("signature")
        if not isinstance(key_b64, str) or not key_b64 or not isinstance(sig_b64, str) or not sig_b64:
            return False
        public = _b64_strict(key_b64)
        signature = _b64_strict(sig_b64)
        if len(public) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
            return False
        message = canonical_bytes(bundle)
    except (binascii.Error, ValueError, TypeError, UnicodeError):
        return False
    try:
        if _use_nacl():
            from nacl.signing import VerifyKey

            VerifyKey(public).verify(message, signature)
        else:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            Ed25519PublicKey.from_public_bytes(public).verify(signature, message)
    except Exception:
        return False
    return True
