import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

app = FastAPI(title="MCP GitHub")
mcp = FastMCP(name="github-mcp", stateless_http=True)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_token() -> None:
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN not set for mcp/github")


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
    status: str = "in_progress"
    conclusion: str | None = None
    title: str | None = None
    summary: str | None = None
    text: str | None = None
    check_run_id: int | None = None


class CommitStatusReq(BaseModel):
    owner: str
    repo: str
    sha: str
    state: str
    context: str = "ai-devops-agent"
    description: str | None = None
    target_url: str | None = None


async def do_set_commit_status(
    owner: str,
    repo: str,
    sha: str,
    state: str,
    context: str = "ai-devops-agent",
    description: str | None = None,
    target_url: str | None = None,
) -> dict:
    ensure_token()
    url = f"https://api.github.com/repos/{owner}/{repo}/statuses/{sha}"
    payload = {"state": state, "context": context, "description": description or ""}
    if target_url:
        payload["target_url"] = target_url

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers(), json=payload)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return {"ok": True}


async def do_get_pr_context(owner: str, repo: str, pr: int) -> dict:
    ensure_token()
    async with httpx.AsyncClient(timeout=60) as client:
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}"
        pr_resp = await client.get(pr_url, headers=headers())
        if pr_resp.status_code != 200:
            raise HTTPException(status_code=pr_resp.status_code, detail=pr_resp.text)
        pr_data = pr_resp.json()
        head_sha = (pr_data.get("head") or {}).get("sha")

        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}/files"
        files_resp = await client.get(files_url, headers=headers())
        if files_resp.status_code != 200:
            raise HTTPException(status_code=files_resp.status_code, detail=files_resp.text)
        files_data = files_resp.json()
        files = [f.get("filename") for f in files_data if f.get("filename")]

        diff_headers = dict(headers())
        diff_headers["Accept"] = "application/vnd.github.v3.diff"
        diff_resp = await client.get(pr_url, headers=diff_headers)
        if diff_resp.status_code != 200:
            raise HTTPException(status_code=diff_resp.status_code, detail=diff_resp.text)

        return {
            "title": pr_data.get("title"),
            "body": pr_data.get("body"),
            "diff": diff_resp.text,
            "files": files,
            "head_sha": head_sha,
        }


async def do_post_comment(owner: str, repo: str, pr: int, body: str) -> dict:
    ensure_token()
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr}/comments"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers(), json={"body": body})
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return {"ok": True, "id": r.json().get("id")}


async def do_upsert_check_run(req: CheckRunReq) -> dict:
    ensure_token()
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
    if req.status == "completed":
        payload["conclusion"] = req.conclusion or "neutral"

    async with httpx.AsyncClient(timeout=60) as client:
        if req.check_run_id:
            r = await client.patch(f"{base}/{req.check_run_id}", headers=headers(), json=payload)
        else:
            r = await client.post(base, headers=headers(), json=payload)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=r.text)
        data = r.json()
        return {"ok": True, "check_run_id": data.get("id")}


@mcp.tool(name="github_get_pr_context")
async def github_get_pr_context(owner: str, repo: str, pr: int) -> dict:
    return await do_get_pr_context(owner, repo, pr)


@mcp.tool(name="github_post_comment")
async def github_post_comment(owner: str, repo: str, pr: int, body: str) -> dict:
    return await do_post_comment(owner, repo, pr, body)


@mcp.tool(name="github_set_commit_status")
async def github_set_commit_status(
    owner: str,
    repo: str,
    sha: str,
    state: str,
    context: str = "ai-devops-agent",
    description: str | None = None,
    target_url: str | None = None,
) -> dict:
    return await do_set_commit_status(
        owner=owner,
        repo=repo,
        sha=sha,
        state=state,
        context=context,
        description=description,
        target_url=target_url,
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/status")
async def set_commit_status(req: CommitStatusReq):
    return await do_set_commit_status(
        owner=req.owner,
        repo=req.repo,
        sha=req.sha,
        state=req.state,
        context=req.context,
        description=req.description,
        target_url=req.target_url,
    )


@app.get("/pr")
async def get_pr(owner: str, repo: str, pr: int):
    return await do_get_pr_context(owner, repo, pr)


@app.post("/comment")
async def post_comment(req: CommentReq):
    return await do_post_comment(req.owner, req.repo, req.pr, req.body)


@app.post("/check-run")
async def upsert_check_run(req: CheckRunReq):
    return await do_upsert_check_run(req)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/", mcp.streamable_http_app())
