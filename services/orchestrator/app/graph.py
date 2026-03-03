from __future__ import annotations
import hashlib
import logging
from typing import Literal
from typing import Any
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from .schema import ReviewState, ToolRun
from .graph_guard import build_guarded_node_handler
from .tools.github_mcp import GitHubMCP
from .tools.ci_mcp import CIMCP
from .tools.security_mcp import SecurityMCP
from .agents.triage import triage_agent
from .agents.code_review import code_review_agent
from .agents.security import security_agent
from .agents.compose_comment import compose_comment
from .ci_findings import build_ci_findings

logger = logging.getLogger(__name__)

gh = GitHubMCP()
ci = CIMCP()
sec = SecurityMCP()


def next_after_compose(state: ReviewState) -> Literal["human_review", "complete_check_run"]:
    return "human_review" if state.findings else "complete_check_run"


def next_after_human_review(state: ReviewState) -> Literal["post_comment", "complete_check_run"]:
    return "post_comment" if bool(state.comment_approved and state.final_comment) else "complete_check_run"


async def fetch_pr(state: ReviewState) -> dict:
    logger.info(
        "graph.fetch_pr start owner=%s repo=%s pr=%s",
        state.owner,
        state.repo,
        state.pr_number,
    )
    ctx = await gh.get_pr_context(state.owner, state.repo, state.pr_number)
    if "head_sha" not in ctx:
        logger.error("graph.fetch_pr missing head_sha ctx_keys=%s", sorted(ctx.keys()))
        raise ValueError(
            f"Missing 'head_sha' in GitHub MCP response. keys={sorted(ctx.keys())}"
        )
    pr_title = ctx.get("title")
    pr_body = ctx.get("body")
    diff = ctx.get("diff")
    files_changed = ctx.get("files", [])
    head_sha = ctx["head_sha"]
    logger.info(
        "graph.fetch_pr done title=%s files=%s head_sha=%s",
        (pr_title or "")[:80],
        len(files_changed),
        (head_sha or "")[:7],
    )
    return {
        "pr_title": pr_title,
        "pr_body": pr_body,
        "diff": diff,
        "files_changed": files_changed,
        "head_sha": head_sha,
    }


async def create_check_run(state: ReviewState) -> dict:
    logger.info(
        "graph.create_check_run start head_sha_present=%s", bool(state.head_sha)
    )
    if state.head_sha:
        tr = await gh.set_commit_status(
            owner=state.owner,
            repo=state.repo,
            sha=state.head_sha,
            state="pending",
            description="AI DevOps review running…",
        )
        logger.info("graph.create_check_run status_pending ok=%s", tr.ok)
        return {"tool_runs": [tr]}
    return {}


async def complete_check_run(state: ReviewState) -> dict:
    logger.info("graph.complete_check_run start findings=%s", len(state.findings))
    if state.head_sha:
        sev = [str(f.severity) for f in state.findings]
        final_state = "success"
        if any("CRITICAL" in s for s in sev) or any("HIGH" in s for s in sev):
            final_state = "failure"

        tr = await gh.set_commit_status(
            owner=state.owner,
            repo=state.repo,
            sha=state.head_sha,
            state=final_state,
            description=f"AI DevOps review {final_state}. Findings={len(state.findings)}",
        )
        logger.info("graph.complete_check_run final_state=%s ok=%s", final_state, tr.ok)
        return {"tool_runs": [tr]}
    return {}


async def run_ci_tools(state: ReviewState) -> dict:
    logger.info("graph.run_ci_tools start")
    repo_url = f"https://github.com/{state.owner}/{state.repo}.git"
    ref = f"refs/pull/{state.pr_number}/head"

    tr = await ci.run_ci(repo_url=repo_url, ref=ref)

    payload = {
        "ok": tr.ok,
        "summary": tr.meta.get("summary", {}),
        "stdout": tr.stdout or "",
        "stderr": tr.stderr or "",
    }

    ci_findings = build_ci_findings(payload)
    logger.info(
        "graph.run_ci_tools done ci_ok=%s ci_findings=%s", tr.ok, len(ci_findings)
    )

    # Return ONLY what changed (patch update)
    return {
        "tool_runs": [tr],
        "findings": ci_findings,
    }


async def run_security_tools(state: ReviewState) -> dict:
    logger.info("graph.run_security_tools start")
    repo_url = f"https://github.com/{state.owner}/{state.repo}.git"
    ref = f"refs/pull/{state.pr_number}/head"

    tr = await sec.run_scans(repo_url=repo_url, ref=ref)
    logger.info("graph.run_security_tools done security_ok=%s", tr.ok)

    # If you later build security findings, add them here too.
    # security_findings = build_security_findings(...)
    # return {"tool_runs": [tr], "findings": security_findings, "security_ok": bool(tr.ok)}

    return {"tool_runs": [tr]}


