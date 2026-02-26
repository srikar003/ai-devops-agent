FROM python:3.11-slim

WORKDIR /app

# Install git + curl + semgrep deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install FastAPI + semgrep
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    pydantic==2.8.2 \
    "mcp>=1.12,<2" \
    semgrep==1.89.0

COPY . .

EXPOSE 7003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7003"]
