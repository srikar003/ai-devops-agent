import shutil
import subprocess
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

app = FastAPI(title="MCP Security")
mcp = FastMCP(name="security-mcp", stateless_http=True)


class ScanReq(BaseModel):
    repo_url: str
    ref: str


def run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def scan_impl(repo_url: str, ref: str) -> dict:
    tmpdir = tempfile.mkdtemp(prefix="repo_")
    stdout_all: list[str] = []
    stderr_all: list[str] = []
    ok = True

    try:
        code, out, err = run(["git", "clone", "--depth", "1", repo_url, tmpdir])
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {"ok": False, "stdout": "\n".join(stdout_all), "stderr": "\n".join(stderr_all)}

        code, out, err = run(["git", "fetch", "origin", ref], cwd=tmpdir)
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {"ok": False, "stdout": "\n".join(stdout_all), "stderr": "\n".join(stderr_all)}

        code, out, err = run(["git", "checkout", "FETCH_HEAD"], cwd=tmpdir)
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {"ok": False, "stdout": "\n".join(stdout_all), "stderr": "\n".join(stderr_all)}

        code, out, err = run(["semgrep", "--config", "auto", "--json"], cwd=tmpdir)
        stdout_all.append(out)
        stderr_all.append(err)
        if code not in (0, 1):
            ok = False

        return {"ok": ok, "stdout": "\n".join(stdout_all), "stderr": "\n".join(stderr_all)}
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
app.mount("/mcp/", mcp.streamable_http_app())
