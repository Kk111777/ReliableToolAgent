"""Run the fixed-agent U0/U1/U2 retail user-simulator ablation.

This is a benchmark launcher only.  It changes the user-simulator model
between separate runs and leaves the official tau2 runtime untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evaluator_retry_wrapper import (
    EvaluatorRetryRecorder,
    install_evaluator_parse_retry,
)


AGENT_MODEL = "openai/qwen3.5-flash-2026-02-23"
U0_MODEL = AGENT_MODEL
# Read from tau2/config.py at the pinned commit, rather than from memory.
U1_MODEL = "gpt-4.1-2025-04-14"
U2_MODEL = "openai/qwen3.8-max-2026-09-02"
TASK_IDS = ["0", "4", "5", "6", "7"]
MODEL_ARGS = {
    "temperature": 0,
    "max_tokens": 512,
    "timeout": 60,
    "num_retries": 3,
}


def run(condition: str, num_trials: int = 1, auto_resume: bool = False) -> None:
    if condition not in {"U0", "U1", "U2"}:
        raise ValueError("condition must be U0, U1, or U2")

    import tau2.evaluator.evaluator_nl_assertions as evaluator_module
    import tau2.runner.simulation as simulation_module

    user_model = {
        "U0": U0_MODEL,
        "U1": U1_MODEL,
        "U2": U2_MODEL,
    }[condition]
    save_to = f"tau3-retail-user-simulator-ablation-{condition.lower()}-0-4"

    # Keep evaluator model and parameters fixed to the infrastructure-stable
    # baseline.  The only experimental change is user_model below.
    evaluator_module.DEFAULT_LLM_NL_ASSERTIONS = AGENT_MODEL
    evaluator_module.DEFAULT_LLM_NL_ASSERTIONS_ARGS = dict(MODEL_ARGS)

    recorder = EvaluatorRetryRecorder()
    original_evaluate = simulation_module.evaluate_simulation

    def tracked_evaluate(*args, **kwargs):
        task = kwargs.get("task")
        recorder.set_task(str(task.id) if task is not None else None)
        return original_evaluate(*args, **kwargs)

    simulation_module.evaluate_simulation = tracked_evaluate
    uninstall = install_evaluator_parse_retry(
        evaluator_module,
        recorder,
        max_parse_retries=2,
    )

    model_args = json.dumps(MODEL_ARGS, separators=(",", ":"))
    sys.argv = [
        "tau2",
        "run",
        "--domain",
        "retail",
        "--task-split-name",
        "base",
        "--task-ids",
        *TASK_IDS,
        "--agent-llm",
        AGENT_MODEL,
        "--agent-llm-args",
        model_args,
        "--user-llm",
        user_model,
        "--user-llm-args",
        model_args,
        "--num-trials",
        str(num_trials),
        "--max-steps",
        "200",
        "--max-concurrency",
        "1",
        "--workers",
        "0",
        "--max-retries",
        "0",
        "--seed",
        "300",
        "--save-to",
        save_to,
    ]
    if auto_resume:
        sys.argv.append("--auto-resume")

    output_dir = Path("data/simulations") / save_to
    try:
        from tau2.cli import main as tau2_main

        tau2_main()
    finally:
        uninstall()
        simulation_module.evaluate_simulation = original_evaluate
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evaluator_retry.json").write_text(
            json.dumps(
                {
                    "max_parse_retries": 2,
                    "records": recorder.records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (output_dir / "ablation_config.json").write_text(
            json.dumps(
                {
                    "condition": condition,
                    "agent_model": AGENT_MODEL,
                    "user_model": user_model,
                    "evaluator_model": AGENT_MODEL,
                    "model_args": MODEL_ARGS,
                    "task_ids": TASK_IDS,
                    "num_trials": num_trials,
                    "max_steps": 200,
                    "simulation_timeout": None,
                    "runner_max_retries": 0,
                    "concurrency": 1,
                    "seed": 300,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("condition", choices=["U0", "U1", "U2"])
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--auto-resume", action="store_true")
    args = parser.parse_args()
    run(args.condition, num_trials=args.num_trials, auto_resume=args.auto_resume)


if __name__ == "__main__":
    main()
