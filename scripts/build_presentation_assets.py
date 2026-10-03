"""Render presentation assets from the existing public diagnostic snapshot.

No model calls, benchmark runs, or experimental-file writes are performed.
Requires matplotlib==3.10.7 in a separate optional presentation environment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports/packaging_evidence_20261003.json"


def main():
    study = json.loads(SOURCE.read_text())["simulator"]
    canonical = ROOT / "benchmark/tau3/results/user_simulator_stability_summary.json"
    if study != json.loads(canonical.read_text()):
        raise ValueError("Presentation source differs from the existing public Simulator snapshot")
    conditions = ("U0", "U2")
    rows = [study["conditions"][c] for c in conditions]
    denominators = [r["valid_simulations"] for r in rows]
    if len(set(denominators)) != 1:
        raise ValueError("This layout requires equal valid-trial denominators")

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelcolor": "#435064",
            "text.color": "#1c293b",
            "xtick.color": "#435064",
            "ytick.color": "#435064",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    colors = ["#79899e", "#2767b8"]
    panels = (
        ("expected_write_executed", "Expected WRITE completed"),
        ("premature_user_termination_before_write", "Premature termination before WRITE"),
    )
    plotted = {}
    for ax, (field, title) in zip(axes, panels):
        values = [r[field] for r in rows]
        plotted[field] = dict(zip(conditions, values))
        bars = ax.bar(conditions, values, color=colors, width=0.5, zorder=3)
        ax.set_title(title, loc="left", pad=14)
        ax.set_ylim(0, denominators[0] + 1.5)
        ax.set_yticks(range(0, denominators[0] + 1, 5))
        ax.set_ylabel("Valid trials (count)")
        ax.grid(axis="y", color="#e4e9f0", zorder=0)
        ax.tick_params(axis="both", length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for bar, value, denominator in zip(bars, values, denominators):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.35,
                f"{value}/{denominator}",
                ha="center",
                fontweight="bold",
                fontsize=12,
            )

    fig.suptitle(
        "User Simulator choice changed measured outcomes", x=0.065, ha="left", fontsize=17, fontweight="bold", y=0.98
    )
    fig.text(
        0.065,
        0.865,
        "Fixed Agent: Qwen3.5 Flash  |  5 selected retail tasks × 3 trials per condition",
        color="#435064",
        fontsize=10,
    )
    fig.text(0.065, 0.085, "U0: Qwen3.5 Flash User   ·   U2: Qwen3.8 Max User", fontsize=10)
    fig.text(
        0.065,
        0.025,
        "Development diagnostic; non-randomized. Not an Agent improvement or a universal model ranking.",
        color="#435064",
        fontsize=9,
    )
    fig.subplots_adjust(left=0.065, right=0.98, bottom=0.22, top=0.74, wspace=0.28)
    output = ROOT / "assets/simulator_ablation.png"
    output.parent.mkdir(exist_ok=True)
    fig.savefig(output, dpi=160, facecolor="white")
    plt.close(fig)

    provenance = {
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "canonical_snapshot": str(canonical.relative_to(ROOT)),
        "canonical_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "matplotlib_version": matplotlib.__version__,
        "denominators": dict(zip(conditions, denominators)),
        "plotted_counts": plotted,
        "figure": str(output.relative_to(ROOT)),
        "figure_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "interpretation_boundary": study["interpretation_boundary"],
    }
    (ROOT / "assets/simulator_ablation.provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({"figure": str(output.relative_to(ROOT)), "plotted_counts": plotted}))


if __name__ == "__main__":
    main()
