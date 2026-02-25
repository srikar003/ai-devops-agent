from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import httpx

app = FastAPI(title="MCP GitHub")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    # You can still start the server, but calls will fail with clear error.
    pass

HEADERS = lambda: {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class CommentReq(BaseModel):
    owner: str
    repo: str
    pr: int
    body: str


class CheckRunReq(BaseModel):
    owner: str
    repo: str
    head_sha: str

    name: str = "ai-devops-agent"
    status: str = "in_progress"  # in_progress | completed
    conclusion: str | None = (
        None  # success | failure | neutral | cancelled | skipped | timed_out | action_required
    )

    title: str | None = None
    summary: str | None = None
    text: str | None = None

    # optional: update existing check run
    check_run_id: int | None = None


class CommitStatusReq(BaseModel):
    owner: str
    repo: str
    sha: str
    state: str  # error | failure | pending | success
    context: str = "ai-devops-agent"
    description: str | None = None
    target_url: str | None = None


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/status")
async def set_commit_status(req: CommitStatusReq):
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500, detail="GITHUB_TOKEN not set for mcp/github"
        )

    url = f"https://api.github.com/repos/{req.owner}/{req.repo}/statuses/{req.sha}"
    payload = {
        "state": req.state,
        "context": req.context,
        "description": req.description or "",
    }
    if req.target_url:
        payload["target_url"] = req.target_url

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=HEADERS(), json=payload)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return {"ok": True}


@app.get("/pr")
async def get_pr(owner: str, repo: str, pr: int):
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500, detail="GITHUB_TOKEN not set for mcp/github"
        )

    async with httpx.AsyncClient(timeout=60) as client:
        # PR info
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}"
        pr_resp = await client.get(pr_url, headers=HEADERS())
        if pr_resp.status_code != 200:
            raise HTTPException(status_code=pr_resp.status_code, detail=pr_resp.text)
        pr_data = pr_resp.json()
        head_sha = (pr_data.get("head") or {}).get("sha")

        # Files changed
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}/files"
        files_resp = await client.get(files_url, headers=HEADERS())
        if files_resp.status_code != 200:
            raise HTTPException(
                status_code=files_resp.status_code, detail=files_resp.text
            )
        files_data = files_resp.json()
        files = [f.get("filename") for f in files_data if f.get("filename")]

        # Diff (unified)
        diff_headers = dict(HEADERS())
        diff_headers["Accept"] = "application/vnd.github.v3.diff"
        diff_resp = await client.get(pr_url, headers=diff_headers)
        if diff_resp.status_code != 200:
            raise HTTPException(
                status_code=diff_resp.status_code, detail=diff_resp.text
            )

        return {
            "title": pr_data.get("title"),
            "body": pr_data.get("body"),
            "diff": diff_resp.text,
            "files": files,
            "head_sha": head_sha,
        }


@app.post("/comment")
async def post_comment(req: CommentReq):
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500, detail="GITHUB_TOKEN not set for mcp/github"
        )

    url = (
        f"https://api.github.com/repos/{req.owner}/{req.repo}/issues/{req.pr}/comments"
    )
    payload = {"body": req.body}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=HEADERS(), json=payload)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return {"ok": True, "id": r.json().get("id")}


@app.post("/check-run")
async def upsert_check_run(req: CheckRunReq):
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500, detail="GITHUB_TOKEN not set for mcp/github"
        )

    base = f"https://api.github.com/repos/{req.owner}/{req.repo}/check-runs"

    payload = {
        "name": req.name,
        "head_sha": req.head_sha,
        "status": req.status,
        "output": {
            "title": req.title or req.name,
            "summary": req.summary or "",
            "text": req.text or "",
        },
    }

    # Only include conclusion when completed (GitHub requires this)
    if req.status == "completed":
        payload["conclusion"] = req.conclusion or "neutral"

    async with httpx.AsyncClient(timeout=60) as client:
        if req.check_run_id:
            url = f"{base}/{req.check_run_id}"
            r = await client.patch(url, headers=HEADERS(), json=payload)
        else:
            url = base
            r = await client.post(url, headers=HEADERS(), json=payload)

        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)

        data = r.json()
        return {"ok": True, "check_run_id": data.get("id")}
