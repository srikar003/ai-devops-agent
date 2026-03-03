from __future__ import annotations

from ..llm.bedrock import BedrockLLM
from ..schema import ReviewState

bedrock = BedrockLLM()


def compose_comment_prompt(state: ReviewState) -> str:
    tool_summary = "\n".join(
        f"- {tool_run.tool}/{tool_run.action}: {'OK' if tool_run.ok else 'FAIL'}"
        for tool_run in state.tool_runs
    )
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    ordered_findings = sorted(
        state.findings,
        key=lambda finding: severity_order.get(str(finding.severity), 99),
    )
    findings = [
        finding.model_dump() if hasattr(finding, "model_dump") else finding
        for finding in ordered_findings[:20]
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


async def compose_comment(state: ReviewState) -> dict:
    final_comment = bedrock.invoke_text(compose_comment_prompt(state))
    return {"final_comment": final_comment}
