from __future__ import annotations
from ..schema import ReviewState
from ..llm.bedrock import BedrockLLM

bedrock = BedrockLLM()


def triage_prompt(state: ReviewState) -> str:
    return f"""
You are a PR triage agent.
Goal: understand intent and identify hotspots/risk.

PR Title: {state.pr_title}
PR Description: {state.pr_body}

Changed files (if known):
{chr(10).join(state.files_changed[:50])}

Diff:
{state.diff[:12000] if state.diff else ""}

Return:
- 3-7 bullet summary of what PR does
- list of risky areas/files
- what checks are most important (tests/security/docker)
Keep it concise.
""".strip()


async def triage_agent(state: ReviewState) -> dict:
    txt = bedrock.invoke_text(triage_prompt(state))
    # optional: store triage as a LOW finding for transparency
    new_findings = [
        {
            "type": "CODE_QUALITY",
            "severity": "LOW",
            "title": "PR summary (triage)",
            "details": txt[:2000],
        }
    ]
    return {"findings": new_findings}
