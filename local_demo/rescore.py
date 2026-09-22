"""Re-score frozen pilot/ablation artifacts without making model calls."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ablation import ABLATION_ROOT, CONDITIONS, summarize_ablation
from .pilot import ARTIFACTS, evaluate_pilot, summarize_reports
from .pilot_tasks import get_pilot_task


EVALUATOR_VERSION = "pilot-evaluator-v2"
RESCORE_ROOT = ARTIFACTS / "rescored"


class StoredResult:
    def __init__(self, output: Any, run: dict[str, Any]):
        self.output = output
        self._run = run

    def dict(self) -> dict[str, Any]:
        return self._run


def _source_specs(source: str) -> list[tuple[str, Path, Path]]:
    specs: list[tuple[str, Path, Path]] = []
    if source in {"pilot", "all"}:
        for condition in ("raw-error", "structured-error"):
            specs.append((f"pilot/{condition}", ARTIFACTS / condition, RESCORE_ROOT / "pilot" / condition))
    if source in {"ablation", "all"}:
        for condition in CONDITIONS:
            specs.append(
                (
                    f"ablation/{condition}",
                    ABLATION_ROOT / condition,
                    RESCORE_ROOT / "ablation" / condition,
                )
            )
    return specs


def _rescore_report(report: dict[str, Any]) -> dict[str, Any]:
    task = get_pilot_task(report["task_id"])
    run = report["run"]
    output = report.get("output", run.get("output"))
    evaluated = evaluate_pilot(task, StoredResult(output, run))
    updated = dict(report)
    updated.update(evaluated)
    updated["evaluator_version"] = EVALUATOR_VERSION
    return updated


def rescore(source: str, output_root: Path = RESCORE_ROOT) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    total = 0
    for label, source_dir, _destination_dir in _source_specs(source):
        reports: list[dict[str, Any]] = []
        for path in sorted(source_dir.glob("r*/P*.json")):
            report = _rescore_report(json.loads(path.read_text()))
            reports.append(report)
            destination = output_root / Path(label) / path.relative_to(source_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
            total += 1
        if not reports:
            continue
        summary = summarize_reports(reports)
        summary_path = output_root / Path(label) / "summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        summaries[label] = summary

    if source in {"ablation", "all"}:
        ablation_reports = {
            condition: [
                json.loads(path.read_text())
                for path in sorted((output_root / "ablation" / condition).glob("r*/P*.json"))
            ]
            for condition in CONDITIONS
        }
        if all(ablation_reports.values()):
            root_summary = summarize_ablation(ablation_reports)
            (output_root / "ablation" / "summary.json").write_text(
                json.dumps(root_summary, ensure_ascii=False, indent=2) + "\n"
            )

    manifest = {
        "evaluator_version": EVALUATOR_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_artifacts_unchanged": True,
        "report_count": total,
        "summaries": sorted(summaries),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("pilot", "ablation", "all"), default="all")
    parser.add_argument("--output-root", type=Path, default=RESCORE_ROOT)
    args = parser.parse_args()
    print(json.dumps(rescore(args.source, args.output_root), ensure_ascii=False))


if __name__ == "__main__":
    main()
