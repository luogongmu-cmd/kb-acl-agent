FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV ANONYMIZED_TELEMETRY=False
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 语料不进 git，启动时生成并按部门 ACL 建索引
CMD ["sh", "-c", "python scripts/seed_corpus.py && python ingest.py && uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
