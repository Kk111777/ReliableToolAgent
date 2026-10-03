"""Render auditable cohort coverage and bilingual reports from a compact bundle."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from frozen_study import file_sha, read_json, schedule, write_json
from study_evidence import audit, task_audit


EVENT_COUNTS = (
    "tool_calls",
    "explicit_tool_errors",
    "unknown_tool_results",
    "same_message_duplicate_calls",
    "same_message_excess_calls",
    "cross_turn_exact_repeats",
)
CANDIDATES = (
    "terminal_before_reference_write_candidate",
    "confirmation_terminal_before_write_candidate",
    "terminal_confirmation_candidate",
    "write_after_latest_confirmation_candidate",
)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def coverage(rows: list[dict], planned: int) -> dict:
    first = [r for r in rows if r["attempt"] == 0]
    valid = [r for r in first if r["status"] == "valid"]
    success = sum(r["metrics"]["official_final_reward"] == 1 for r in valid)
    restored = {r["slot_id"] for r in rows if r["status"] == "valid"}
    return {
        "planned_slots": planned,
        "first_attempts_retained": len(first),
        "first_attempt_status_counts": dict(sorted(Counter(r["status"] for r in first).items())),
        "valid_first_attempts": len(valid),
        "successful_first_attempts": success,
        "scored_non_success_first_attempts": len(valid) - success,
        "invalid_first_attempts": len(first) - len(valid),
        "unstarted_slots": planned - len(first),
        "success_over_valid_first_attempts": ratio(success, len(valid)),
        "success_over_retained_first_attempts": ratio(success, len(first)),
        "success_over_planned_slots": ratio(success, planned),
        "additional_attempts": sum(r["attempt"] > 0 for r in rows),
        "additional_attempt_status_counts": dict(
            sorted(Counter(r["status"] for r in rows if r["attempt"] > 0).items())
        ),
        "valid_slots_after_additional_attempts_secondary": len(restored),
        "slots_without_valid_result_after_additional_attempts": planned - len(restored),
    }


def events(rows: list[dict]) -> dict:
    terminal = [r for r in rows if r["metrics"].get("terminal_marker") in {"STOP", "TRANSFER"}]
    return {
        "retained_attempts": len(rows),
        "termination_reason_counts": dict(
            sorted(Counter(str(r["metrics"].get("termination_reason")) for r in rows).items())
        ),
        "terminal_marker_counts": dict(
            sorted(Counter(r["metrics"].get("terminal_marker", "NONE") for r in rows).items())
        ),
        "tool_event_totals": {key: sum(r["metrics"].get(key, 0) for r in rows) for key in EVENT_COUNTS},
        "candidate_attempt_counts": {key: sum(r["metrics"].get(key) is True for r in rows) for key in CANDIDATES},
        "real_terminal_attempts": len(terminal),
        "assistant_after_real_terminal_attempts": sum(
            r["metrics"].get("agent_after_terminal_user") is True for r in terminal
        ),
        "attempts_with_reference_write_keys": sum(r["metrics"].get("expected_write_key_count", 0) > 0 for r in rows),
        "attempts_with_all_reference_write_keys_matched": sum(
            r["metrics"].get("all_expected_writes_observed") is True for r in rows
        ),
    }


@dataclass
class StudyReport:
    payload: dict
    frozen_summary: dict
    evidence_file_sha256: str

    @classmethod
    def load(cls, path: Path) -> StudyReport:
        summary = audit(path)
        return cls(read_json(path), summary, file_sha(path))

    def recompute(self) -> dict:
        manifest = self.payload["manifest"]
        formal = [r for r in self.payload["rows"] if r["phase"] == "formal"]
        first = [r for r in formal if r["attempt"] == 0]
        slots = schedule(manifest, "formal")
        by_key = {(r["task_id"], r["trial"], r["condition"]): r for r in first}
        pair_counts = Counter()
        missing_pairs = []
        tasks = []
        for task in manifest["task_ids"]:
            task_rows = [r for r in first if r["task_id"] == task]
            task_conditions = {
                condition: coverage([r for r in task_rows if r["condition"] == condition], manifest["trials"])
                for condition in manifest["conditions"]
            }
            differences = []
            for trial in range(manifest["trials"]):
                pair = [by_key.get((task, trial, condition)) for condition in manifest["conditions"]]
                retained = sum(r is not None for r in pair)
                state = "both_retained" if retained == 2 else "one_unstarted" if retained == 1 else "both_unstarted"
                pair_counts[state] += 1
                if all(r and r["status"] == "valid" for r in pair):
                    pair_counts["both_valid"] += 1
                    differences.append(
                        pair[1]["metrics"]["official_final_reward"] - pair[0]["metrics"]["official_final_reward"]
                    )
                else:
                    missing_pairs.append(
                        {
                            "task_id": task,
                            "trial": trial,
                            "statuses": [r["status"] if r else "unstarted" for r in pair],
                        }
                    )
            tasks.append(
                {
                    "task_id": task,
                    "conditions": task_conditions,
                    "valid_primary_trial_pairs": len(differences),
                    "mean_reward_difference_U2_minus_U0_complete_task_only": sum(differences) / manifest["trials"]
                    if len(differences) == manifest["trials"]
                    else None,
                }
            )
        task_metadata = task_audit(manifest)["tasks"]
        family_key = "stratum" if manifest.get("official_split") == "train" else "write_family"
        selected = [t for t in task_metadata if t["task_id"] in manifest["task_ids"]]
        families = {}
        for family in sorted({t[family_key] for t in selected}):
            ids = {t["task_id"] for t in selected if t[family_key] == family}
            families[family] = {
                condition: coverage(
                    [r for r in formal if r["task_id"] in ids and r["condition"] == condition],
                    len(ids) * manifest["trials"],
                )
                for condition in manifest["conditions"]
            }
        return {
            "report_schema_version": 1,
            "study_id": manifest["study_id"],
            "official_split": manifest.get("official_split", "test"),
            "execution_coverage": "all_primary_slots_retained"
            if self.frozen_summary["complete"]
            else "incomplete_snapshot",
            "evidence_file_sha256": self.evidence_file_sha256,
            "evidence_payload_sha256": self.payload["payload_sha256"],
            "report_source_sha256": file_sha(Path(__file__)),
            "engineering_gate_pass": self.frozen_summary["engineering_gate_pass"],
            "conditions": {
                condition: coverage([r for r in formal if r["condition"] == condition], len(slots) // 2)
                for condition in manifest["conditions"]
            },
            "pairs": {
                "planned": len(slots) // 2,
                **{
                    key: pair_counts[key] for key in ("both_retained", "one_unstarted", "both_unstarted", "both_valid")
                },
                "without_two_valid_first_attempts": len(missing_pairs),
                "missing_or_invalid_pairs": missing_pairs,
            },
            "tasks": tasks,
            "business_family_coverage": families,
            "event_diagnostics": {
                "all_retained_first_attempts": events(first),
                "valid_first_attempts": events([r for r in first if r["status"] == "valid"]),
            },
            "frozen_bootstrap_results": {
                key: value
                for key, value in self.frozen_summary.items()
                if "bootstrap" in key or "near_duplicate" in key
            },
            "usage_all_phases_by_role": self.frozen_summary["usage_all_phases_by_role"],
            "billing_all_phases": self.frozen_summary["billing_all_phases"],
            "first_attempt_wall_seconds_by_condition": self.frozen_summary["first_attempt_wall_seconds_by_condition"],
            "boundary": (
                "One cohort only; no pooled test/train score. Success means official reward exactly 1; "
                "a valid fractional reward is a scored non-success, not an infrastructure failure. "
                "Additional attempts never change first-attempt denominators or the engineering gate. "
                "Retained-attempt and planned-slot rates describe execution coverage as well as outcomes. "
                "An incomplete bundle does not prove execution stopped or authorize final publication. "
                "Bootstrap results are unchanged frozen diagnostics on complete three-trial tasks. "
                "Candidate events do not establish component causality or Agent improvement. "
                "Billing covers this bundle, not the account's full paid history; estimates are not invoices."
            ),
        }

    def render(self, result: dict, *, chinese: bool = False) -> str:
        if chinese:
            lead = f"# Retail 单批次证据报告\n\n批次：`{result['study_id']}`。split：`{result['official_split']}`。"
            state = "全部首次槽位已保留" if self.frozen_summary["complete"] else "未完成快照"
            headers = "条件 | 计划 | 首次已尝试 | 有效 | reward=1 | 已评分但未满分 | 无效 | 未启动 | 补跑"
            rates = "条件 | 成功/有效首次 | 成功/已尝试首次 | 成功/计划槽位"
            note = (
                "未启动槽位没有模型结果。无效首次包含基础设施、超时或预算中断，不能算成已评分的模型失败。"
                "补跑仅作为次级覆盖，不改变首次分母或工程门槛。reward=1表示满分成功；有效的部分分数保留在原证据中。"
            )
            pair_note = "首次配对覆盖"
            interval_note = "冻结的任务级平均reward差异与95%区间（U2−U0）"
            cost_note = "角色用量与原价估算；仅本证据包，非账户总消费或账单"
            end = (
                "本批次不能与另一split合并为官方test成绩。区间只使用三次配对完整的任务，"
                "不把重复trial当作独立任务。候选事件不证明组件因果或Agent算法收益。"
                "两项冻结字段的覆盖限制见预算运行说明：完成部分WRITE后仍可能漏掉最后WRITE；"
                "无User消息时agent_after_terminal_user也可能为True，本报告仅在真实STOP/TRANSFER下汇总该字段。"
                "未完成快照不证明执行已停止；正式发布仍须核对进程锁、停止原因及原始证据。"
            )
        else:
            lead = f"# Retail cohort evidence report\n\nStudy: `{result['study_id']}`. Split: `{result['official_split']}`."
            state = "All primary slots retained" if self.frozen_summary["complete"] else "Incomplete snapshot"
            headers = "Condition | Planned | First retained | Valid | Reward=1 | Scored non-success | Invalid | Unstarted | Additional"
            rates = "Condition | Success/valid first | Success/retained first | Success/planned slots"
            note = (
                "Unstarted slots have no model outcome. Invalid first attempts include infrastructure failures, "
                "timeouts or budget interruptions; they are not scored model failures. Additional attempts are "
                "secondary coverage and never change first-attempt denominators or the engineering gate. "
                "Success means reward=1; valid fractional rewards remain in the source evidence."
            )
            pair_note = "First-attempt pair coverage"
            interval_note = "Frozen task-level mean reward difference and 95% interval (U2−U0)"
            cost_note = "Role usage and list-price estimates; this bundle only, not account totals or invoices"
            end = (
                "Do not pool this cohort with another split as an official test score. Intervals use complete "
                "three-trial tasks and do not count repeated trials as independent tasks. Candidate events do "
                "not establish component causality or Agent improvement. See the budgeted execution guide for "
                "the frozen field limits: a remaining WRITE can be missed after earlier ones completed; "
                "agent_after_terminal_user can be true without a user message, so this report counts it only "
                "with a real STOP/TRANSFER marker. An incomplete snapshot does not prove execution stopped; "
                "final publication still needs lock, stop-reason and retained-evidence checks."
            )
        count_fields = (
            "planned_slots",
            "first_attempts_retained",
            "valid_first_attempts",
            "successful_first_attempts",
            "scored_non_success_first_attempts",
            "invalid_first_attempts",
            "unstarted_slots",
            "additional_attempts",
        )
        lines = [
            lead,
            "",
            f"**{state}**；{'工程门槛' if chinese else 'engineering gate'}=`{str(result['engineering_gate_pass']).lower()}`.",
            "",
            headers,
            " | ".join(["---"] * 9),
        ]
        for condition, row in result["conditions"].items():
            lines.append(" | ".join([condition, *(str(row[key]) for key in count_fields)]))
        lines.extend(["", note, "", rates, "--- | --- | --- | ---"])
        for condition, row in result["conditions"].items():
            success = row["successful_first_attempts"]
            fractions = [
                f"{success}/{row[key]}" if row[key] else "NA (0 denominator)"
                for key in ("valid_first_attempts", "first_attempts_retained", "planned_slots")
            ]
            lines.append(" | ".join([condition, *fractions]))
        pair_labels = (
            ["计划", "双方有首次记录", "双方首次有效", "一方未启动", "双方未启动", "无完整有效配对"]
            if chinese
            else [
                "Planned",
                "Both retained",
                "Both valid",
                "One unstarted",
                "Both unstarted",
                "Without two valid first attempts",
            ]
        )
        pair_fields = (
            "planned",
            "both_retained",
            "both_valid",
            "one_unstarted",
            "both_unstarted",
            "without_two_valid_first_attempts",
        )
        lines.extend(
            [
                "",
                pair_note,
                "",
                " | ".join(pair_labels),
                " | ".join(["---"] * 6),
                " | ".join(str(result["pairs"][key]) for key in pair_fields),
            ]
        )
        lines.extend(
            [
                "",
                interval_note,
                "",
                "分析 | 完整任务 | 重采样簇 | 平均差异 | 95%区间"
                if chinese
                else "Analysis | Complete tasks | Resampling clusters | Mean difference | 95% CI",
                "--- | --- | --- | --- | ---",
            ]
        )
        for name, value in result["frozen_bootstrap_results"].items():
            difference, interval = value["mean_difference_U2_minus_U0"], value["confidence_interval_95"]
            cells = [
                name,
                str(value["complete_tasks"]),
                str(value.get("resampling_clusters", 0)),
                f"{difference:.4f}" if difference is not None else "NA",
                f"[{interval[0]:.4f}, {interval[1]:.4f}]" if interval is not None else "NA",
            ]
            lines.append(" | ".join(cells))
        lines.extend(
            [
                "",
                cost_note,
                "",
                "角色 | HTTP | 缺失用量 | 输入token | 输出token | 已知费用(元) | 预留(元)"
                if chinese
                else "Role | HTTP | Missing usage | Input tokens | Output tokens | Known RMB | Reserved RMB",
                "--- | --- | --- | --- | --- | --- | ---",
            ]
        )
        for role, value in result["usage_all_phases_by_role"].items():
            cells = [
                role,
                str(value["observed_http_requests"]),
                str(value["missing_usage_requests"]),
                str(value["prompt_tokens_known"]),
                str(value["completion_tokens_known"]),
                f"{value['known_list_price_rmb']:.6f}",
                f"{value['conservative_budget_debit_rmb'] - value['known_list_price_rmb']:.6f}",
            ]
            lines.append(" | ".join(cells))
        details = (
            "逐任务、业务家族、缺失配对、首跑状态、事件候选、延迟及完整角色用量见summary.json。"
            "token仅统计已返回用量；reasoning包含在output中，不重复计费。缺失用量保留预留。"
            if chinese
            else "See summary.json for per-task and family coverage, every missing pair, first-attempt statuses, event candidates, latency and full role usage. Tokens count returned usage only; reasoning is part of output, not an additional charge. Missing usage retains its reservation."
        )
        lines.extend(
            [
                "",
                details,
                "",
                end,
                "",
                f"Evidence SHA256: `{result['evidence_file_sha256']}`",
                f"Report source SHA256: `{result['report_source_sha256']}`",
                "",
            ]
        )
        return "\n".join(lines)

    def save(self, destination: Path) -> dict:
        result = self.recompute()
        english, chinese = self.render(result), self.render(result, chinese=True)
        destination.mkdir(parents=True, exist_ok=False)
        write_json(destination / "summary.json", result, exclusive=True)
        (destination / "report.md").write_text(english)
        (destination / "report.zh-CN.md").write_text(chinese)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="audited compact evidence; one cohort only")
    parser.add_argument("--output", required=True, type=Path, help="new directory; never overwrite reports")
    args = parser.parse_args()
    result = StudyReport.load(args.input).save(args.output)
    print({key: result[key] for key in ("study_id", "execution_coverage", "engineering_gate_pass")})


if __name__ == "__main__":
    main()
