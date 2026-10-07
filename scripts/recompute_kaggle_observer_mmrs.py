#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from vithia.canonical import canonical_sha256
from vithia.fco import make_fco, fco_digest, validate_fco
from vithia.integrity import MMRAccumulator

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "runtime/kaggle_longrun/shared"
LEDGER = SHARED / "PARALLEL_OBSERVATION_LEDGER.jsonl"
OUT = SHARED / "observer_mmr"
OUT.mkdir(parents=True, exist_ok=True)

GENESIS = json.loads((SHARED / "PARALLEL_RUN_GENESIS.json").read_text())
rows = [json.loads(x) for x in LEDGER.read_text().splitlines() if x.strip()]

def make_route_fco(lane: str, row: dict, idx: int) -> dict:
    key = "vita" if lane == "VITA" else "vcc"
    status_key = f"{key}_status"
    start_key = f"{key}_start_utc"
    elapsed_key = f"{key}_elapsed_seconds"
    payload = {
        "schema": "kaggle_observer_route_state.v1",
        "route": f"{lane}_KAGGLE_ROUTE",
        "event_index": idx,
        "observed_at_utc": row.get("observed_at_utc"),
        "kernel": GENESIS["lanes"][key]["kernel"],
        "kernel_version": GENESIS["lanes"][key]["kernel_version"],
        "start_utc": row.get(start_key, GENESIS["lanes"][key]["kaggle_last_run_time_utc"]),
        "status": row.get(status_key, "UNKNOWN"),
        "elapsed_seconds": row.get(elapsed_key, "UNKNOWN"),
        "continuous_liveness": row.get("continuous_liveness", "UNKNOWN"),
        "source_observation_sha256": canonical_sha256(row),
        "observation_origin": "magicPRObox_Kaggle_CLI",
        "claim_boundary": "Discrete external observation only; does not prove continuous liveness between observations."
    }
    return make_fco("KaggleRouteObservationFCO", payload)

def make_interaction_fco(row: dict, idx: int) -> dict:
    payload = {
        "schema": "parallel_kaggle_interaction_observation.v1",
        "event_index": idx,
        "observed_at_utc": row.get("observed_at_utc"),
        "vita_status": row.get("vita_status", "UNKNOWN"),
        "vcc_status": row.get("vcc_status", "UNKNOWN"),
        "parallel_execution_observed": row.get("parallel_execution_observed", "UNKNOWN"),
        "continuous_liveness": row.get("continuous_liveness", "UNKNOWN"),
        "hour_1_survival": row.get("hour_1_survival", "NOT_TESTED"),
        "future_milestones": row.get("future_milestones", "NOT_TESTED"),
        "source_observation_sha256": canonical_sha256(row),
        "claim_boundary": "Joint observer state only; no project canonical admission and no scientific claim."
    }
    return make_fco("KaggleParallelInteractionFCO", payload)

def build(name: str, fcos: list[dict]) -> dict:
    mmr = MMRAccumulator()
    for i, fco in enumerate(fcos):
        if not validate_fco(fco):
            raise RuntimeError(f"invalid FCO at {name}:{i}")
        mmr.append(i, fco_digest(fco), f"{name}:state:{i:04d}:{fco_digest(fco)[:12]}")
    rec = mmr.verification_receipt()
    rec.update({
        "lineage": name,
        "source_ledger": str(LEDGER.relative_to(ROOT)),
        "source_ledger_sha256": __import__("hashlib").sha256(LEDGER.read_bytes()).hexdigest(),
        "project_canonical_mmr_append": False,
        "signature_state": "NOT_SIGNED",
        "claim_boundary": "Ordered identity/custody commitment only; not truth, causality, scientific validity, or project admission."
    })
    return rec

vita = [make_route_fco("VITA", r, i) for i, r in enumerate(rows)]
vcc = [make_route_fco("VCC", r, i) for i, r in enumerate(rows)]
interaction = [make_interaction_fco(r, i) for i, r in enumerate(rows)]

