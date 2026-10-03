"""Select an additional retail sample using task metadata, never model outcomes."""

from __future__ import annotations

import random
from collections import Counter


STRATUM_QUOTAS = {
    "cancel": 2,
    "exchange": 3,
    "multi_write": 5,
    "pending_modify": 4,
    "policy_or_readonly": 2,
    "profile_modify": 1,
    "return": 3,
}


def select_stratified(
    candidates: list[dict], similarities: dict[tuple[str, str], float], *, seed: int = 20261003
) -> list[dict]:
    rng = random.Random(seed)
    selected = []
    for family, quota in STRATUM_QUOTAS.items():
        pool = sorted([row for row in candidates if row["stratum"] == family], key=lambda r: int(r["task_id"]))
        rng.shuffle(pool)
        accepted = []
        for row in pool:
            if any(
                similarities.get(tuple(sorted([row["task_id"], old["task_id"]])), 0) >= 0.9
                for old in selected + accepted
            ):
                continue
            accepted.append(row)
            if len(accepted) == quota:
                break
        if len(accepted) != quota:
            raise ValueError(f"not enough distinct candidates in {family}")
        selected.extend(accepted)
    if Counter(row["stratum"] for row in selected) != Counter(STRATUM_QUOTAS):
        raise ValueError("stratum quota mismatch")
    if len({row["task_id"] for row in selected}) != 20:
        raise ValueError("task IDs are not unique")
    return sorted(selected, key=lambda row: int(row["task_id"]))