async def converge_scans(state: ReviewState) -> dict:
    """Convergence point for parallel scan execution."""
    logger.info("graph.converge_scans")
    return {}


async def converge_agents(state: ReviewState) -> dict:
    """Convergence point for parallel agent execution."""
    logger.info("graph.converge_agents")
    return {}


async def post_comment(state: ReviewState) -> dict:
    logger.info("graph.post_comment start has_comment=%s", bool(state.final_comment))
    if state.final_comment:
        source = f"{state.owner}/{state.repo}#{state.pr_number}:{state.head_sha or ''}:{state.final_comment}"
        idempotency_key = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
        try:
            tr = await gh.post_comment(
                state.owner,
                state.repo,
                state.pr_number,
                state.final_comment,
                idempotency_key=idempotency_key,
            )
            logger.info("graph.post_comment done ok=%s", tr.ok)
            return {"tool_runs": [tr]}
        except Exception as exc:  # noqa: BLE001
            logger.exception("graph.post_comment failed error=%s", str(exc))
            return {
                "tool_runs": [
                    ToolRun(
                        tool="github",
                        action="comment",
                        ok=False,
                        meta={"error": "github_post_comment_failed"},
                        stderr=str(exc),
                    )
                ]
            }
    return {}


async def human_review(state: ReviewState) -> dict:
    logger.info(
        "graph.human_review start findings=%s has_comment=%s",
        len(state.findings),
        bool(state.final_comment),
    )
    if not state.final_comment:
        logger.info("graph.human_review skipped because final_comment is empty")
        return {"comment_approved": False}

    decision = interrupt(
        {
            "type": "human_comment_review",
            "owner": state.owner,
            "repo": state.repo,
            "pr_number": state.pr_number,
            "final_comment": state.final_comment,
            "prompt": "Review the comment. Approve to post, or reject to skip posting.",
            "resume_schema": {
                "ok": "bool (true = post comment, false = skip comment)",
                "comment": "optional string, edited comment to post when ok=true",
            },
        }
    )
    if not isinstance(decision, dict):
        raise TypeError(
            f"human_review interrupt resume payload must be dict, got {type(decision).__name__}"
        )
    approved = bool(decision.get("ok", False))
    edited_comment = decision.get("comment")
    updated_comment = (
        edited_comment
        if isinstance(edited_comment, str) and edited_comment.strip()
        else state.final_comment
    )
    logger.info(
        "graph.human_review done approved=%s edited=%s",
        approved,
        bool(isinstance(edited_comment, str) and edited_comment.strip()),
    )
    return {
        "comment_approved": approved,
        "final_comment": updated_comment,
    }


def build_graph(checkpointer: Any | None = None):
    g = StateGraph(ReviewState)

    # Nodes
    nodes = {
        "create_check_run": create_check_run,
        "complete_check_run": complete_check_run,
        "fetch_pr": fetch_pr,
        "run_ci": run_ci_tools,
        "run_security": run_security_tools,
        "converge_scans": converge_scans,
        "triage": triage_agent,
        "code_review": code_review_agent,
        "security_review": security_agent,
        "converge_agents": converge_agents,
        "compose_comment": compose_comment,
        "human_review": human_review,
        "post_comment": post_comment,
    }
    for node_name, node_callable in nodes.items():
        g.add_node(node_name, build_guarded_node_handler(node_name, node_callable))

    # Entry
    g.set_entry_point("fetch_pr")

    # Sequential: fetch and create check
    g.add_edge("fetch_pr", "create_check_run")

    # Parallel: run CI and security scans concurrently
    g.add_edge("create_check_run", "run_ci")
    g.add_edge("create_check_run", "run_security")
    g.add_edge("run_ci", "converge_scans")
    g.add_edge("run_security", "converge_scans")

    # Parallel: run all three agents concurrently
    g.add_edge("converge_scans", "triage")
    g.add_edge("converge_scans", "code_review")
    g.add_edge("converge_scans", "security_review")
    g.add_edge("triage", "converge_agents")
    g.add_edge("code_review", "converge_agents")
    g.add_edge("security_review", "converge_agents")

    # Sequential: process and post results
    g.add_edge("converge_agents", "compose_comment")

    # Conditional: request human review only if findings exist
    g.add_conditional_edges("compose_comment", next_after_compose)
    g.add_conditional_edges("human_review", next_after_human_review)

    g.add_edge("post_comment", "complete_check_run")
    g.add_edge("complete_check_run", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


def render_graph_png(xray: bool = True) -> bytes:
    graph = build_graph()
    return graph.get_graph(xray=xray).draw_mermaid_png()
