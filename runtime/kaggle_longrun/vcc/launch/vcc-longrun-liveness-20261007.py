#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import platform
import random
import signal
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

CONFIG = json.loads(r"""{"checkpoint_interval_seconds":300,"claim_ceiling":"VCC_INFRASTRUCTURE_RUNTIME_QUALIFICATION_ONLY;NO_SCORE_BEARING_EXPERIMENT;NO_SUBMISSION","github_check_interval_seconds":3600,"github_control_branch":"runtime/kaggle-vcc-longrun-liveness-20261007","github_control_path":"runtime/kaggle_longrun/vcc/CONTROL.json","github_repo":"biobitworks/vithia-verifiable-long-horizon-agents","kernel_slug":"biobitworks/vcc-longrun-liveness-20261007","kernel_title":"VCC Longrun Liveness 20261007","lane":"VCC_LONGRUN_LIVENESS","predecessor_state":"VCC::READY_NOT_AUTHORIZED;SAFE_TO_START_LONG_RUNS=NO","project_id":"FCO-FCG-KAGGLE-LIVENESS-20261007","run_id":"VCC-KAGGLE-LIVENESS-20261007-001","scientific_state":"VCC_SCIENTIFIC_EXECUTION=NOT_EXECUTED;VCC_INFRASTRUCTURE_LIVENESS_TEST=EXECUTED_IF_RUNNING;SAFE_TO_START_LONG_RUNS=NO","seed":20261007,"source_descriptor":{"hidden_challenge_outcomes_used":false,"kind":"SYNTHETIC_REFERENCE","purpose":"VCC-shaped runtime/liveness surrogate only","shape":{"batch":64,"d_model":64,"sequence_length":16,"vocab":4096}},"source_input_root":"75aea1889a06a0adfd2e55c8f51c7217c2905c3c732cdefa1a1a02b4e55e69bb","step_sleep_seconds":0.05,"target_wall_time_seconds":28800,"workload_kind":"VCC_SYNTHETIC_SEQUENCE_SHAPED"}""")

OUT = Path("/kaggle/working")
CP_DIR = OUT / "checkpoints"
HOUR_DIR = OUT / "hourly"
RUN_GENESIS = OUT / "RUN_GENESIS.json"
CAPABILITY_RECEIPT = OUT / "CAPABILITY_RECEIPT.json"
CHECKPOINT_MANIFEST = OUT / "CHECKPOINT_MANIFEST.jsonl"
CONTROL_OBSERVATIONS = OUT / "GITHUB_CONTROL_OBSERVATIONS.jsonl"
STATUS_WRITES = OUT / "GITHUB_STATUS_WRITES.jsonl"
ERROR_LEDGER = OUT / "ERROR_LEDGER.jsonl"
HOURLY_BREAKPOINTS = OUT / "HOURLY_BREAKPOINTS.jsonl"
TERMINAL_RESULT = OUT / "TERMINAL_RESULT.json"
ARTIFACT_MANIFEST = OUT / "ARTIFACT_MANIFEST.json"
MERKLE_CONSTRUCTION = OUT / "MERKLE_CONSTRUCTION.json"
VERIFY_RECEIPT = OUT / "VERIFY_RECEIPT.json"
FINAL_HANDOFF = OUT / "FINAL_HANDOFF.md"
LAUNCH_BP = OUT / "LAUNCH_TURN_BREAKPOINT.json"
POST30 = OUT / "POST30M_BREAKPOINT.json"

TARGET_SECONDS = int(CONFIG["target_wall_time_seconds"])
CHECKPOINT_INTERVAL = int(CONFIG["checkpoint_interval_seconds"])
GITHUB_INTERVAL = int(CONFIG["github_check_interval_seconds"])

STOP_REQUESTED = False
STOP_SIGNAL = None

def _signal(signum, frame):
    global STOP_REQUESTED, STOP_SIGNAL
    STOP_REQUESTED = True
    STOP_SIGNAL = signal.Signals(signum).name

signal.signal(signal.SIGTERM, _signal)
signal.signal(signal.SIGINT, _signal)

