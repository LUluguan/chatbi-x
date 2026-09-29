# ---- 阶段1: 构建前端 ----
FROM node:22-alpine AS web
WORKDIR /src/web
COPY web/package*.json ./
RUN npm ci --no-fund --no-audit
COPY web/ ./
RUN npm run build

# ---- 阶段2: API + 静态托管 ----
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
# [mcp] 让容器内也能跑 MCP server（python -m app.mcp_server）
RUN pip install --no-cache-dir ".[mcp]"
COPY scripts ./scripts
COPY data/eval ./data/eval
COPY --from=web /src/web/dist ./web/dist

ENV CHATBI_WEB_DIST=/app/web/dist
EXPOSE 8000
# 首次启动生成确定性演示库（已挂载 data 卷时跳过）
CMD ["sh", "-c", "python scripts/make_demo_db.py && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
