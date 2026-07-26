# syntax=docker/dockerfile:1
# 前端产物由本地同步脚本构建；镜像不安装 Node.js，也不接触源仓库中的账本数据。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN groupadd --gid 10001 palace \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin palace

COPY deploy/requirements-runtime.txt ./requirements-runtime.txt
RUN pip install --no-cache-dir -r requirements-runtime.txt

COPY src ./src
COPY frontend/dist ./frontend/dist

RUN mkdir -p /data \
    && chown palace:palace /data \
    && chmod -R a+rX /app/frontend/dist

USER palace

EXPOSE 8787

CMD ["uvicorn", "src.palace_api:app", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
