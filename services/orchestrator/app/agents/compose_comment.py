from __future__ import annotations
from ..schema import ReviewState
from ..llm.bedrock import BedrockLLM

bedrock = BedrockLLM()


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


async def compose_comment(state: ReviewState) -> ReviewState:
    state.final_comment = bedrock.invoke_text(compose_comment_prompt(state))
    return state
