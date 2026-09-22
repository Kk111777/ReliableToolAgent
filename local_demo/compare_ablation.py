"""Read-only trajectory comparison for the four ablation conditions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ablation import ABLATION_ROOT, CONDITIONS


def _path(condition: str, task_id: str, repeat_index: int) -> Path:
    return ABLATION_ROOT / condition / f"r{repeat_index:02d}" / f"{task_id}.json"


def _print_record(record: dict) -> None:
    if record["tool_name"] == "final_answer":
        answer = " ".join(str(record.get("result") or "").split())
        if len(answer) > 180:
            answer = answer[:180] + "..."
        print(f"  S{record['step_index']} C{record['call_index']} final_answer -> {answer}")
        return
    arguments = json.dumps(record.get("arguments"), ensure_ascii=False, sort_keys=True)
    if record["status"] == "error":
        print(
            f"  S{record['step_index']} C{record['call_index']} "
            f"{record['tool_name']}({arguments}) -> ERROR {record['error_type']}"
        )
        metadata = {
            key: record.get(key)
            for key in ("retryable_same_call", "scope", "message", "details")
            if record.get(key) is not None
        }
        if metadata:
            print(f"      structured_metadata={json.dumps(metadata, ensure_ascii=False, sort_keys=True)}")
        else:
            error = record.get("error") or {}
            print(f"      raw_error={error.get('message', error) if isinstance(error, dict) else error}")
    else:
        print(
            f"  S{record['step_index']} C{record['call_index']} "
            f"{record['tool_name']}({arguments}) -> OK {record.get('result')}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True, choices=[f"P{i:02d}" for i in range(1, 9)])
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    for condition in CONDITIONS:
        path = _path(condition, args.task_id, args.repeat)
        if not path.exists():
            raise SystemExit(f"Missing artifact: {path}")
        report = json.loads(path.read_text())
        print(f"===== {condition} =====")
        print(
            json.dumps(
                {
                    "model_id": report["model_id"],
                    "task_id": report["task_id"],
                    "repeat": report["repeat"],
                    "error_mode": report["error_mode"],
                    "retry_framing": report["retry_framing"],
                    "metrics": report["metrics"],
                },
                ensure_ascii=False,
            )
        )
        for record in report["trajectory"]:
            _print_record(record)


if __name__ == "__main__":
    main()
