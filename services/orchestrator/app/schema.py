from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any, Annotated
import operator

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
FindingType = Literal[
    "CODE_QUALITY", "BUG_RISK", "SECURITY", "PERFORMANCE", "TESTING", "DOCKER", "CI"
]


class Finding(BaseModel):
    type: FindingType
    severity: Severity
    title: str
    file: Optional[str] = None
    line: Optional[int] = None
    details: str
    recommendation: Optional[str] = None
    evidence: Optional[str] = None


class ToolRun(BaseModel):
    tool: str
    action: str
    ok: bool
    meta: Dict[str, Any] = Field(default_factory=dict)
    stdout: Optional[str] = None
    stderr: Optional[str] = None


class ReviewState(BaseModel):
    owner: str
    repo: str
    pr_number: int

    pr_title: Optional[str] = None
    pr_body: Optional[str] = None
    diff: Optional[str] = None
    files_changed: List[str] = Field(default_factory=list)

    # reducers: multiple parallel updates are merged by concatenation
    tool_runs: Annotated[List[ToolRun], operator.add] = Field(default_factory=list)
    findings: Annotated[List[Finding], operator.add] = Field(default_factory=list)
    node_calls: Annotated[List[str], operator.add] = Field(default_factory=list)

    final_comment: Optional[str] = None
    comment_approved: Optional[bool] = None
    head_sha: Optional[str] = None
    check_run_id: Optional[int] = None
