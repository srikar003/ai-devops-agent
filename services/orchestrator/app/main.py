from __future__ import annotations
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

app = FastAPI(title="AI DevOps Orchestrator")
graph = build_graph()


class RunRequest(BaseModel):
    owner: str
    repo: str
    pr_number: int


@app.post("/run")
async def run_review(req: RunRequest):
    logger.info(
        "api.run_review start owner=%s repo=%s pr=%s",
        req.owner,
        req.repo,
        req.pr_number,
    )
    init = ReviewState(owner=req.owner, repo=req.repo, pr_number=req.pr_number)
    try:
        final_state_dict = await graph.ainvoke(
            init,
            config={"recursion_limit": max(1, settings.graph_recursion_limit)},
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