def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def canon(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()

def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(canon(obj))
    os.replace(tmp, path)

def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as fh:
        fh.write(canon(obj))
        fh.flush()
        os.fsync(fh.fileno())

def obj_root(obj: Any) -> str:
    bio = io.BytesIO()
    torch.save(obj, bio)
    return sha_bytes(bio.getvalue())

def model_root(model: nn.Module) -> str:
    return obj_root({k: v.detach().cpu() for k, v in model.state_dict().items()})

def accelerator_state() -> dict:
    out = {
        "cuda_available": torch.cuda.is_available(),
        "device_count": torch.cuda.device_count(),
    }
    if torch.cuda.is_available():
        out.update({
            "device": torch.cuda.current_device(),
            "name": torch.cuda.get_device_name(torch.cuda.current_device()),
            "memory_allocated": int(torch.cuda.memory_allocated()),
            "memory_reserved": int(torch.cuda.memory_reserved()),
        })
    return out

def runtime_identity() -> dict:
    safe_env = {}
    for key in ["KAGGLE_KERNEL_RUN_TYPE", "KAGGLE_KERNEL_INTEGRATIONS", "KAGGLE_KERNEL_ID", "KAGGLE_USER_NAME"]:
        if key in os.environ:
            safe_env[key] = os.environ[key]
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "safe_kaggle_env": safe_env,
        "accelerator": accelerator_state(),
    }

def error_record(operation: str, exc: Exception, recoverable: bool) -> dict:
    rec = {
        "schema": "kaggle_longrun_error.v1",
        "timestamp_utc": utc_now(),
        "error_class": type(exc).__name__,
        "sanitized_message": str(exc)[:1000],
        "operation": operation,
        "recoverable": bool(recoverable),
    }
    append_jsonl(ERROR_LEDGER, rec)
    return rec

