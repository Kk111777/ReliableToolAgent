"""The larger sample has fixed strata and does not read simulation rewards."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from extend_retail_design import STRATUM_QUOTAS, select_stratified  # noqa: E402


def test_fixed_strata_are_reproducible_and_unique():
    candidates = [
        {"task_id": str(i * 10 + j), "stratum": family}
        for i, (family, count) in enumerate(STRATUM_QUOTAS.items())
        for j in range(count + 2)
    ]
    selected = select_stratified(candidates, {})
    assert selected == select_stratified(list(reversed(candidates)), {})
    assert len(selected) == 20
    assert Counter(row["stratum"] for row in selected) == Counter(STRATUM_QUOTAS)


def test_insufficient_stratum_stops_selection():
    with pytest.raises(ValueError, match="not enough"):
        select_stratified([], {})
