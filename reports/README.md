# Evidence bundle

This directory contains the small, reviewable evidence intended for GitHub and interview preparation. Large raw trajectories remain local and ignored.

| File | Purpose |
|---|---|
| [`final_technical_report.md`](final_technical_report.md) | Full research and engineering narrative |
| [`tau3-clean-audit-summary.json`](tau3-clean-audit-summary.json) | Machine-readable clean benchmark snapshot |
| [`../benchmark/tau3/`](../benchmark/tau3/) | Public τ³ launchers, analyzers, fixed configuration, and compact evidence |
| [`residual_case_T05.md`](residual_case_T05.md) | Offline reconstruction of the only valid reward-zero case |
| [`artifact_index.md`](artifact_index.md) | Map from each study phase to configs, summaries, and local raw evidence |
| [`resume_notes.md`](resume_notes.md) | Chinese/English bullets and interview talking points |
| [`evaluator-v2-ablation-summary.json`](evaluator-v2-ablation-summary.json) | Compact toy ablation summary after evaluator corrections |

Interpretation boundary: the project validates observability and failure attribution. It does not claim that a Guard, Controller, or structured error intervention improved τ³ performance.
