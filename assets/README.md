# Presentation Assets

[`simulator_ablation.png`](simulator_ablation.png) visualizes two counts from the existing fixed-Agent User Simulator diagnostic: expected-WRITE completion and premature termination before WRITE. Each condition has 15 valid trials (five selected tasks × three repeats).

The generator reads [`packaging_evidence_20261003.json`](../reports/packaging_evidence_20261003.json) and verifies equality with the [existing public Simulator summary](../benchmark/tau3/results/user_simulator_stability_summary.json). It never fills chart values manually, calls models, or changes experimental artifacts. The [provenance file](simulator_ablation.provenance.json) records source/generator/image hashes, plotted counts, denominators, and plotting version.

## Regenerate from saved data

An optional presentation environment keeps plotting dependencies separate from the Agent runtime:

```bash
uv venv --python 3.12 .venv-presentation
uv pip install --python .venv-presentation/bin/python matplotlib==3.10.7
MPLCONFIGDIR=/tmp/reliabletoolagent-matplotlib \
  .venv-presentation/bin/python scripts/build_presentation_assets.py
```

Run these commands at the repository root. `.venv-presentation` is ignored by Git. This regenerates the figure and its provenance only; it is not a new experiment. Minor rasterization differences may depend on transitive plotting dependencies and platform, so hashes describe the saved figure rather than a promise of byte-identical rendering everywhere.

The plot is a non-randomized development diagnostic. It does not show an Agent algorithm improvement, error bars, a confidence interval, or a universal Simulator ranking. U0 includes one replacement of an infrastructure-invalid trial, disclosed in the [audit](../reports/packaging_audit_20261003.md).

The two architecture diagrams remain Mermaid in [README](../README.md#system--experiment-architecture); no decorative pipeline image duplicates them.
