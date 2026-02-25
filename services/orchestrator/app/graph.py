from __future__ import annotations
from langgraph.graph import StateGraph, END
from .schema import ReviewState
from .tools.github_mcp import GitHubMCP
from .tools.ci_mcp import CIMCP
from .tools.security_mcp import SecurityMCP
from .agents.triage import triage_prompt, triage_agent
from .agents.code_review import code_review_agent
from .agents.security import security_agent
from .agents.compose_comment import compose_comment
from .ci_findings import build_ci_findings
import os

# assumes these node funcs already exist in the same module:
# fetch_pr, run_ci_tools, run_security_tools, triage_agent,
# code_review_agent, security_agent, compose_comment, post_comment

GITHUB_MCP_URL = os.getenv("MCP_GITHUB_URL", "http://mcp_github:7001")

gh = GitHubMCP(GITHUB_MCP_URL)
ci = CIMCP()
sec = SecurityMCP()


async def fetch_pr(state: ReviewState) -> ReviewState:
    ctx = await gh.get_pr_context(state.owner, state.repo, state.pr_number)
    state.pr_title = ctx.get("title")
    state.pr_body = ctx.get("body")
    state.diff = ctx.get("diff")
    state.files_changed = ctx.get("files", [])
    state.head_sha = ctx["head_sha"]
    return state


async def create_check_run(state: ReviewState) -> ReviewState:
    if state.head_sha:
        tr = await gh.set_commit_status(
            owner=state.owner,
            repo=state.repo,
            sha=state.head_sha,
            state="pending",
            description="AI DevOps review running…",
        )
        state.tool_runs.append(tr)
    return state


async def complete_check_run(state: ReviewState) -> ReviewState:
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
        state.tool_runs.append(tr)
    return state


async def run_ci_tools(state: ReviewState) -> dict:
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

    # Return ONLY what changed (patch update)
    return {
        "tool_runs": [tr],
        "findings": ci_findings,
        "ci_ok": bool(tr.ok),
        "ci_summary": payload.get("summary", {}),
    }


async def run_security_tools(state: ReviewState) -> dict:
    repo_url = f"https://github.com/{state.owner}/{state.repo}.git"
    ref = f"refs/pull/{state.pr_number}/head"

    tr = await sec.run_scans(repo_url=repo_url, ref=ref)

    # If you later build security findings, add them here too.
    # security_findings = build_security_findings(...)
    # return {"tool_runs": [tr], "findings": security_findings, "security_ok": bool(tr.ok)}

    return {
        "tool_runs": [tr],
        "security_ok": bool(tr.ok),
        "security_meta": tr.meta or {},
    }


async def rank_findings(state: ReviewState) -> ReviewState:
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    state.findings.sort(key=lambda f: order.get(f.severity, 99))
    return state


def conclude(state: ReviewState) -> str:
    severities = [f.severity for f in state.findings]
    if any(str(s).endswith("CRITICAL") for s in severities):
        return "failure"
    if any(str(s).endswith("HIGH") for s in severities):
        return "failure"
    return "success"


async def converge_scans(state: ReviewState) -> ReviewState:
    """Convergence point for parallel scan execution."""
    return {
        "check_run_id": state.check_run_id
    }


async def converge_agents(state: ReviewState) -> ReviewState:
    """Convergence point for parallel agent execution."""
    return {
        "check_run_id": state.check_run_id
    }


async def post_comment(state: ReviewState) -> ReviewState:
    if state.final_comment:
        tr = await gh.post_comment(
            state.owner, state.repo, state.pr_number, state.final_comment
        )
        state.tool_runs.append(tr)
    return state


def build_graph():
    g = StateGraph(ReviewState)

    # Nodes
    g.add_node("create_check_run", create_check_run)
    g.add_node("complete_check_run", complete_check_run)
    g.add_node("fetch_pr", fetch_pr)
    g.add_node("run_ci", run_ci_tools)
    g.add_node("run_security", run_security_tools)
    g.add_node("converge_scans", converge_scans)
    g.add_node("triage", triage_agent)
    g.add_node("code_review", code_review_agent)
    g.add_node("security_review", security_agent)
    g.add_node("converge_agents", converge_agents)
    g.add_node("rank_findings", rank_findings)
    g.add_node("compose_comment", compose_comment)
    g.add_node("post_comment", post_comment)

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
    g.add_edge("converge_agents", "rank_findings")
    g.add_edge("rank_findings", "compose_comment")

    # Conditional: post comment only if findings exist
    g.add_conditional_edges(
        "compose_comment",
        lambda state: "post_comment" if state.findings else "complete_check_run",
    )

    g.add_edge("post_comment", "complete_check_run")
    g.add_edge("complete_check_run", END)

    return g.compile()
