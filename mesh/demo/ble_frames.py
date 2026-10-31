"""Référence du protocole de trames BLE (V3, transport de secours).

Même format exact que BleFrame.kt (miroir testé ici, faute de SDK Android).
Trame : magic(2)=WS | ver(1)=1 | tag(4)=sha256(bundle_id)[:4] |
         index(2 BE) | total(2 BE) | payload (mtu-3-11 octets max).

Le tag groupe les trames en vol ; l'identité/audit viennent du JSON
(bundle_id + checksum vérifiés après réassemblage).
"""

from __future__ import annotations

import hashlib
import struct
import time

SERVICE_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5"
TX_CHAR_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d6"
RX_CHAR_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d7"
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

MAGIC = b"WS"
VERSION = 1
HEADER_LEN = 11
PARTIAL_TTL_S = 60.0


def bundle_tag(bundle_id: str) -> bytes:
    return hashlib.sha256(bundle_id.encode("utf-8")).digest()[:4]


def encode_frames(bundle: bytes, bundle_id: str, mtu: int = 512) -> list[bytes]:
    if mtu < 16:
        raise ValueError("MTU trop petit pour l'en-tête BLE")
    payload_size = mtu - 3 - HEADER_LEN  # 3 octets d'overhead ATT
    tag = bundle_tag(bundle_id)
    chunks = [bundle[i:i + payload_size] for i in range(0, max(len(bundle), 1), payload_size)]
    total = len(chunks)
    if total > 0xFFFF:
        raise ValueError("Bundle trop gros pour le transport BLE")
    frames = []
    for index, chunk in enumerate(chunks):
        frames.append(MAGIC + bytes([VERSION]) + tag + struct.pack(">HH", index, total) + chunk)
    return frames


class Reassembler:
    """Assemble les trames par tag. Retourne le bundle complet ou None."""

    def __init__(self) -> None:
        self._partials: dict[bytes, dict] = {}

    def feed(self, frame: bytes, now: float | None = None) -> bytes | None:
        now = time.monotonic() if now is None else now
        for tag in [t for t, p in self._partials.items() if now - p["seen"] > PARTIAL_TTL_S]:
            del self._partials[tag]
        if len(frame) < HEADER_LEN or frame[0:2] != MAGIC or frame[2] != VERSION:
            return None
        tag = frame[3:7]
        index, total = struct.unpack(">HH", frame[7:11])
        if total == 0 or total > 0xFFFF or index >= total:
            return None
        part = self._partials.setdefault(tag, {"chunks": {}, "total": total, "seen": now})
        if part["total"] != total:
            return None  # tag réutilisé avec un total différent : on ignore
        part["chunks"][index] = frame[11:]
        part["seen"] = now
        if len(part["chunks"]) == total:
            del self._partials[tag]
            return b"".join(part["chunks"][i] for i in range(total))
        return None