receipts = {}
all_fcos = []
edges = []
for name, fcos in [("VITA_OBSERVER_ROUTE_MMR", vita), ("VCC_OBSERVER_ROUTE_MMR", vcc), ("PARALLEL_INTERACTION_MMR", interaction)]:
    p = OUT / f"{name}_FCOS.jsonl"
    p.write_text("".join(json.dumps(x, sort_keys=True, separators=(",",":")) + "\n" for x in fcos))
    rec = build(name, fcos)
    receipts[name] = rec
    (OUT / f"{name}_RECEIPT.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    all_fcos.extend(fcos)
    for i in range(1, len(fcos)):
        edges.append({"from": fcos[i]["object_id"], "type": "SUCCESSOR_OF", "to": fcos[i-1]["object_id"]})

for i in range(len(interaction)):
    edges.append({"from": interaction[i]["object_id"], "type": "OBSERVES", "to": vita[i]["object_id"]})
    edges.append({"from": interaction[i]["object_id"], "type": "OBSERVES", "to": vcc[i]["object_id"]})

mmr_state_fcos = []
for name, rec in receipts.items():
    f = make_fco("MMRStateFCO", {
        "schema": "fco_fcg.mmr_state.v1",
        "lineage": name,
        "algorithm_id": rec["algorithm_id"],
        "leaf_count": rec["leaf_count"],
        "peaks": rec["peaks"],
        "root_sha256": rec["root_sha256"],
        "verification_passed": rec["verification_passed"],
        "project_canonical_mmr_append": False,
        "signature_state": "NOT_SIGNED",
        "claim_boundary": rec["claim_boundary"]
    })
    mmr_state_fcos.append(f)
    all_fcos.append(f)

for lane_fco, mmr_fco in [(vita[-1], mmr_state_fcos[0]), (vcc[-1], mmr_state_fcos[1]), (interaction[-1], mmr_state_fcos[2])]:
    edges.append({"from": mmr_fco["object_id"], "type": "COMMITS_LINEAGE_ENDING_AT", "to": lane_fco["object_id"]})

(OUT / "OBSERVER_FCG_FCOS.jsonl").write_text("".join(json.dumps(x, sort_keys=True, separators=(",",":")) + "\n" for x in all_fcos))
(OUT / "OBSERVER_FCG_EDGES.jsonl").write_text("".join(json.dumps(x, sort_keys=True, separators=(",",":")) + "\n" for x in edges))

summary = {
    "schema": "kaggle_fractal_commitment_state.v1",
    "observer_ledger_events": len(rows),
    "vita_run_local_commitment": "LANE_MERKLE_IMPLEMENTED_IN_RUNNING_SOURCE; ROOT_NOT_EXTERNALLY_OBSERVED; RUN_MMR_NOT_IMPLEMENTED",
    "vcc_run_local_commitment": "LANE_MERKLE_IMPLEMENTED_IN_RUNNING_SOURCE; ROOT_NOT_EXTERNALLY_OBSERVED; RUN_MMR_NOT_IMPLEMENTED",
    "vita_observer_route_mmr": json.loads((OUT / "VITA_OBSERVER_ROUTE_MMR_RECEIPT.json").read_text()),
    "vcc_observer_route_mmr": json.loads((OUT / "VCC_OBSERVER_ROUTE_MMR_RECEIPT.json").read_text()),
    "parallel_interaction_mmr": json.loads((OUT / "PARALLEL_INTERACTION_MMR_RECEIPT.json").read_text()),
    "project_canonical_mmr_append": False,
    "federation_mmr_append": False,
    "signature_state": "NOT_SIGNED"
}
(OUT / "FRACTAL_COMMITMENT_STATE.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(json.dumps({
    "events": len(rows),
    "vita_route_root": summary["vita_observer_route_mmr"]["root_sha256"],
    "vcc_route_root": summary["vcc_observer_route_mmr"]["root_sha256"],
    "interaction_root": summary["parallel_interaction_mmr"]["root_sha256"]
}, sort_keys=True))
