from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import tempfile
import os
import shutil

app = FastAPI(title="MCP Security")


class ScanReq(BaseModel):
    repo_url: str
    ref: str


@app.get("/health")
def health():
    return {"ok": True}


def run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


@app.post("/scan")
def scan(req: ScanReq):
    tmpdir = tempfile.mkdtemp(prefix="repo_")
    stdout_all = []
    stderr_all = []
    ok = True

    try:
        # Clone
        code, out, err = run(["git", "clone", "--depth", "1", req.repo_url, tmpdir])
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {
                "ok": False,
                "stdout": "\n".join(stdout_all),
                "stderr": "\n".join(stderr_all),
            }

        # Fetch PR ref (works for GitHub refs/pull/<n>/head)
        code, out, err = run(["git", "fetch", "origin", req.ref], cwd=tmpdir)
        stdout_all.append(out)
        stderr_all.append(err)
        if code != 0:
            return {
                "ok": False,
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

        # Semgrep scan
        # --config auto uses semgrep registry rules; requires outbound internet
        code, out, err = run(["semgrep", "--config", "auto", "--json"], cwd=tmpdir)
        stdout_all.append(out)
        stderr_all.append(err)

        # semgrep returns non-zero when findings exist; treat as ok=True but report output
        if code not in (0, 1):
            ok = False

        return {
            "ok": ok,
            "stdout": "\n".join(stdout_all),
            "stderr": "\n".join(stderr_all),
        }

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
