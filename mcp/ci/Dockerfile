FROM node:20-slim

WORKDIR /app

# Install git for cloning + python venv
RUN apt-get update && apt-get install -y --no-install-recommends \
    git python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create venv and install FastAPI deps inside it (avoids PEP 668)
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn==0.30.6 \
    pydantic==2.8.2

# Optional: pnpm for repos that use it
RUN npm i -g pnpm@9

COPY . .

EXPOSE 7002
CMD ["/opt/venv/bin/python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7002"]