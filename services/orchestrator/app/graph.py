from __future__ import annotations
from langgraph.graph import StateGraph, END
from .schema import ReviewState
from .llm.bedrock import BedrockLLM
from .tools.github_mcp import GitHubMCP
from .tools.ci_mcp import CIMCP
from .tools.security_mcp import SecurityMCP
from .agents.triage import triage_prompt
from .agents.code_review import code_review_prompt, parse_findings
from .agents.security import security_prompt, parse_security_findings
from .ci_findings import build_ci_findings
import os

GITHUB_MCP_URL = os.getenv("MCP_GITHUB_URL", "http://mcp_github:7001")

bedrock = BedrockLLM()
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


async def run_ci_tools(state: ReviewState) -> ReviewState:
    repo_url = f"https://github.com/{state.owner}/{state.repo}.git"
    ref = f"refs/pull/{state.pr_number}/head"
    tr = await ci.run_ci(repo_url=repo_url, ref=ref)

    # Build the payload expected by build_ci_findings()
    payload = {
        "ok": tr.ok,
        "summary": tr.meta.get("summary", {}),
        "stdout": tr.stdout or "",
        "stderr": tr.stderr or "",
    }

    ci_findings = build_ci_findings(payload)
    state.findings.extend(ci_findings)
    state.tool_runs.append(tr)
    return state


async def run_security_tools(state: ReviewState) -> ReviewState:
    repo_url = f"https://github.com/{state.owner}/{state.repo}.git"
    ref = f"refs/pull/{state.pr_number}/head"
    tr = await sec.run_scans(repo_url=repo_url, ref=ref)
    state.tool_runs.append(tr)
    return state


async def triage_agent(state: ReviewState) -> ReviewState:
    txt = bedrock.invoke_text(triage_prompt(state))
    # optional: store triage as a LOW finding for transparency
    state.findings.append(
        {
            "type": "CODE_QUALITY",
            "severity": "LOW",
            "title": "PR summary (triage)",
            "details": txt[:2000],
        }
    )
    return state


async def code_review_agent(state: ReviewState) -> ReviewState:
    txt = bedrock.invoke_text(code_review_prompt(state))
    state.findings.extend(parse_findings(txt))
    return state


async def security_agent(state: ReviewState) -> ReviewState:
    sec_stdout = None
    for tr in reversed(state.tool_runs):
        if tr.tool == "security" and tr.action == "scan":
            sec_stdout = tr.stdout
            break
    txt = bedrock.invoke_text(security_prompt(state, sec_stdout))
    state.findings.extend(parse_security_findings(txt))
    return state


def compose_comment_prompt(state: ReviewState) -> str:
    tool_summary = "\n".join(
        f"- {tr.tool}/{tr.action}: {'✅' if tr.ok else '❌'}" for tr in state.tool_runs
    )
    findings = [
        f.model_dump() if hasattr(f, "model_dump") else f for f in state.findings[:20]
    ]

    return f"""
Write a GitHub PR review comment in Markdown.

Include:
1) PR summary (2-4 bullets)
2) Checks run:
{tool_summary if tool_summary else "- (none)"}

3) Findings grouped by severity (CRITICAL->LOW). Each item:
- Type, Severity
- File/line if available
- What is wrong
- Concrete recommendation

Use ONLY these findings as ground truth (do not invent):
{findings}

Be concise and actionable.
""".strip()


async def rank_findings(state: ReviewState) -> ReviewState:
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    state.findings.sort(key=lambda f: order.get(f.severity, 99))
    return state


async def compose_comment(state: ReviewState) -> ReviewState:
    state.final_comment = bedrock.invoke_text(compose_comment_prompt(state))
    return state


def conclude(state: ReviewState) -> str:
    severities = [f.severity for f in state.findings]
    if any(str(s).endswith("CRITICAL") for s in severities):
        return "failure"
    if any(str(s).endswith("HIGH") for s in severities):
        return "failure"
    return "success"


async def post_comment(state: ReviewState) -> ReviewState:
    if state.final_comment:
        tr = await gh.post_comment(
            state.owner, state.repo, state.pr_number, state.final_comment
        )
        state.tool_runs.append(tr)
    return state


from langgraph.graph import StateGraph, END
from .schema import ReviewState

# assumes these node funcs already exist in the same module:
# fetch_pr, run_ci_tools, run_security_tools, triage_agent,
# code_review_agent, security_agent, compose_comment, post_comment


def build_graph():
    g = StateGraph(ReviewState)

    # Nodes
    g.add_node("create_check_run", create_check_run)
    g.add_node("complete_check_run", complete_check_run)
    g.add_node("fetch_pr", fetch_pr)
    g.add_node("run_ci", run_ci_tools)
    g.add_node("run_security", run_security_tools)
    g.add_node("triage", triage_agent)
    g.add_node("code_review", code_review_agent)
    g.add_node("security_review", security_agent)
    g.add_node("rank_findings", rank_findings)
    g.add_node("compose_comment", compose_comment)
    g.add_node("post_comment", post_comment)

    # Entry
    g.set_entry_point("fetch_pr")

    g.add_edge("fetch_pr", "create_check_run")
    g.add_edge("create_check_run", "run_ci")
    g.add_edge("run_ci", "run_security")
    g.add_edge("run_security", "triage")
    g.add_edge("triage", "code_review")
    g.add_edge("code_review", "security_review")
    g.add_edge("security_review", "rank_findings")
    g.add_edge("rank_findings", "compose_comment")
    g.add_edge("compose_comment", "post_comment")
    g.add_edge("post_comment", "complete_check_run")
    g.add_edge("complete_check_run", END)

    return g.compile()
