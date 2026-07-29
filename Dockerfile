# --- Builder ---
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Runtime ---
FROM python:3.12-slim

# 安全：非 root 用户
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app

# 复制依赖
COPY --from=builder /install /usr/local

# 复制应用代码
COPY . .

# 创建运行时目录
RUN mkdir -p runtime/logs workspaces && \
    chown -R app:app /app

# 切换到非 root 用户
USER app

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 暴露端口
EXPOSE 8765

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/docs')"

# 启动命令
CMD ["python", "-m", "uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8765"]
