from __future__ import annotations
from contextlib import asynccontextmanager
import inspect
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
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
checkpointContext = None
checkpointSaver = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global graph, checkpointContext, checkpointSaver
    checkpointSaver = None
    checkpointContext = None

    if settings.database_url:
        try:
            checkpointSerializer = JsonPlusSerializer(
                allowed_msgpack_modules=[
                    ("app.schema", "Finding"),
                    ("app.schema", "ToolRun"),
                    ("app.schema", "PatchSuggestion"),
                    ("app.schema", "ReviewState"),
                ]
            )
            checkpointContext = AsyncPostgresSaver.from_conn_string(
                settings.database_url,
                serde=checkpointSerializer,
            )
            checkpointSaver = await checkpointContext.__aenter__()
            if hasattr(checkpointSaver, "asetup"):
                await checkpointSaver.asetup()
            elif hasattr(checkpointSaver, "setup"):
                maybe_setup = checkpointSaver.setup()
                if inspect.isawaitable(maybe_setup):
                    await maybe_setup
            logger.info("checkpoint.postgres enabled")
        except Exception as exc:  # noqa: BLE001
            logger.exception("checkpoint.postgres init failed error=%s", str(exc))
            raise RuntimeError(f"Failed to initialize postgres checkpointer: {exc}") from exc
    else:
        logger.warning("checkpoint.postgres disabled because DATABASE_URL is empty")

    graph = build_graph(checkpointer=checkpointSaver)
    try:
        yield
    finally:
        if checkpointContext is not None:
            await checkpointContext.__aexit__(None, None, None)


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
    init = ReviewState(owner=req.owner, repo=req.repo, pr_number=req.pr_number)
    threadId = req.thread_id or f"{req.owner}/{req.repo}#{req.pr_number}"
    try:
        if graph is None:
            raise RuntimeError("Graph is not initialized")
        final_state_dict = await graph.ainvoke(
            init,
            config={
                "recursion_limit": max(1, settings.graph_recursion_limit),
                "configurable": {"thread_id": threadId},
            },
        )
        final_state = ReviewState.model_validate(final_state_dict)
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
            "node_calls": final_state.node_calls,
            "thread_id": threadId,
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
