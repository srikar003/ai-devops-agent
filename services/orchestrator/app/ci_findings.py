from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .schema import Finding, Severity, FindingType

import re

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _ft(value: str) -> Any:
    """
    Supports FindingType as Enum OR str/Literal.
    """
    try:
        return FindingType(value)  # type: ignore
    except Exception:
        return value


def _sev(value: str) -> Any:
    """
    Supports Severity as Enum OR str/Literal.
    - If Severity is an Enum, Severity(value) works.
    - If Severity is str/Literal, returning value works.
    """
    try:
        return Severity(value)  # type: ignore
    except Exception:
        return value


def _sev_from_audit(high: int, critical: int):
    if critical and critical > 0:
        return _sev("CRITICAL")
    if high and high > 0:
        return _sev("HIGH")
    return _sev("MEDIUM")


def build_ci_findings(ci_payload: Dict[str, Any]) -> List[Finding]:
    """
    Expects CI MCP response shape:
      {
        "ok": bool,
        "summary": {
          "package_manager": "npm|pnpm|yarn",
          "audit": {"low":..,"moderate":..,"high":..,"critical":..,"total":..} | null,
          "steps": [{"name":..., "ok":..., ...}, ...]
        },
        "stdout": str,
        "stderr": str
      }
    """
    findings: List[Finding] = []
    summary = (ci_payload or {}).get("summary") or {}
    steps = summary.get("steps") or []
    audit = summary.get("audit") or None
    pm = summary.get("package_manager")

    # 1) npm audit finding
    if isinstance(audit, dict):
        high = int(audit.get("high") or 0)
        critical = int(audit.get("critical") or 0)
        moderate = int(audit.get("moderate") or 0)
        low = int(audit.get("low") or 0)
        total = int(audit.get("total") or (low + moderate + high + critical))

        if total > 0:
            sev = _sev_from_audit(high=high, critical=critical)

            rec = []
            if pm == "npm":
                rec.append("Run `npm audit fix` and re-run CI.")
                if high > 0 or critical > 0:
                    rec.append(
                        "If needed, run `npm audit fix --force` (may introduce breaking changes)."
                    )
            elif pm == "pnpm":
                rec.append("Run `pnpm audit` and update vulnerable dependencies.")
            elif pm == "yarn":
                rec.append("Run `yarn audit` and update vulnerable dependencies.")

            findings.append(
                Finding(
                    type=_ft("SECURITY"),  # or FindingType.CI if you prefer
                    severity=sev,
                    title=f"Dependency vulnerabilities detected by {pm or 'package manager'} audit",
                    details=(
                        f"Audit summary: total={total}, critical={critical}, high={high}, "
                        f"moderate={moderate}, low={low}."
                    ),
                    recommendation=" ".join(rec) if rec else None,
                    evidence=(ci_payload.get("stdout") or "")[-1500:] or None,
                )
            )

    # 2) Any failed CI steps
    for s in steps:
        name = str(s.get("name") or "unknown-step")
        ok = bool(s.get("ok", False))
        if ok:
            continue

        # choose severity: install failure is critical-ish; test/build failures high
        sev = _sev("HIGH")
        if name in {"git-clone", "git-fetch-ref", "git-checkout", "install"}:
            sev = _sev("CRITICAL")

        cmd = s.get("cmd")
        exit_code = s.get("exit_code")
        cmd_txt = f" Command: {' '.join(cmd)}." if isinstance(cmd, list) else ""

        findings.append(
            Finding(
                type=_ft("CI"),
                severity=sev,
                title=f"CI step failed: {name}",
                details=f"Step `{name}` failed with exit_code={exit_code}.{cmd_txt}",
                recommendation="Inspect CI logs, fix the underlying error, and re-run the pipeline.",
                evidence=(
                    (ci_payload.get("stderr") or "")[-1500:]
                    or (ci_payload.get("stdout") or "")[-1500:]
                )
                or None,
            )
        )

    # Sort: CRITICAL -> LOW
    findings.sort(
        key=lambda f: _SEV_ORDER.get(
            f.severity.value if hasattr(f.severity, "value") else str(f.severity), 99
        )
    )
    return findings
