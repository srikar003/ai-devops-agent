import json
import shutil
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

app = FastAPI(title="MCP CI")
mcp = FastMCP(name="ci-mcp", stateless_http=True)


class RunReq(BaseModel):
    repo_url: str
    ref: str


def run(cmd: List[str], cwd: str | None = None, timeout: int = 1800) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def detect_pm(repo_dir: str) -> str:
    d = Path(repo_dir)
    if (d / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (d / "yarn.lock").exists():
        return "yarn"
    if (d / "package-lock.json").exists():
        return "npm"
    return "npm"


def scripts(repo_dir: str) -> Dict[str, str]:
    pkg = Path(repo_dir) / "package.json"
    if not pkg.exists():
        return {}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        return data.get("scripts") or {}
    except Exception:
        return {}


def cmd_run_script(pm: str, script: str) -> List[str]:
    if pm == "npm":
        return ["npm", "run", script]
    if pm == "yarn":
        return ["yarn", script]
    return ["pnpm", "run", script]


def is_nx_workspace(repo_dir: str) -> bool:
    d = Path(repo_dir)
    return any((d / f).exists() for f in ["nx.json", "workspace.json", "angular.json"])


def cmd_install(pm: str) -> List[str]:
    if pm == "pnpm":
        return ["pnpm", "install", "--frozen-lockfile"]
    if pm == "yarn":
        return ["yarn", "install", "--frozen-lockfile"]
    return ["npm", "ci"]


def safe_json_load(s: str) -> Optional[dict]:
    try:
        return json.loads(s)
    except Exception:
        return None


def parse_npm_audit(audit_json: dict) -> dict:
    out = {"low": 0, "moderate": 0, "high": 0, "critical": 0, "total": 0}
    meta = (audit_json.get("metadata") or {}).get("vulnerabilities")
    if isinstance(meta, dict):
        out["low"] = int(meta.get("low", 0) or 0)
        out["moderate"] = int(meta.get("moderate", 0) or 0)
        out["high"] = int(meta.get("high", 0) or 0)
        out["critical"] = int(meta.get("critical", 0) or 0)
        out["total"] = out["low"] + out["moderate"] + out["high"] + out["critical"]
        return out

    advisories = audit_json.get("advisories")
    if isinstance(advisories, dict):
        for _, adv in advisories.items():
            sev = str((adv or {}).get("severity", "")).lower()
            if sev in out:
                out[sev] += 1
        out["total"] = out["low"] + out["moderate"] + out["high"] + out["critical"]
        return out
    return out


def looks_like_missing_target(err_text: str) -> bool:
    t = err_text.lower()
    return (
        "cannot find target" in t
        or "target does not exist" in t
        or "not found in project" in t
        or "no tasks were run" in t
        or "does not have a target" in t
    )


def nx_commands() -> List[Tuple[str, List[str]]]:
    return [
        ("nx-lint", ["npx", "nx", "run-many", "-t", "lint", "--all"]),
        ("nx-test", ["npx", "nx", "run-many", "-t", "test", "--all"]),
        ("nx-typecheck", ["npx", "nx", "run-many", "-t", "typecheck", "--all"]),
        ("nx-build", ["npx", "nx", "run-many", "-t", "build", "--all"]),
    ]


def run_ci_impl(repo_url: str, ref: str) -> dict:
    tmpdir = tempfile.mkdtemp(prefix="ci_")
    stdout_all: List[str] = []
    stderr_all: List[str] = []
    steps: List[Dict[str, Any]] = []
    ok = True

    def record_step(name: str, step_ok: bool, extra: dict | None = None):
        nonlocal ok
        if not step_ok:
            ok = False
        entry = {"name": name, "ok": step_ok}
        if extra:
            entry.update(extra)
        steps.append(entry)

    try:
        code, out, err = run(["git", "clone", "--depth", "1", repo_url, tmpdir], timeout=300)
        stdout_all.append(out)
        stderr_all.append(err)
        record_step("git-clone", code == 0, {"exit_code": code})
        if code != 0:
            return {
                "ok": False,
                "summary": {"steps": steps},
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        code, out, err = run(["git", "fetch", "origin", ref], cwd=tmpdir, timeout=300)
        stdout_all.append(out)
        stderr_all.append(err)
        record_step("git-fetch-ref", code == 0, {"exit_code": code, "ref": ref})
        if code != 0:
            return {
                "ok": False,
                "summary": {"steps": steps},
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        code, out, err = run(["git", "checkout", "FETCH_HEAD"], cwd=tmpdir, timeout=120)
        stdout_all.append(out)
        stderr_all.append(err)
        record_step("git-checkout", code == 0, {"exit_code": code})
        if code != 0:
            return {
                "ok": False,
                "summary": {"steps": steps},
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        if not (Path(tmpdir) / "package.json").exists():
            stdout_all.append("\n[ci] No package.json detected; skipping node CI.\n")
            record_step("detect-node-project", True, {"node_project": False})
            return {
                "ok": True,
                "summary": {"package_manager": None, "steps": steps},
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        pm = detect_pm(tmpdir)
        stdout_all.append(f"\n[ci] detected package manager: {pm}\n")
        record_step("detect-node-project", True, {"node_project": True, "package_manager": pm})

        install_cmd = cmd_install(pm)
        stdout_all.append(f"\n[ci] install: {' '.join(install_cmd)}\n")
        code, out, err = run(install_cmd, cwd=tmpdir, timeout=1800)
        stdout_all.append(out)
        stderr_all.append(err)
        record_step("install", code == 0, {"exit_code": code, "cmd": install_cmd})
        if code != 0:
            return {
                "ok": False,
                "summary": {"package_manager": pm, "steps": steps},
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        audit_summary = None
        if pm == "npm":
            stdout_all.append("\n[ci] npm audit (json)\n")
            code, out, err = run(["npm", "audit", "--json"], cwd=tmpdir, timeout=600)
            stdout_all.append(out)
            stderr_all.append(err)
            data = safe_json_load(out) or {}
            audit_summary = parse_npm_audit(data)
            audit_fail = audit_summary["critical"] > 0
            record_step(
                "npm-audit",
                (not audit_fail),
                {
                    "exit_code": code,
                    "vulns": audit_summary,
                    "policy": "fail_on_critical",
                },
            )
            if audit_fail:
                stdout_all.append(
                    f"\n[ci] npm audit policy failed: high={audit_summary['high']} critical={audit_summary['critical']}\n"
                )

        scr = scripts(tmpdir)
        preferred_scripts = [s for s in ["lint", "test", "typecheck"] if s in scr]
        if not preferred_scripts and "build" in scr:
            preferred_scripts = ["build"]

        ran_any_checks = False

        if preferred_scripts:
            for s in preferred_scripts:
                cmd = cmd_run_script(pm, s)
                stdout_all.append(f"\n[ci] script {s}: {' '.join(cmd)}\n")
                code, out, err = run(cmd, cwd=tmpdir, timeout=1800)
                stdout_all.append(out)
                stderr_all.append(err)
                record_step(f"script-{s}", code == 0, {"exit_code": code, "cmd": cmd})
                ran_any_checks = True
                if code != 0:
                    break

        if not ran_any_checks and is_nx_workspace(tmpdir):
            stdout_all.append("\n[ci] Nx workspace detected; running nx run-many fallbacks.\n")
            record_step("nx-detected", True)

            for name, cmd in nx_commands():
                stdout_all.append(f"\n[ci] {name}: {' '.join(cmd)}\n")
                code, out, err = run(cmd, cwd=tmpdir, timeout=2400)
                stdout_all.append(out)
                stderr_all.append(err)

                if code != 0 and looks_like_missing_target(out + "\n" + err):
                    record_step(
                        name,
                        True,
                        {
                            "skipped": True,
                            "reason": "missing_target",
                            "exit_code": code,
                            "cmd": cmd,
                        },
                    )
                    continue

                record_step(name, code == 0, {"exit_code": code, "cmd": cmd})
                ran_any_checks = True
                if code != 0:
                    break

        if not ran_any_checks:
            stdout_all.append(
                "\n[ci] No lint/test/typecheck/build scripts found and no Nx checks ran. Install-only.\n"
            )
            record_step("checks-none", True, {"note": "install_only"})

        summary = {"package_manager": pm, "audit": audit_summary, "steps": steps}
        return {
            "ok": ok,
            "summary": summary,
            "stdout": "\n".join(stdout_all),
            "stderr": "\n".join(stderr_all),
        }
    except subprocess.TimeoutExpired as e:
        stderr_all.append(f"\nTIMEOUT: {e}\n")
        record_step("timeout", False, {"error": str(e)})
        return {
            "ok": False,
            "summary": {"steps": steps},
            "stdout": "\n".join(stdout_all),
            "stderr": "\n".join(stderr_all),
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@mcp.tool(name="ci_run")
def ci_run(repo_url: str, ref: str) -> dict:
    return run_ci_impl(repo_url, ref)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/run")
def run_ci(req: RunReq):
    return run_ci_impl(req.repo_url, req.ref)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/", mcp.streamable_http_app())
