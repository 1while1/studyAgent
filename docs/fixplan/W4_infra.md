# W4 工程基础设施改进 — `chore/infra`

> 日期：2026-07-29
> 分支：`chore/infra`

## 目标

补齐项目工程基础设施，为后续协作和 CI 打底。

## 修改清单

### 1. `requirements-dev.txt`（新建）

开发环境额外依赖，与主 `requirements.txt` 分离：
- `playwright>=1.40`（UI 走查脚本专用，不随生产环境安装）
- psutil 已在 `requirements.txt` 中 pin 为运行时依赖，此处不重复

### 2. `.gitattributes`（新建）

统一换行符与文件类型标记：
- `* text=auto` 全局自动换行符转换
- Python / TOML / JS / HTML / CSS / Markdown 标记为 text
- PNG / JPG / GIF 标记为 binary
- `resources/scaffolds/gradle/.gradle/**` 标记 `-text`（构建产物永不提交）

### 3. `.github/workflows/ci.yml`（新建）

GitHub Actions 最低门槛 CI：
- 触发条件：push / PR to `main`
- Python 3.11 on ubuntu-latest
- 步骤：checkout → setup python → install deps → unittest → validate hook（目录存在时运行，`|| true` 防 CI 环境缺数据失败）

## 不在本轮范围

- DevLog / AGENTS.md 文档更新（留给合并时统一处理）
- lock file（后续评估）
