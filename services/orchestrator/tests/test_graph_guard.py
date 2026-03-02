from __future__ import annotations

import unittest

from services.orchestrator.app.graph_guard import (
    merge_node_call_record,
    validate_node_call_limits,
)
from services.orchestrator.app.schema import ReviewState


class GraphGuardTests(unittest.TestCase):
    def test_validate_node_call_limits_raises_for_total_limit(self) -> None:
        state = ReviewState(owner="o", repo="r", pr_number=1, node_calls=["a"] * 100)
        with self.assertRaises(RuntimeError):
            validate_node_call_limits(state, "fetch_pr")

    def test_validate_node_call_limits_raises_for_per_node_limit(self) -> None:
        state = ReviewState(
            owner="o",
            repo="r",
            pr_number=1,
            node_calls=["run_ci", "run_ci", "run_ci", "run_ci", "run_ci"],
        )
        with self.assertRaises(RuntimeError):
            validate_node_call_limits(state, "run_ci")

    def test_merge_node_call_record_updates_dict_output(self) -> None:
        result = merge_node_call_record({"findings": []}, "triage")
        self.assertEqual(["triage"], result["node_calls"])

    def test_merge_node_call_record_updates_state_output(self) -> None:
        state = ReviewState(owner="o", repo="r", pr_number=1)
        updated = merge_node_call_record(state, "fetch_pr")
        self.assertEqual(["fetch_pr"], updated.node_calls)
