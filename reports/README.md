# Evidence bundle

This directory contains the small, reviewable project evidence intended for GitHub. Large raw trajectories remain local and ignored.

| File | Purpose |
|---|---|
| [`final_technical_report.md`](final_technical_report.md) | Full research and engineering narrative |
| [`tau3-clean-audit-summary.json`](tau3-clean-audit-summary.json) | Machine-readable clean benchmark snapshot |
| [`../benchmark/tau3/`](../benchmark/tau3/) | Public τ³ launchers, analyzers, fixed configuration, and compact evidence |
| [`residual_case_T05.md`](residual_case_T05.md) | Offline reconstruction of the only valid reward-zero case |
| [`artifact_index.md`](artifact_index.md) | Map from each study phase to configs, summaries, and local raw evidence |
| [`evaluator-v2-ablation-summary.json`](evaluator-v2-ablation-summary.json) | Compact toy ablation summary after evaluator corrections |
| [`packaging_audit_20261003.md`](packaging_audit_20261003.md) | Read-only source checks, original/v2 score discrepancy, and presentation boundaries |
| [`packaging_evidence_20261003.json`](packaging_evidence_20261003.json) | New presentation snapshot of existing results with checked source hashes |
| [`../assets/README.md`](../assets/README.md) | Data-derived chart and regeneration/provenance notes |

The original E2 toy success is 23/24; the existing evaluator-v2 rescore is 24/24 for the same trajectories. The difference is disclosed rather than replaced with a new result. This packaging update does not run experiments or alter either scoring artifact.

Interpretation boundary: the project validates observability and failure attribution. It does not claim that a Guard, Controller, or structured error intervention improved τ³ performance.
