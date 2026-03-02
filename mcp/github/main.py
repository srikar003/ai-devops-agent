import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from config import settings

app = FastAPI(title="MCP GitHub")
mcp = FastMCP(name="github-mcp", stateless_http=True)

def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_token() -> None:
    if not settings.github_token:
        raise HTTPException(
            status_code=500, detail="GITHUB_TOKEN not set for mcp/github"
        )


def _is_transient_http_status(code: int) -> bool:
    return code in settings.github_transient_status_codes


async def _request_with_retry(
    method: str,
    url: str,
    *,
    headers_in: dict[str, str],
    json_body: dict | None = None,
) -> httpx.Response:
    attempts = max(1, settings.github_retry_attempts)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.github_http_timeout_seconds) as client:
                resp = await client.request(
                    method=method,
                    url=url,
                    headers=headers_in,
                    json=json_body,
                )
            if _is_transient_http_status(resp.status_code) and attempt < attempts:
                retry_after = resp.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else (0.5 * (2 ** (attempt - 1)))
                )
                await asyncio.sleep(delay)
                continue
            return resp
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
    if last_exc:
        raise HTTPException(
            status_code=503, detail=f"GitHub request failed after retries: {last_exc}"
        ) from last_exc
    raise HTTPException(status_code=503, detail="GitHub request failed after retries")


class CommentReq(BaseModel):
    owner: str
    repo: str
    pr: int
    body: str
    idempotency_key: str | None = None


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
    # Idempotency: if current top status for this context already matches, skip creating another status.
    combined_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/status"
    combined_resp = await _request_with_retry("GET", combined_url, headers_in=headers())
    if combined_resp.status_code == 200:
        combined_data = combined_resp.json() or {}
        for status_item in combined_data.get("statuses", []):
            if str(status_item.get("context", "")) != context:
                continue
            current_state = str(status_item.get("state", ""))
            current_desc = str(status_item.get("description", "") or "")
            current_target = str(status_item.get("target_url", "") or "")
            if (
                current_state == state
                and current_desc == (description or "")
                and current_target == (target_url or "")
            ):
                return {"ok": True, "deduped": True}
            break

    url = f"https://api.github.com/repos/{owner}/{repo}/statuses/{sha}"
    payload = {"state": state, "context": context, "description": description or ""}
    if target_url:
        payload["target_url"] = target_url

    r = await _request_with_retry("POST", url, headers_in=headers(), json_body=payload)
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return {"ok": True, "deduped": False}


async def do_get_pr_context(owner: str, repo: str, pr: int) -> dict:
    ensure_token()
    pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}"
    pr_resp = await _request_with_retry("GET", pr_url, headers_in=headers())
    if pr_resp.status_code != 200:
        raise HTTPException(status_code=pr_resp.status_code, detail=pr_resp.text)
    pr_data = pr_resp.json()
    head_sha = (pr_data.get("head") or {}).get("sha")

    files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}/files"
    files_resp = await _request_with_retry("GET", files_url, headers_in=headers())
    if files_resp.status_code != 200:
        raise HTTPException(status_code=files_resp.status_code, detail=files_resp.text)
    files_data = files_resp.json()
    files = [f.get("filename") for f in files_data if f.get("filename")]

    diff_headers = dict(headers())
    diff_headers["Accept"] = "application/vnd.github.v3.diff"
    diff_resp = await _request_with_retry("GET", pr_url, headers_in=diff_headers)
    if diff_resp.status_code != 200:
        raise HTTPException(status_code=diff_resp.status_code, detail=diff_resp.text)

    return {
        "title": pr_data.get("title"),
        "body": pr_data.get("body"),
        "diff": diff_resp.text,
        "files": files,
        "head_sha": head_sha,
    }


def _idempotency_marker(idempotency_key: str) -> str:
    return f"<!-- ai-devops-idempotency:{idempotency_key} -->"


async def do_post_comment(
    owner: str,
    repo: str,
    pr: int,
    body: str,
    idempotency_key: str | None = None,
) -> dict:
    ensure_token()
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr}/comments"
    final_body = body
    marker = ""
    if idempotency_key:
        marker = _idempotency_marker(idempotency_key)
        if marker not in final_body:
            final_body = f"{body.rstrip()}\n\n{marker}"

        comments_resp = await _request_with_retry("GET", url, headers_in=headers())
        if comments_resp.status_code == 200:
            comments_data = comments_resp.json() or []
            for c in reversed(comments_data[-50:]):
                existing_body = str(c.get("body", "") or "")
                if marker and marker in existing_body:
                    return {"ok": True, "id": c.get("id"), "deduped": True}

    r = await _request_with_retry(
        "POST", url, headers_in=headers(), json_body={"body": final_body}
    )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return {"ok": True, "id": r.json().get("id"), "deduped": False}


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

    if req.check_run_id:
        r = await _request_with_retry(
            "PATCH",
            f"{base}/{req.check_run_id}",
            headers_in=headers(),
            json_body=payload,
        )
    else:
        r = await _request_with_retry(
            "POST",
            base,
            headers_in=headers(),
            json_body=payload,
        )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=r.status_code, detail=r.text)
    data = r.json()
    return {"ok": True, "check_run_id": data.get("id")}


@mcp.tool(name="github_get_pr_context")
async def github_get_pr_context(owner: str, repo: str, pr: int) -> dict:
    return await do_get_pr_context(owner, repo, pr)


@mcp.tool(name="github_post_comment")
async def github_post_comment(
    owner: str,
    repo: str,
    pr: int,
    body: str,
    idempotency_key: str | None = None,
) -> dict:
    return await do_post_comment(owner, repo, pr, body, idempotency_key=idempotency_key)


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
    return await do_post_comment(
        req.owner,
        req.repo,
        req.pr,
        req.body,
        idempotency_key=req.idempotency_key,
    )


@app.post("/check-run")
async def upsert_check_run(req: CheckRunReq):
    return await do_upsert_check_run(req)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/", mcp.streamable_http_app())
