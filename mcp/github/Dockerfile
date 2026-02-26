FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    httpx>=0.28.0 \
    "mcp>=1.12,<2"

COPY . .

EXPOSE 7001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7001"]
