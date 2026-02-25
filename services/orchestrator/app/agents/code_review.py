from __future__ import annotations
from ..schema import ReviewState, Finding
import json

def code_review_prompt(state: ReviewState) -> str:
    return f"""
You are a senior software engineer reviewing a PR.

Return ONLY valid JSON.

Schema:
{{
  "findings": [
    {{
      "type": "CODE_QUALITY | BUG_RISK | PERFORMANCE | TESTING",
      "severity": "LOW | MEDIUM | HIGH | CRITICAL",
      "title": "short title",
      "file": "filename if known or null",
      "line": 0,
      "details": "what is wrong",
      "recommendation": "how to fix"
    }}
  ]
}}

PR Title: {state.pr_title}

Diff:
{state.diff[:12000] if state.diff else ""}
"""


def parse_findings(text: str) -> list[Finding]:
    try:
        data = json.loads(text)
        findings = []
        for f in data.get("findings", []):
            findings.append(Finding(**f))
        return findings
    except Exception:
        return []