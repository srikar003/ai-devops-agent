from __future__ import annotations

from functools import partial
from typing import Awaitable, Callable

from .config import settings
from .schema import ReviewState


def validate_node_call_limits(state: ReviewState, node_name: str) -> None:
    max_total_calls = max(1, settings.graph_max_total_node_calls)
    max_calls_per_node = max(1, settings.graph_max_calls_per_node)

    total_calls_after_run = len(state.node_calls) + 1
    calls_for_node_after_run = state.node_calls.count(node_name) + 1

    if total_calls_after_run > max_total_calls:
        recent_trail = ",".join(state.node_calls[-10:])
        raise RuntimeError(
            f"Graph node-call guard triggered: total calls {total_calls_after_run} exceeded limit {max_total_calls}. trail=[{recent_trail}]"
        )
    if calls_for_node_after_run > max_calls_per_node:
        recent_trail = ",".join(state.node_calls[-10:])
        raise RuntimeError(
            f"Graph node-call guard triggered: node '{node_name}' called {calls_for_node_after_run} times (limit {max_calls_per_node}). trail=[{recent_trail}]"
        )


def merge_node_call_record(
    node_output: dict,
    node_name: str,
) -> dict:
    return {
        **node_output,
        # Reducer fields must return only delta updates per step.
        "node_calls": [node_name],
    }


async def execute_node_with_guard(
    state: ReviewState,
    node_name: str,
    node_callable: Callable[[ReviewState], Awaitable[dict]],
) -> dict:
    validate_node_call_limits(state, node_name)
    node_output = await node_callable(state)
    if isinstance(node_output, dict):
        return merge_node_call_record(node_output, node_name)
    raise TypeError(
        f"Graph node '{node_name}' must return dict delta update, got {type(node_output).__name__}"
    )


def build_guarded_node_handler(
    node_name: str,
    node_callable: Callable[[ReviewState], Awaitable[dict]],
) -> Callable[[ReviewState], Awaitable[dict]]:
    return partial(execute_node_with_guard, node_name=node_name, node_callable=node_callable)
