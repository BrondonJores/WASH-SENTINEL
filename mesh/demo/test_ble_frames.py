"""Tests du protocole de trames BLE (référence Python de BleFrame.kt)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ble_frames
from ble_frames import Reassembler, bundle_tag, encode_frames


def test_tag_deterministe():
    assert bundle_tag("abc") == bundle_tag("abc")
    assert len(bundle_tag("abc")) == 4
    assert bundle_tag("abc") != bundle_tag("abd")


def test_roundtrip_mtu_defaut():
    payload = b'{"bundle_id":"x",' + b"y" * 2000 + b"}"
    frames = encode_frames(payload, "bundle-1")
    assert len(frames) > 1
    asm = Reassembler()
    out = None
    for frame in frames:
        out = asm.feed(frame) or out
    assert out == payload


def test_roundtrip_mtu_minimal_23():
    payload = b"z" * 100
    frames = encode_frames(payload, "bundle-2", mtu=23)
    assert all(len(f) <= 20 for f in frames)  # 23 - 3 ATT
    asm = Reassembler()
    out = None
    for frame in frames:
        out = asm.feed(frame) or out
    assert out == payload


def test_desordre_et_melange_de_tags():
    a = encode_frames(b"A" * 500, "bundle-A", mtu=100)
    b = encode_frames(b"B" * 500, "bundle-B", mtu=100)
    asm = Reassembler()
    results = []
    for frame in [x for pair in zip(a, b) for x in pair][::-1]:
        done = asm.feed(frame)
        if done is not None:
            results.append(done)
    assert sorted(results) == [b"A" * 500, b"B" * 500]


def test_trames_corrompues_ignorees():
    asm = Reassembler()
    assert asm.feed(b"") is None
    assert asm.feed(b"XX\x01\x00\x00\x00\x00\x00\x00\x00") is None  # mauvais magic
    assert asm.feed(b"WS\x02\x00\x00\x00\x00\x00\x00\x01") is None  # mauvaise version
    frames = encode_frames(b"hello", "bundle-3")
    assert len(frames) == 1
    assert asm.feed(frames[0]) == b"hello"


def test_incomplet_puis_complet():
    frames = encode_frames(b"Q" * 300, "bundle-4", mtu=100)
    asm = Reassembler()
    assert asm.feed(frames[0]) is None
    out = None
    for frame in frames[1:]:
        out = asm.feed(frame) or out
    assert out == b"Q" * 300


def test_expiration_des_partiels():
    frames = encode_frames(b"W" * 300, "bundle-5", mtu=100)
    asm = Reassembler()
    assert asm.feed(frames[0], now=0.0) is None
    # Après TTL, l'ancien partiel est purgé : la suite seule ne suffit plus.
    assert asm.feed(frames[1], now=ble_frames.PARTIAL_TTL_S + 1) is None
