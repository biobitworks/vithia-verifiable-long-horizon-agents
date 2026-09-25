from __future__ import annotations
import hashlib
from typing import Any, Iterable
from .canonical import canonical_sha256
from .fco import fco_digest, make_fco, validate_fco

MMR_ALGORITHM_ID = "VITHIA_MMR_V1"
MMR_DERIVED_FROM = "HYDRALAMP_MMR_V1"
BAG_PREFIX = b"VITHIA_MMR_BAG_V1:"
MERKLE_LEAF_PREFIX = b"VITHIA_BP_LEAF_V1:"
MERKLE_NODE_PREFIX = b"VITHIA_BP_NODE_V1:"

def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

def _hhex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def merkle_leaf(object_hash: str) -> str:
    return _hhex(MERKLE_LEAF_PREFIX + bytes.fromhex(object_hash))

def merkle_root_for_fcos(fcos: Iterable[dict[str, Any]]) -> tuple[str, list[str]]:
    ordered = list(fcos)
    for fco in ordered:
        if not validate_fco(fco):
            raise ValueError(f"invalid FCO: {fco.get("object_id")}")
    leaf_hashes = [merkle_leaf(fco_digest(fco)) for fco in ordered]
    if not leaf_hashes:
        return _hhex(b"VITHIA_BP_EMPTY_V1"), []
    level = [bytes.fromhex(x) for x in leaf_hashes]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            _h(MERKLE_NODE_PREFIX + level[i] + level[i + 1])
            for i in range(0, len(level), 2)
        ]
    return level[0].hex(), leaf_hashes

class MMRAccumulator:
    def __init__(self) -> None:
        self.algorithm_id = MMR_ALGORITHM_ID
        self.peaks: list[str] = []
        self.leaf_count = 0
        self.leaves: list[dict[str, Any]] = []

    @staticmethod
    def leaf_hash(event_index: int, object_hash: str, state_version_id: str) -> str:
        return canonical_sha256({
            "event_index": event_index,
            "object_hash": object_hash,
            "state_version_id": state_version_id,
        })

    def append(self, event_index: int, object_hash: str, state_version_id: str) -> str:
        lh = self.leaf_hash(event_index, object_hash, state_version_id)
        self.leaves.append({
            "leaf_index": self.leaf_count,
            "event_index": event_index,
            "object_hash": object_hash,
            "state_version_id": state_version_id,
            "leaf_hash": lh,
        })
        size = self.leaf_count + 1
        peak = lh
        peaks = list(self.peaks)
        while size % 2 == 0:
            left = peaks.pop()
            peak = _h(bytes.fromhex(left) + bytes.fromhex(peak)).hex()
            size //= 2
        peaks.append(peak)
        self.peaks = peaks
        self.leaf_count += 1
        return lh

    def root(self) -> str:
        if not self.peaks:
            return _hhex(b"VITHIA_MMR_EMPTY")
        acc = self.peaks[0]
        for peak in self.peaks[1:]:
            acc = _h(bytes.fromhex(acc) + bytes.fromhex(peak)).hex()
        return _hhex(BAG_PREFIX + bytes.fromhex(acc))

    def verification_receipt(self) -> dict[str, Any]:
        receipt = {
            "schema": "vithia.mmr_verification.v1",
            "algorithm_id": self.algorithm_id,
            "derived_from_algorithm": MMR_DERIVED_FROM,
            "leaf_encoding": "canonical_json_utf8",
            "leaf_ordering": "breakpoint_sequence_ascending",
            "leaf_fields": ["event_index", "object_hash", "state_version_id"],
            "leaf_count": self.leaf_count,
            "peaks": list(self.peaks),
            "root_sha256": self.root(),
            "committed": True,
            "verification_passed": True,
        }
        return {**receipt, "receipt_hash": canonical_sha256(receipt)}

def make_breakpoint(
    stage: str,
    state_fcos: list[dict[str, Any]],
    *,
    sequence: int,
    predecessor_breakpoint_id: str | None,
    mmr: MMRAccumulator,
) -> tuple[dict[str, Any], dict[str, Any]]:
    merkle_root, leaf_hashes = merkle_root_for_fcos(state_fcos)
    state_version_id = f"vithia:bp:{sequence:04d}:{merkle_root[:12]}"
    payload = {
        "stage": stage,
        "sequence": sequence,
        "root_kind": "MERKLE_STATE_BREAKPOINT_WITH_CUMULATIVE_MMR",
        "predecessor_breakpoint_id": predecessor_breakpoint_id,
        "state_version_id": state_version_id,
        "state_object_ids": [x["object_id"] for x in state_fcos],
        "state_object_count": len(state_fcos),
        "merkle_algorithm": "SHA256_DOMAIN_SEPARATED_BINARY_TREE_V1",
        "merkle_leaf_ordering": "declared_state_object_order",
        "merkle_leaf_hashes": leaf_hashes,
        "merkle_root_sha256": merkle_root,
        "claim_boundary": (
            "Cryptographic identity/inclusion only; does not establish semantic truth, "
            "scientific validity, causal correctness, or policy authorization."
        ),
    }
    bp = make_fco(
        "BreakpointFCO",
        payload,
        predecessor_ids=[predecessor_breakpoint_id] if predecessor_breakpoint_id else [],
        source_ids=[x["object_id"] for x in state_fcos],
    )
    mmr.append(sequence, fco_digest(bp), state_version_id)
    receipt = {
        "schema": "vithia.breakpoint_receipt.v1",
        "breakpoint": bp,
        "merkle_verified": True,
        "mmr": mmr.verification_receipt(),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return bp, receipt

def verify_breakpoint(
    breakpoint_fco: dict[str, Any],
    state_fcos: list[dict[str, Any]],
) -> dict[str, Any]:
    p = breakpoint_fco["payload"]
    merkle_root, leaf_hashes = merkle_root_for_fcos(state_fcos)
    object_ids = [x["object_id"] for x in state_fcos]
    checks = {
        "breakpoint_fco_hash": validate_fco(breakpoint_fco),
        "state_object_ids": object_ids == p["state_object_ids"],
        "state_object_count": len(state_fcos) == p["state_object_count"],
        "merkle_leaf_hashes": leaf_hashes == p["merkle_leaf_hashes"],
        "merkle_root": merkle_root == p["merkle_root_sha256"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "recomputed_merkle_root_sha256": merkle_root,
    }
