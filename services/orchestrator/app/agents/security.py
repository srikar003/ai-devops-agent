from __future__ import annotations
from ..schema import ReviewState, Finding


def security_prompt(state: ReviewState, security_tool_stdout: str | None) -> str:
    return f"""
You are an application security reviewer.

PR Title: {state.pr_title}

Diff:
{state.diff[:10000] if state.diff else ""}

Security scan output:
{(security_tool_stdout or "")[:12000]}

Return:
- Top security risks in this PR (if any)
- Any dependency issues found
- Concrete remediation guidance

Be careful: if scans show nothing, say so.
""".strip()


def parse_security_findings(text: str) -> list[Finding]:
    # MVP: treat as a single SECURITY finding if anything looks serious.
    lowered = text.lower()
    if any(
        k in lowered
        for k in ["critical", "high", "vulnerability", "cve-", "secret", "injection"]
    ):
        return [
            Finding(
                type="SECURITY",
                severity="HIGH",
                title="Security risks detected",
                details=text.strip()[:3000],
                recommendation="Address the items listed above; verify with scans and add tests.",
            )
        ]
    return [
        Finding(
            type="SECURITY",
            severity="LOW",
            title="No major security issues detected",
            details=(
                text.strip()[:1200]
                if text.strip()
                else "Scans and review did not surface major issues."
            ),
        )
    ]
