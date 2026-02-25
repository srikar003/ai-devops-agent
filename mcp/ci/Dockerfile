FROM python:3.11-slim

WORKDIR /app

# Install git (needed to clone repos) + any tools you plan to run
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7002"]