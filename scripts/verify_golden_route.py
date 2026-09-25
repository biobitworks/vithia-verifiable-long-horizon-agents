#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vithia.canonical import canonical_json_bytes, canonical_sha256
from vithia.integrity import verify_breakpoint, MMRAccumulator
from vithia.fco import fco_digest

GR = ROOT / "results/hackathon_runtime/golden_route"
OBJ = GR / "objects"
SP = ROOT / "results/hackathon_runtime/sponsors"
ok = True

items = []
for p in (GR / "breakpoints").glob("GR*.json"):
    d = json.loads(p.read_text())
    seq = d.get("breakpoint", {}).get("payload", {}).get("sequence")
    if isinstance(seq, int):
        items.append((seq, p, d))
items.sort()
mmr = MMRAccumulator()
route, ids, roots = [], [], []
for seq, p, receipt in items:
    bp = receipt["breakpoint"]
    state = []
    for oid in bp["payload"]["state_object_ids"]:
        op = OBJ / (oid.split(":", 1)[1] + ".json")
        if not op.exists():
            print(f"{p.name}: FAIL missing {oid}")
            ok = False
            state = []
            break
        state.append(json.loads(op.read_text()))
    if not state:
        continue
    v = verify_breakpoint(bp, state)
    mmr.append(seq, fco_digest(bp), bp["payload"]["state_version_id"])
    rm = receipt["mmr"]
    mmr_ok = (
        mmr.root() == rm["root_sha256"]
        and mmr.peaks == rm["peaks"]
        and mmr.leaf_count == rm["leaf_count"]
    )
    passed = v["passed"] and mmr_ok
    ok &= passed
    route.append(bp["payload"]["stage"])
    ids.append(bp["object_id"])
    roots.append(v["recomputed_merkle_root_sha256"])
    print(f"{p.name}: {'PASS' if passed else 'FAIL'} "
          f"MERKLE={v['recomputed_merkle_root_sha256']} MMR={mmr.root()}")
manifest = json.loads((GR / "GOLDEN_ROUTE_MANIFEST_V3.json").read_text())
manifest_hash = canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})
manifest_checks = {
    "manifest_hash": manifest_hash == manifest["manifest_sha256"],
    "route": route == manifest["route"],
    "breakpoint_ids": ids == manifest["breakpoint_ids"],
    "merkle_roots": roots == manifest["merkle_roots"],
    "mmr_root": mmr.root() == manifest["mmr_root"],
    "breakpoint_count": len(items) == len(manifest["breakpoint_ids"]),
}
manifest_ok = all(manifest_checks.values())
ok &= manifest_ok
print("MANIFEST_V3:", "PASS" if manifest_ok else "FAIL", manifest_checks)
print("FINAL_MMR:", mmr.root(), "LEAVES:", mmr.leaf_count)

media_checks = []
def check_media(file_name, receipt_name, key):
    global ok
    p = SP / file_name
    r = json.loads((SP / receipt_name).read_text())
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    expected = r[key]
    passed = actual == expected
    ok &= passed
    media_checks.append((file_name, passed, actual))
check_media("BFL_FLUX2_KLEIN4B_OUTPUT_V2.png", "BFL_USAGE_RECEIPT_V2.json", "media_sha256")
check_media("BFL_FLUX3_VIDEO_AUDIO_DRAFT.mp4", "BFL_FLUX3_VIDEO_AUDIO_ROUNDTRIP.json", "video_sha256")
check_media("BFL_FLUX3_LONGHORIZON_DASHBOARD_PROMPT_API_REPLAY.mp4",
            "BFL_DASHBOARD_PROMPT_API_REPLAY_RECEIPT.json", "video_sha256")
for name, passed, digest in media_checks:
    print(f"MEDIA {name}: {'PASS' if passed else 'FAIL'} {digest}")

bp_path = ROOT / "PUBLIC_PACKAGE_BREAKPOINT.json"
pkg = json.loads(bp_path.read_text())
excluded = {"PUBLIC_PACKAGE_BREAKPOINT.json", "RELEASE_RECEIPT.json"}
records = []
for p in sorted(x for x in ROOT.rglob("*") if x.is_file() and ".git" not in x.parts):
    rel = p.relative_to(ROOT).as_posix()
    if rel in excluded:
        continue
    b = p.read_bytes()
    records.append({"path": rel, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})

leaf_prefix = b"LONGHORIZON_PUBLIC_FILE_LEAF_V1:"
node_prefix = b"LONGHORIZON_PUBLIC_FILE_NODE_V1:"
leaf_hashes = [hashlib.sha256(leaf_prefix + canonical_json_bytes(r)).hexdigest() for r in records]
level = [bytes.fromhex(x) for x in leaf_hashes]
if not level:
    package_root = hashlib.sha256(b"LONGHORIZON_PUBLIC_FILE_EMPTY_V1").hexdigest()
else:
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(node_prefix + level[i] + level[i + 1]).digest()
            for i in range(0, len(level), 2)
        ]
    package_root = level[0].hex()

pkg_body = {k: v for k, v in pkg.items() if k != "breakpoint_sha256"}
pkg_checks = {
    "files": records == pkg["files"],
    "leaf_hashes": leaf_hashes == pkg["leaf_hashes"],
    "file_count": len(records) == pkg["file_count"],
    "merkle_root": package_root == pkg["merkle_root_sha256"],
    "golden_mmr_binding": mmr.root() == pkg["bound_golden_route_mmr_root"],
    "breakpoint_hash": canonical_sha256(pkg_body) == pkg["breakpoint_sha256"],
}
pkg_ok = all(pkg_checks.values())
ok &= pkg_ok
print("PUBLIC_PACKAGE:", "PASS" if pkg_ok else "FAIL", pkg_checks)
print("PUBLIC_PACKAGE_MERKLE:", package_root)
print("OVERALL:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
