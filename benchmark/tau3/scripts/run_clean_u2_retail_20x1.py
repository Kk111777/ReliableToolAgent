"""Run the clean U2-user retail development set once."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evaluator_retry_wrapper import (
    EvaluatorRetryRecorder,
    install_evaluator_parse_retry,
)


AGENT_MODEL = "openai/qwen3.5-flash-2026-02-23"
USER_MODEL = "openai/qwen3.8-max-2026-09-02"
MODEL_ARGS = {
    "temperature": 0,
    "max_tokens": 512,
    "timeout": 60,
    "num_retries": 3,
}
SAVE_TO = "tau3-retail-clean-u2-20x1"
TASK_IDS = [str(task_id) for task_id in range(20)]


def main() -> None:
    import tau2.evaluator.evaluator_nl_assertions as evaluator_module
    import tau2.runner.simulation as simulation_module

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
        USER_MODEL,
        "--user-llm-args",
        model_args,
        "--num-trials",
        "1",
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
        SAVE_TO,
    ]

    try:
        from tau2.cli import main as tau2_main

        tau2_main()
    finally:
        uninstall()
        simulation_module.evaluate_simulation = original_evaluate
        output_dir = Path("data/simulations") / SAVE_TO
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
        (output_dir / "clean_config.json").write_text(
            json.dumps(
                {
                    "agent_model": AGENT_MODEL,
                    "user_model": USER_MODEL,
                    "evaluator_model": AGENT_MODEL,
                    "model_args": MODEL_ARGS,
                    "task_ids": TASK_IDS,
                    "num_trials": 1,
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


if __name__ == "__main__":
    main()