def fetch_control() -> dict:
    repo = CONFIG["github_repo"]
    branch = CONFIG["github_control_branch"]
    path = CONFIG["github_control_path"]
    enc_ref = urllib.parse.quote(branch, safe="")
    api = f"https://api.github.com/repos/{repo}/contents/{path}?ref={urllib.parse.quote(branch, safe='')}&_={time.time_ns()}"
    commit_api = f"https://api.github.com/repos/{repo}/commits/{enc_ref}?_={time.time_ns()}"
    req = urllib.request.Request(api, headers={"User-Agent": "fco-fcg-kaggle-longrun/1.0", "Accept": "application/vnd.github+json", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        wrapper = json.loads(resp.read())
    raw = base64.b64decode(wrapper["content"])
    doc = json.loads(raw)
    if doc.get("transport_only_not_canonical_state") is not True:
        raise RuntimeError("CONTROL_BOUNDARY_MISSING")
    if doc.get("run_id") != CONFIG["run_id"]:
        raise RuntimeError("CONTROL_RUN_ID_MISMATCH")
    req2 = urllib.request.Request(commit_api, headers={"User-Agent": "fco-fcg-kaggle-longrun/1.0", "Accept": "application/vnd.github+json", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req2, timeout=20) as resp:
        commit_doc = json.loads(resp.read())
    return {
        "fetch_state": "ACCESSIBLE",
        "document": doc,
        "content_sha256": sha_bytes(raw),
        "github_blob_sha": wrapper.get("sha"),
        "github_commit": commit_doc.get("sha"),
        "observed_at_utc": utc_now(),
    }

def observe_control() -> dict:
    try:
        obs = fetch_control()
        action = str(obs["document"].get("action", "CONTINUE")).upper()
        if action not in {"CONTINUE", "PAUSE", "STOP", "CHECKPOINT_NOW"}:
            obs["control_action"] = "UNKNOWN_CONTROL_ACTION"
            obs["effective_action"] = "CONTINUE"
        else:
            obs["control_action"] = action
            obs["effective_action"] = action
        obs["control_revision"] = obs["document"].get("control_revision")
        obs["action_seq"] = obs["document"].get("action_seq")
        append_jsonl(CONTROL_OBSERVATIONS, obs)
        return obs
    except Exception as exc:
        rec = error_record("GITHUB_CONTROL_READ", exc, True)
        obs = {
            "fetch_state": "INACCESSIBLE_CURRENTLY",
            "document": None,
            "content_sha256": None,
            "github_blob_sha": None,
            "github_commit": None,
            "observed_at_utc": utc_now(),
            "control_action": "NO_UPDATE",
            "effective_action": "CONTINUE",
            "control_revision": None,
            "action_seq": None,
            "error": rec,
        }
        append_jsonl(CONTROL_OBSERVATIONS, obs)
        return obs

def merkle_root_from_hourly() -> tuple[str, list[str]]:
    paths = sorted(HOUR_DIR.glob("HOUR-*.json"))
    leaf_hashes = []
    for p in paths:
        leaf = hashlib.sha256(b"KAGGLE-LONGRUN-LEAF-v1\x00" + p.read_bytes()).hexdigest()
        leaf_hashes.append(leaf)
    if not leaf_hashes:
        return hashlib.sha256(b"KAGGLE-LONGRUN-EMPTY-v1").hexdigest(), []
    level = list(leaf_hashes)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        nxt = []
        for i in range(0, len(level), 2):
            nxt.append(hashlib.sha256(b"KAGGLE-LONGRUN-NODE-v1\x00" + bytes.fromhex(level[i]) + bytes.fromhex(level[i+1])).hexdigest())
        level = nxt
    return level[0], leaf_hashes

class VitaSynthetic(nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = nn.Embedding(22, 32)
        self.n1 = nn.Linear(8, 32)
        self.h = nn.Linear(64, 96)
        self.o = nn.Linear(96, 1)
    def forward(self, ids, numeric):
        x = self.emb(ids).mean(dim=1)
        n = F.gelu(self.n1(numeric))
        return self.o(F.gelu(self.h(torch.cat([x, n], dim=1)))).squeeze(-1)

class VCCSynthetic(nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = nn.Embedding(4096, 64)
        enc = nn.TransformerEncoderLayer(d_model=64, nhead=4, dim_feedforward=128, dropout=0.0, batch_first=True)
        self.tr = nn.TransformerEncoder(enc, num_layers=1)
        self.o = nn.Linear(64, 32)
    def forward(self, ids):
        h = self.tr(self.emb(ids))
        return self.o(h[:, -1, :])

def build_workload(device):
    seed = int(CONFIG["seed"])
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    if CONFIG["workload_kind"] == "VITA_SYNTHETIC_EXP168_SHAPED":
        model = VitaSynthetic().to(device)
    else:
        model = VCCSynthetic().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda _: 1.0)
    return model, opt, sched

def training_step(model, opt, sched, device, step: int) -> float:
    opt.zero_grad(set_to_none=True)
    if CONFIG["workload_kind"] == "VITA_SYNTHETIC_EXP168_SHAPED":
        ids = torch.randint(0, 22, (256, 60), device=device)
        numeric = torch.rand((256, 8), device=device)
        target = (ids.float().mean(dim=1) / 21.0 + numeric.mean(dim=1)) * 0.5
        pred = model(ids, numeric)
        loss = F.mse_loss(pred, target)
    else:
        ids = torch.randint(0, 4096, (64, 16), device=device)
        target = torch.remainder(ids[:, :32] if ids.shape[1] >= 32 else ids.repeat(1, 2)[:, :32], 32).float()
        logits = model(ids)
        loss = F.mse_loss(logits, target / 31.0)
    if not torch.isfinite(loss):
        raise FloatingPointError("NONFINITE_COMPUTE_STATE")
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step()
    sched.step()
    return float(loss.detach().cpu())

def checkpoint(reason: str, step: int, model, opt, sched, start_monotonic: float) -> dict:
    CP_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "schema": "kaggle_longrun_checkpoint.v1",
        "lane": CONFIG["lane"],
        "run_id": CONFIG["run_id"],
        "reason": reason,
        "step": step,
        "wall_seconds": time.monotonic() - start_monotonic,
        "model": model.state_dict(),
        "optimizer": opt.state_dict(),
        "scheduler": sched.state_dict(),
        "rng_cpu": torch.get_rng_state(),
        "rng_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "config_root": sha_bytes(canon(CONFIG)),
        "source_input_root": CONFIG["source_input_root"],
    }
    p = CP_DIR / f"checkpoint-{step:09d}-{reason}.pt"
    torch.save(state, p)
    os.sync()
    rec = {
        "schema": "kaggle_longrun_checkpoint_receipt.v1",
        "created_at_utc": utc_now(),
        "run_id": CONFIG["run_id"],
        "lane": CONFIG["lane"],
        "reason": reason,
        "step": step,
        "wall_seconds": state["wall_seconds"],
        "checkpoint_file": p.name,
        "checkpoint_sha256": sha_file(p),
        "model_state_root": model_root(model),
        "optimizer_state_root": obj_root(opt.state_dict()),
        "scheduler_state_root": obj_root(sched.state_dict()),
        "rng_root": obj_root({"cpu": torch.get_rng_state(), "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []}),
        "data_cursor_root": sha_bytes(canon({"synthetic_step": step, "seed": CONFIG["seed"]})),
        "configuration_root": sha_bytes(canon(CONFIG)),
        "runtime_health": accelerator_state(),
    }
    append_jsonl(CHECKPOINT_MANIFEST, rec)
    return rec

def verify_checkpoint(rec: dict) -> dict:
    p = CP_DIR / rec["checkpoint_file"]
    loaded = torch.load(p, map_location="cpu", weights_only=False)
    return {
        "checkpoint_exists": p.exists(),
        "checkpoint_sha256_match": sha_file(p) == rec["checkpoint_sha256"],
        "step_match": int(loaded["step"]) == int(rec["step"]),
        "run_id_match": loaded["run_id"] == CONFIG["run_id"],
        "all_pass": p.exists() and sha_file(p) == rec["checkpoint_sha256"] and int(loaded["step"]) == int(rec["step"]) and loaded["run_id"] == CONFIG["run_id"],
    }

def write_hourly(hour_index: int, wall: float, step: int, cp: dict, control: dict, errors_since_prev: list[dict], state: str) -> dict:
    obs = {
        "schema": "kaggle_longrun_hourly_observation.v1",
        "project": CONFIG["project_id"],
        "lane": CONFIG["lane"],
        "run_id": CONFIG["run_id"],
        "hour_index": hour_index,
        "observed_wall_seconds": wall,
        "state": state,
        "step": step,
        "latest_checkpoint_sha256": cp["checkpoint_sha256"],
        "latest_checkpoint_step": cp["step"],
        "latest_checkpoint_roots": {
            "model": cp["model_state_root"],
            "optimizer": cp["optimizer_state_root"],
            "scheduler": cp["scheduler_state_root"],
            "rng": cp["rng_root"],
            "data_cursor": cp["data_cursor_root"],
            "configuration": cp["configuration_root"],
        },
        "accelerator": accelerator_state(),
        "github_fetch_state": control.get("fetch_state"),
        "github_control_commit_observed": control.get("github_commit"),
        "github_control_blob_observed": control.get("github_blob_sha"),
        "github_control_content_sha256": control.get("content_sha256"),
        "control_revision": control.get("control_revision"),
        "action_seq": control.get("action_seq"),
        "github_control_action": control.get("control_action"),
        "effective_action": control.get("effective_action"),
        "github_write_result": "INACCESSIBLE_NO_AUTHORIZED_WRITE_CREDENTIAL",
        "errors_since_previous": errors_since_prev,
        "scientific_state": CONFIG["scientific_state"],
        "claim_ceiling": CONFIG["claim_ceiling"],
        "project_mmr_append": False,
        "signature_state": "NOT_SIGNED",
    }
    HOUR_DIR.mkdir(parents=True, exist_ok=True)
    p = HOUR_DIR / f"HOUR-{hour_index:03d}.json"
    atomic_json(p, obs)
    root, leaves = merkle_root_from_hourly()
    obs["lane_merkle_root_after_observation"] = root
    obs["lane_merkle_leaf_count"] = len(leaves)
    atomic_json(p, obs)
    append_jsonl(HOURLY_BREAKPOINTS, obs)
    append_jsonl(STATUS_WRITES, {
        "timestamp_utc": utc_now(),
        "hour_index": hour_index,
        "operation": "GITHUB_STATUS_WRITE",
        "authorization_result": "DENIED_NO_AUTHORIZED_WRITE_CREDENTIAL",
        "github_write_state": "INACCESSIBLE",
        "continued_compute": True,
    })
    return obs

def final_manifest() -> dict:
    files = []
    for p in sorted(OUT.rglob("*")):
        if p.is_file() and not p.name.endswith(".tmp"):
            files.append({"path": str(p.relative_to(OUT)), "size": p.stat().st_size, "sha256": sha_file(p)})
    root = sha_bytes(canon(files))
    doc = {"schema": "kaggle_longrun_artifact_manifest.v1", "created_at_utc": utc_now(), "run_id": CONFIG["run_id"], "files": files, "manifest_body_sha256": root}
    atomic_json(ARTIFACT_MANIFEST, doc)
    return doc

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    CP_DIR.mkdir(parents=True, exist_ok=True)
    HOUR_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(MERKLE_CONSTRUCTION, {
        "schema": "kaggle_longrun_merkle_construction.v1",
        "hash_algorithm": "SHA-256",
        "canonicalization": "RFC8259-compatible JSON; sort_keys=true; separators=(',',':'); UTF-8; trailing LF",
        "ordering": "ascending HOUR-NNN filename / hour_index",
        "leaf_encoding": "SHA256(b'KAGGLE-LONGRUN-LEAF-v1\\x00' || exact HOUR-NNN.json bytes)",
        "node_construction": "SHA256(b'KAGGLE-LONGRUN-NODE-v1\\x00' || left_digest_bytes || right_digest_bytes)",
        "odd_leaf_rule": "duplicate final leaf at each level",
        "empty_tree_rule": "SHA256(b'KAGGLE-LONGRUN-EMPTY-v1')",
        "scope": "lane hourly observations only; NOT project MMR",
    })
    atomic_json(CAPABILITY_RECEIPT, {
        "schema": "kaggle_longrun_capability_receipt.v1",
        "actor_id": CONFIG["kernel_slug"],
        "target_repository": CONFIG["github_repo"],
        "authorized_branch_path": {"branch": CONFIG["github_control_branch"], "path": CONFIG["github_control_path"]},
        "access_request_fco": {"requested": ["repository_read", "restricted_status_write"], "secret_material_included": False},
        "access_grant_fco": {"repository_read": "PUBLIC_ANONYMOUS_READ"},
        "access_deny_fco": {"restricted_status_write": "DENIED_NO_AUTHORIZED_WRITE_CREDENTIAL"},
        "key_use_fco": {"key_id": None, "operation": "PUBLIC_GITHUB_READ", "authorization_result": "NO_KEY_USED"},
        "github_write_state": "INACCESSIBLE",
    })
    if not torch.cuda.is_available():
        raise RuntimeError("ACCELERATOR_PREFLIGHT_FAILED_CUDA_UNAVAILABLE")
    device = torch.device("cuda:0")
    code_sha = sha_file(Path(__file__))
    initial_control = observe_control()
    expected_code = (initial_control.get("document") or {}).get("expected_code_sha256")
    if expected_code and expected_code != code_sha:
        raise RuntimeError("CODE_IDENTITY_MISMATCH")
    runtime = runtime_identity()
    genesis = {
        "schema": "RunGenesisFCO.v1",
        "created_at_utc": utc_now(),
        "project_id": CONFIG["project_id"],
        "lane_id": CONFIG["lane"],
        "run_id": CONFIG["run_id"],
        "code_sha256": code_sha,
        "code_commit": (initial_control.get("document") or {}).get("launch_source_commit", "UNKNOWN"),
        "kernel_slug": CONFIG["kernel_slug"],
        "kernel_version": "RUNTIME_VERSION_NOT_EXPOSED",
        "container_runtime_identity": runtime,
        "python_version": platform.python_version(),
        "framework_version": torch.__version__,
        "accelerator_type": accelerator_state(),
        "device_count": torch.cuda.device_count(),
        "source_input_roots": [CONFIG["source_input_root"]],
        "config_root": sha_bytes(canon(CONFIG)),
        "control_document_root": initial_control.get("content_sha256"),
        "github_target_repo_ref": {"repo": CONFIG["github_repo"], "branch": CONFIG["github_control_branch"], "path": CONFIG["github_control_path"]},
        "target_wall_time_seconds": TARGET_SECONDS,
        "checkpoint_cadence_seconds": CHECKPOINT_INTERVAL,
        "github_observation_cadence_seconds": GITHUB_INTERVAL,
        "claim_ceiling": CONFIG["claim_ceiling"],
        "scientific_state": CONFIG["scientific_state"],
        "short_lease_required": False,
        "segment_boundary_terminates_run": False,
        "control_plane_silence_terminates_run": False,
        "github_unchanged_terminates_run": False,
        "github_unreachable_terminates_run": False,
        "project_mmr_append": False,
        "signature_state": "NOT_SIGNED",
    }
    atomic_json(RUN_GENESIS, genesis)

    model, opt, sched = build_workload(device)
    started = time.monotonic()
    start_utc = utc_now()
    step = 0
    last_cp_t = started
    next_github_t = started + GITHUB_INTERVAL
    errors_since_hour = []
    last_action_seq = initial_control.get("action_seq")
    last_cp = checkpoint("genesis", step, model, opt, sched, started)
    verify0 = verify_checkpoint(last_cp)
    atomic_json(VERIFY_RECEIPT, {"schema": "kaggle_longrun_verify_receipt.v1", "created_at_utc": utc_now(), "genesis_checkpoint": verify0, "state": "PASS" if verify0["all_pass"] else "FAIL"})
    h0 = write_hourly(0, 0.0, step, last_cp, initial_control, [], "RUNNING")
    atomic_json(LAUNCH_BP, {
        "schema": "ConversationFCO.TurnBreakpoint.v1",
        "id": f"BP-LAUNCH-{CONFIG['lane']}",
        "parent": CONFIG["predecessor_state"],
        "verified_new": ["code_sha256", "config_root", "control_route", "capability_state", "genesis_checkpoint"],
        "executed": ["CUDA_PREFLIGHT", "PUBLIC_GITHUB_CONTROL_READ", "GENESIS_CHECKPOINT_VERIFY"],
        "observed": {"start_utc": start_utc, "runtime": runtime, "h00": h0},
        "decisions": ["INFRASTRUCTURE_LIVENESS_ONLY", "NO_SHORT_LEASE", "GITHUB_SILENCE_CONTINUES"],
        "proposed": ["POST_30_MINUTE_LIVENESS", "H01_GITHUB_ROUNDTRIP"],
        "not_tested": ["30_MIN_SURVIVAL", "1H_SURVIVAL", "8H_SURVIVAL"],
        "failures": [],
        "unresolved": ["KAGGLE_RUNTIME_DURATION"],
        "next_action": "CONTINUE_TO_POST30M",
        "project_mmr_append": False,
        "signature_state": "NOT_SIGNED",
    })

    termination = None
    last_loss = None
    post30_written = False
    try:
        while True:
            now = time.monotonic()
            wall = now - started
            if STOP_REQUESTED:
                termination = f"PLATFORM_OR_OPERATOR_SIGNAL:{STOP_SIGNAL}"
                break
            if wall >= TARGET_SECONDS:
                termination = "TARGET_WALL_TIME_REACHED"
                break
            last_loss = training_step(model, opt, sched, device, step)
            step += 1

            if wall >= 1860 and not post30_written:
                post30_cp = checkpoint("post30m", step, model, opt, sched, started)
                atomic_json(POST30, {
                    "schema": "kaggle_longrun_post30m_breakpoint.v1",
                    "run_id": CONFIG["run_id"],
                    "lane": CONFIG["lane"],
                    "observed_wall_seconds": wall,
                    "state": "RUNNING",
                    "step": step,
                    "checkpoint_sha256": post30_cp["checkpoint_sha256"],
                    "both_runs_survive_30m": "UNKNOWN_REQUIRES_SHARED_OBSERVER",
                    "claim_ceiling": CONFIG["claim_ceiling"],
                })
                last_cp = post30_cp
                last_cp_t = now
                post30_written = True

            if now - last_cp_t >= CHECKPOINT_INTERVAL:
                last_cp = checkpoint("periodic_recovery", step, model, opt, sched, started)
                last_cp_t = now

            if now >= next_github_t:
                hour_index = int((now - started) // GITHUB_INTERVAL)
                control = observe_control()
                if control.get("fetch_state") != "ACCESSIBLE":
                    errors_since_hour.append(control.get("error", {}))
                if control.get("effective_action") == "CHECKPOINT_NOW":
                    last_cp = checkpoint("control_checkpoint_now", step, model, opt, sched, started)
                    last_cp_t = now
                elif control.get("effective_action") in {"PAUSE", "STOP"}:
                    last_cp = checkpoint("control_terminal", step, model, opt, sched, started)
                    termination = f"EXPLICIT_{control['effective_action']}"
                    write_hourly(hour_index, now - started, step, last_cp, control, errors_since_hour, "TERMINATING")
                    break
                write_hourly(hour_index, now - started, step, last_cp, control, errors_since_hour, "RUNNING")
                errors_since_hour = []
                last_action_seq = control.get("action_seq")
                next_github_t += GITHUB_INTERVAL

            if step % 25 == 0:
                torch.cuda.synchronize()
            time.sleep(float(CONFIG["step_sleep_seconds"]))
    except Exception as exc:
        error_record("WORKLOAD_LOOP", exc, False)
        termination = f"UNRECOVERABLE_RUNTIME:{type(exc).__name__}"

    final_cp = checkpoint("terminal", step, model, opt, sched, started)
    verify = verify_checkpoint(final_cp)
    wall = time.monotonic() - started
    if termination == "TARGET_WALL_TIME_REACHED" and verify["all_pass"]:
        test_result = "PASS_8H"
    elif termination and termination.startswith("PLATFORM_OR_OPERATOR_SIGNAL") and wall > 1800 and verify["all_pass"]:
        test_result = "PASS_PARTIAL_PLATFORM_LIMIT"
    elif termination and termination.startswith("UNRECOVERABLE_RUNTIME"):
        test_result = "FAIL_RUNTIME"
    elif not verify["all_pass"]:
        test_result = "FAIL_INTEGRITY"
    elif termination in {"EXPLICIT_STOP", "EXPLICIT_PAUSE"}:
        test_result = "ABSTAIN"
    else:
        test_result = "ABSTAIN"

    root, leaves = merkle_root_from_hourly()
    terminal = {
        "schema": "kaggle_longrun_terminal_result.v1",
        "created_at_utc": utc_now(),
        "project_id": CONFIG["project_id"],
        "run_id": CONFIG["run_id"],
        "lane": CONFIG["lane"],
        "test_result": test_result,
        "actual_wall_seconds": wall,
        "termination_cause": termination,
        "final_step": step,
        "last_loss": last_loss,
        "last_checkpoint": final_cp,
        "checkpoint_verify": verify,
        "hourly_observation_count": len(leaves),
        "lane_merkle_root": root,
        "survived_gt_30m": wall > 1800,
        "survived_gt_1h": wall > 3600,
        "survived_gt_2h": wall > 7200,
        "survived_gt_4h": wall > 14400,
        "survived_gt_6h": wall > 21600,
        "target_duration_reached": wall >= TARGET_SECONDS,
        "github_write_state": "INACCESSIBLE",
        "scientific_state": CONFIG["scientific_state"],
        "claim_ceiling": CONFIG["claim_ceiling"],
        "project_mmr_append": False,
        "signature_state": "NOT_SIGNED",
    }
    atomic_json(TERMINAL_RESULT, terminal)
    manifest = final_manifest()
    atomic_json(VERIFY_RECEIPT, {
        "schema": "kaggle_longrun_verify_receipt.v1",
        "created_at_utc": utc_now(),
        "terminal_checkpoint": verify,
        "hourly_merkle_root": root,
        "hourly_leaf_count": len(leaves),
        "manifest_body_sha256": manifest["manifest_body_sha256"],
        "state": "PASS" if verify["all_pass"] else "FAIL",
    })
    FINAL_HANDOFF.write_text(
        "# Kaggle Long-Run Final Handoff\n\n"
        + f"- Lane: {CONFIG['lane']}\n"
        + f"- Run ID: {CONFIG['run_id']}\n"
        + f"- Result: {test_result}\n"
        + f"- Wall seconds: {wall:.3f}\n"
        + f"- Termination: {termination}\n"
        + f"- Lane Merkle root: {root}\n"
        + "- Project MMR append: NO\n"
        + "- Signature state: NOT_SIGNED\n"
        + f"- Scientific state: {CONFIG['scientific_state']}\n"
        + f"- Claim ceiling: {CONFIG['claim_ceiling']}\n",
        encoding="utf-8",
    )
    return 0 if test_result in {"PASS_8H", "PASS_PARTIAL_PLATFORM_LIMIT", "ABSTAIN"} else 2

if __name__ == "__main__":
    raise SystemExit(main())
