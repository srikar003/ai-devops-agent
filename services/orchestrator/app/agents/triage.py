from __future__ import annotations
from ..schema import ReviewState


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
