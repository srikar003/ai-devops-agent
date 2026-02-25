from __future__ import annotations
from fastapi import FastAPI
from pydantic import BaseModel
from .schema import ReviewState
from .graph import build_graph

app = FastAPI(title="AI DevOps Orchestrator")
graph = build_graph()


class RunRequest(BaseModel):
    owner: str
    repo: str
    pr_number: int


@app.post("/run")
async def run_review(req: RunRequest):
    init = ReviewState(owner=req.owner, repo=req.repo, pr_number=req.pr_number)
    final_state_dict = await graph.ainvoke(init)
    final_state = ReviewState.model_validate(final_state_dict)
    return {
        "ok": True,
        "final_comment": final_state.final_comment,
        "findings_count": len(final_state.findings),
        "findings": [f.model_dump() for f in final_state.findings],
        "tool_runs": [tr.model_dump() for tr in final_state.tool_runs],
    }
