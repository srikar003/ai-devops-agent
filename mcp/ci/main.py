from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class RunReq(BaseModel):
    repo_url: str
    ref: str

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/run")
def run(req: RunReq):
    # MVP stub: later you’ll clone repo + run pytest/ruff
    return {"ok": True, "stdout": f"CI stub for {req.repo_url} @ {req.ref}", "stderr": ""}