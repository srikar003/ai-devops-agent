from __future__ import annotations
from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import logging
import os
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
            async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpoint_saver:
                await checkpoint_saver.setup()
                logger.info("checkpoint.postgres enabled")
                graph = build_graph(checkpointer=checkpoint_saver)
                yield
        except Exception as exc:  # noqa: BLE001
            logger.exception("checkpoint.postgres init failed error=%s", str(exc))
            raise RuntimeError(f"Failed to initialize postgres checkpointer: {exc}") from exc
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
            if isinstance(state_values, dict):
                previous_node_calls_count = len(state_values.get("node_calls", []) or [])
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
        final_state = ReviewState.model_validate(final_state_dict)
        current_run_node_calls = final_state.node_calls[previous_node_calls_count:]
        logger.info(
            "api.run_review done findings=%s tool_runs=%s has_comment=%s",
            len(final_state.findings),
            len(final_state.tool_runs),
            bool(final_state.final_comment),
        )
        return {
            "ok": True,
            "final_comment": final_state.final_comment,
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


@app.get("/graph")
async def graph_png():
    try:
        png_bytes = render_graph_png(xray=True)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as exc:  # noqa: BLE001
        logger.exception("api.graph_png failed error=%s", str(exc))
        raise HTTPException(status_code=500, detail=f"graph_render_failed: {exc}") from exc
