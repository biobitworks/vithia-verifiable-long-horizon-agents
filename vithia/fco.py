from __future__ import annotations
from typing import Any, Iterable
from .canonical import canonical_sha256

FCO_SCHEMA = "vithia.fco.v1"

def make_fco(
    object_type: str,
    payload: dict[str, Any],
    *,
    predecessor_ids: Iterable[str] = (),
    source_ids: Iterable[str] = (),
) -> dict[str, Any]:
    body = {
        "schema": FCO_SCHEMA,
        "object_type": object_type,
        "predecessor_ids": list(predecessor_ids),
        "source_ids": list(source_ids),
        "payload": payload,
    }
    digest = canonical_sha256(body)
    return {"object_id": f"fco:{digest}", **body}

def fco_digest(fco: dict[str, Any]) -> str:
    object_id = fco.get("object_id", "")
    if not object_id.startswith("fco:"):
        raise ValueError("missing fco: object_id")
    return object_id.split(":", 1)[1]

def validate_fco(fco: dict[str, Any]) -> bool:
    body = {k: v for k, v in fco.items() if k != "object_id"}
    return fco.get("object_id") == f"fco:{canonical_sha256(body)}"
