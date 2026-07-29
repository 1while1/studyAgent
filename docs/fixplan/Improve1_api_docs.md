# 改进1: FastAPI API 文档启用

> 分支：feat/api-docs

## 修改
- `backend/api/middleware.py`：auth_gate 豁免路径显式添加 /docs、/openapi.json、/redoc

## 验证
- 单测 577 绿 + validate SUCCESS + 走查 187 PASS
