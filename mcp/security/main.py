import os
import shutil
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from config import settings

app = FastAPI(title="MCP Security")
mcp = FastMCP(name="security-mcp", stateless_http=True)


class ScanReq(BaseModel):
    repo_url: str
    ref: str


def run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=settings.security_cmd_timeout_seconds,
    )
    return p.returncode, p.stdout, p.stderr


def run_with_retries(
    cmd: list[str], cwd: str | None = None
) -> tuple[int, str, str, int]:
    out_all: list[str] = []
    err_all: list[str] = []
    last_code = 1
    for attempt in range(1, max(1, settings.security_retry_attempts) + 1):
        code, out, err = run(cmd, cwd=cwd)
        out_all.append(out)
        err_all.append(err)
        last_code = code
        if code == 0:
            return code, "\n".join(out_all), "\n".join(err_all), attempt
        if attempt < max(1, settings.security_retry_attempts):
            time.sleep(0.5 * (2 ** (attempt - 1)))
    return (
        last_code,
        "\n".join(out_all),
        "\n".join(err_all),
        max(1, settings.security_retry_attempts),
    )


def scan_impl(repo_url: str, ref: str) -> dict:
    tmpdir = tempfile.mkdtemp(prefix="repo_")
    stdout_all: list[str] = []
    stderr_all: list[str] = []
    ok = True

    try:
        clone_attempts = 0
        clone_out_all: list[str] = []
        clone_err_all: list[str] = []
        for clone_attempts in range(1, max(1, settings.security_retry_attempts) + 1):
            for p in os.listdir(tmpdir):
                full = os.path.join(tmpdir, p)
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    try:
                        os.remove(full)
                    except OSError:
                        pass
            code, out, err = run(["git", "clone", "--depth", "1", repo_url, tmpdir])
            clone_out_all.append(out)
            clone_err_all.append(err)
            if code == 0:
                break
            if clone_attempts < max(1, settings.security_retry_attempts):
                time.sleep(0.5 * (2 ** (clone_attempts - 1)))
        out = "\n".join(clone_out_all)
        err = "\n".join(clone_err_all)
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {
                "ok": False,
                "summary": {"git_clone_attempts": clone_attempts},
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        code, out, err, fetch_attempts = run_with_retries(
            ["git", "fetch", "origin", ref], cwd=tmpdir
        )
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {
                "ok": False,
                "summary": {
                    "git_clone_attempts": clone_attempts,
                    "git_fetch_attempts": fetch_attempts,
                },
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        code, out, err = run(["git", "checkout", "FETCH_HEAD"], cwd=tmpdir)
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {
                "ok": False,
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        code, out, err = run(["semgrep", "--config", "auto", "--json"], cwd=tmpdir)
        stdout_all.append(out)
        stderr_all.append(err)
        if code not in (0, 1):
            ok = False

        return {
            "ok": ok,
            "summary": {
                "git_clone_attempts": clone_attempts,
                "git_fetch_attempts": fetch_attempts,
            },
            "stdout": "\n".join(stdout_all),
            "stderr": "\n".join(stderr_all),
        }
    except subprocess.TimeoutExpired as e:
        stderr_all.append(f"\nTIMEOUT: {e}\n")
        return {
            "ok": False,
            "summary": {"error": "timeout"},
            "stdout": "\n".join(stdout_all),
            "stderr": "\n".join(stderr_all),
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@mcp.tool(name="security_scan")
def security_scan(repo_url: str, ref: str) -> dict:
    return scan_impl(repo_url, ref)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/scan")
def scan(req: ScanReq):
    return scan_impl(req.repo_url, req.ref)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/", mcp.streamable_http_app())
