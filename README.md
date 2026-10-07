# Vithia — Verifiable Long-Horizon Agents

Hackathon-specific public evidence repository for the **Long Horizon Agents Hack 2026**.

Vithia separates a growing persistent evidence graph from the bounded context presented to a model. Work is represented as independently addressable FCO objects connected in an FCG, with explicit Golden/Dark path selection, exact context projection, successor state, and cryptographic breakpoints.

## Live submission

- Tokens& project: https://tokensand.com/p/vithia-verifiable-long-horizon-agents?mode=developer
- Working demo: https://vithia-longhorizon-hackathon.vercel.app/
- Demo video: https://vithia-longhorizon-hackathon.vercel.app/demo.mp4
- Public repository: https://github.com/biobitworks/vithia-verifiable-long-horizon-agents

## Current verified Golden Route

- Breakpoints: **14** (GR0 through GR13)
- Final breakpoint: fco:ff58c25a8cb416241fc468520f4c9a3514bc8fcab0e7fab30f9147a80a696093
- Final cumulative MMR root: 47292dd4a67dcd23e759059856da2f22f341c6b2178d0e211a42777bc7949087
- Manifest: results/hackathon_runtime/golden_route/GOLDEN_ROUTE_MANIFEST_V3.json
- Independent recomputation: **PASS**

The verifier rebuilds every breakpoint Merkle root from the included FCO objects and replays the cumulative MMR from sequence 0. It does not trust the stored roots as proof.

## Sponsor execution state

| Lane | State |
|---|---|
| Liquid AI | **PASS** — local LFM2.5-1.2B executed over the exact BP4 context |
| Nimble | **PASS** — live search returned three resolved source URLs |
| RawTree / Tinybird shared lane | **PASS via RawTree** — insert + SQL readback; direct Tinybird API remains NOT_TESTED |
| Black Forest Labs image | **PASS** — FLUX.2 Klein image artifact is byte-hashed |
| Black Forest Labs video/audio | **PASS_WITH_RAW_WHITESPACE_DRIFT** — normalized STT exact match, WER 0.0 |
| BFL dashboard-prompt API replay | **PASS_WITH_RAW_WHITESPACE_DRIFT** — prompt identity match and normalized transcript exact match |
| BFL finetune | BLOCKED_NO_CHECKPOINT — training/upload/finetuned inference remain NOT_TESTED |
| OTEL | DEFERRED |

Failed and partial predecessors remain in the route rather than being overwritten.

## Verify locally

Requirements: Python 3, standard library only.

~~~bash
python3 scripts/verify_golden_route.py
~~~

A successful run prints each breakpoint, the recomputed cumulative MMR, sponsor-media checks, and OVERALL: PASS.

## Architecture

source → FCO atoms → FCG → Anticube/ΔG* simulation metadata → candidate Golden/Dark paths → exact ContextProjectionFCO → model/action output → successor FCG → Merkle/MMR

The exact active context is committed as bytes rather than represented only by a token count. A cold-restart test kills the agent process and reconstructs the same bounded context/custody state from persisted objects without requiring the original conversation.

## Post-publication validation

- Anonymous GitHub page/raw README access: **PASS**
- Anonymous git ls-remote: **PASS**
- Nimble extraction of this public repository: **PASS**; repository name and current Golden Route root were observed.
- RawTree publication-event insert: **HTTP 200**; immediate SQL readback returned zero rows, so this specific post-publication check is preserved as **FAIL**. The earlier GR5 RawTree insert/readback integration remains **PASS** and is not overwritten by this successor observation.

## Claim boundary

Merkle inclusion establishes integrity/inclusion, not causality or truth. Hashes establish identity, not correctness. Anticube and Hydra/ΔG* are simulation metadata in this MVP; biological validation is NOT_TESTED.

See PUBLICATION_STATUS.json, docs/BREAKPOINT_PROTOCOL.md, and the individual sponsor receipts for bounded claims.

**License:** Unless otherwise explicitly licensed, original Biobitworks material in this repository is licensed under [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/); third-party components remain under their respective licenses.
