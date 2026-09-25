# Vithia Hackathon Breakpoint Protocol v1

Claim boundary: Anticube and Hydra ΔG* are `SIMULATION_ONLY`; biological validation is `NOT_TESTED`. Merkle/MMR prove declared-byte identity and append-only custody, not truth.

| Breakpoint | Type | Minimum committed objects | Demo question answered |
|---|---|---|---|
| BP0 | `INGEST_CUSTODY` | SourceFCO, DatasetFCO, QuestionFCO/JEVFCO | What exact input entered? |
| BP1 | `FCG_CONSTRUCTION` | AtomFCO, BridgeFCO, FCGStateFCO | What knowledge graph was constructed? |
| BP2 | `SIMULATION_FIELD` | AnticubeClassificationFCO, HydraFieldFCO, HydraTransitionFCO | What simulated metadata existed before selection? |
| BP3 | `PATH_DECISION` | CandidatePathFCO, PathSetFCO, GoldenPathFCO, DarkPathFCO, SelectorModelFCO or deterministic selector config | What was selected and what alternatives were retained? |
| BP4 | `CONTEXT_PROJECTION` | ContextProjectionFCO with exact context bytes/hash and budget | What exact bytes did the reader see? |
| BP5 | `SUCCESSOR_TRANSITION` | ReaderInvocationFCO, ModelOutputFCO, ObservationFCO, FCGStateFCO(t+1), RestartCapsuleFCO | Can a fresh process reconstruct and continue? |
| EBP0 | `EVALUATION_PREREG` | EvaluationPlanFCO | What metrics/gates were fixed before results? |
| EBP1 | `EVALUATION_RESULT` | EvaluationResultFCO(s) | Did the external/held-out test pass without moving the goalposts? |

## Hard invariants

- Exact canonical object hashes must recompute.
- Every breakpoint Merkle root must recompute from its declared ordered state-object list.
- Cumulative MMR replay must reproduce its root.
- BP4 exact context bytes must reconstruct byte-for-byte.
- BP5 restart must not require the original conversation transcript.
- Failed/null/negative/deferred states remain addressable successors; they are never overwritten.
- Learned selector is admitted only if its preregistered held-out gate passes; otherwise deterministic fallback remains canonical for the demo.
