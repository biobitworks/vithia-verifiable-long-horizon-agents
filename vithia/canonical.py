from __future__ import annotations
import hashlib
import json
from typing import Any

def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical_sha256(value: Any) -> str:
    return sha256_hex(canonical_json_bytes(value))
