from __future__ import annotations
from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
import logging
import os
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from .schema import ReviewState
from .graph import build_graph, render_graph_png
from .config import settings

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

graph = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global graph

    if settings.database_url:
        try:
            async with AsyncPostgresSaver.from_conn_string(
                settings.database_url
            ) as checkpoint_saver:
                await checkpoint_saver.setup()
                logger.info("checkpoint.postgres enabled")
                graph = build_graph(checkpointer=checkpoint_saver)
                yield
        except Exception as exc:  # noqa: BLE001
            logger.exception("checkpoint.postgres init failed error=%s", str(exc))
            raise RuntimeError(
                f"Failed to initialize postgres checkpointer: {exc}"
            ) from exc
    else:
        logger.warning("checkpoint.postgres disabled because DATABASE_URL is empty")
        graph = build_graph()
        yield


app = FastAPI(title="AI DevOps Orchestrator", lifespan=lifespan)


class RunRequest(BaseModel):
    owner: str
    repo: str
    pr_number: int
    thread_id: str | None = None


class RunDecisionRequest(BaseModel):
    thread_id: str
    approve: bool
    edited_comment: str | None = None


def get_node_calls_count(values: dict[str, Any] | None) -> int:
    if not isinstance(values, dict):
        return 0
    return len(values.get("node_calls", []) or [])


def get_interrupts(result: Any) -> list[Any]:
    if isinstance(result, dict):
        interrupts = result.get("__interrupt__", [])
        if isinstance(interrupts, list):
            return interrupts
    return []


async def load_state_for_thread(thread_id: str) -> ReviewState:
    state_snapshot = await graph.aget_state(
        config={"configurable": {"thread_id": thread_id}}
    )
    state_values = getattr(state_snapshot, "values", None) or {}
    return ReviewState.model_validate(state_values)


@app.post("/run")
async def run_review(req: RunRequest):
    logger.info(
        "api.run_review start owner=%s repo=%s pr=%s",
        req.owner,
        req.repo,
        req.pr_number,
    )
    thread_id = req.thread_id or f"{req.owner}/{req.repo}#{req.pr_number}"
    try:
        if graph is None:
            raise RuntimeError("Graph is not initialized")

        previous_node_calls_count = 0
        try:
            state_snapshot = await graph.aget_state(
                config={"configurable": {"thread_id": thread_id}}
            )
            state_values = getattr(state_snapshot, "values", None)
            previous_node_calls_count = get_node_calls_count(state_values)
        except Exception:
            previous_node_calls_count = 0

        init = ReviewState(
            owner=req.owner,
            repo=req.repo,
            pr_number=req.pr_number,
            node_calls=[],
        )
        final_state_dict = await graph.ainvoke(
            init,
            config={
                "recursion_limit": max(1, settings.graph_recursion_limit),
                "configurable": {"thread_id": thread_id},
            },
        )
        interrupts = get_interrupts(final_state_dict)
        final_state = await load_state_for_thread(thread_id)
        current_run_node_calls = final_state.node_calls[previous_node_calls_count:]
        logger.info(
            "api.run_review done findings=%s tool_runs=%s has_comment=%s interrupted=%s",
            len(final_state.findings),
            len(final_state.tool_runs),
            bool(final_state.final_comment),
            bool(interrupts),
        )
        return {
            "ok": True,
            "requires_human_review": bool(interrupts),
            "final_comment": final_state.final_comment,
            "comment_approved": final_state.comment_approved,
            "next_action": (
                "POST /run/decision with thread_id + approve(true/false) + optional edited_comment"
                if interrupts
                else None
            ),
            "findings_count": len(final_state.findings),
            "findings": [f.model_dump() for f in final_state.findings],
            "tool_runs": [tr.model_dump() for tr in final_state.tool_runs],
            "node_calls": current_run_node_calls,
            "node_calls_history": final_state.node_calls,
            "thread_id": thread_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "api.run_review failed owner=%s repo=%s pr=%s error=%s",
            req.owner,
            req.repo,
            req.pr_number,
            str(exc),
        )
        raise HTTPException(status_code=500, detail=f"review_failed: {exc}") from exc


@app.post("/run/decision")
async def run_review_decision(req: RunDecisionRequest):
    logger.info(
        "api.run_review_decision start thread_id=%s approve=%s",
        req.thread_id,
        req.approve,
    )
    try:
        if graph is None:
            raise RuntimeError("Graph is not initialized")

        previous_state = await load_state_for_thread(req.thread_id)
        previous_node_calls_count = len(previous_state.node_calls)
        final_state_dict = await graph.ainvoke(
            Command(
                resume={
                    "ok": req.approve,
                    "comment": req.edited_comment,
                }
            ),
            config={
                "recursion_limit": max(1, settings.graph_recursion_limit),
                "configurable": {"thread_id": req.thread_id},
            },
        )
        interrupts = get_interrupts(final_state_dict)
        final_state = await load_state_for_thread(req.thread_id)
        current_run_node_calls = final_state.node_calls[previous_node_calls_count:]
        logger.info(
            "api.run_review_decision done findings=%s posted=%s interrupted=%s",
            len(final_state.findings),
            any(
                tr.tool == "github" and tr.action == "comment" and tr.ok
                for tr in final_state.tool_runs
            ),
            bool(interrupts),
        )
        return {
            "ok": True,
            "requires_human_review": bool(interrupts),
            "final_comment": final_state.final_comment,
            "comment_approved": final_state.comment_approved,
            "findings_count": len(final_state.findings),
            "findings": [f.model_dump() for f in final_state.findings],
            "tool_runs": [tr.model_dump() for tr in final_state.tool_runs],
            "node_calls": current_run_node_calls,
            "node_calls_history": final_state.node_calls,
            "thread_id": req.thread_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "api.run_review_decision failed thread_id=%s error=%s",
            req.thread_id,
            str(exc),
        )
        raise HTTPException(
            status_code=500, detail=f"review_decision_failed: {exc}"
        ) from exc


@app.get("/graph")
async def graph_png():
    try:
        png_bytes = render_graph_png(xray=True)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.graph_png failed error=%s", str(exc))
        raise HTTPException(
            status_code=500, detail=f"graph_render_failed: {exc}"
        ) from exc
