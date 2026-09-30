# ChatBI-X

![CI](https://github.com/LUluguan/chatbi-x/actions/workflows/ci.yml/badge.svg)

评测驱动的 ChatBI / Text2SQL 数据问答 Agent：用自然语言问关系型数据库，Agent 生成 SQL、
执行验证、失败自校正，返回表格结果。**每一个能力都有对应测试与可复现的执行准确率指标。**

## 功能现状（W2 数据与基线）

- **自研 Agent 工具循环**（不依赖 LangChain）：单条 JSON 工具协议
  `get_schema` / `run_sql` / `final`，SQL 执行失败自动带错误信息重试，final 前二次验证。
- **Schema Linking**：中文问题 → 英文表名的桥接方案 = 库内 `schema_comments` 中文注释表
  + CJK 字符 n-gram 相似度排序，只把最相关的表放进模型上下文。
- **只读 SQL 执行器**：SELECT/WITH 白名单、单语句限制、只读连接、progress handler 超时熔断、行数截断。
- **LLM Provider 抽象**：`mock`（离线确定性，测试与零配置演示）/ `openai_compat`
  （DeepSeek、Ollama、vLLM、OpenAI 等任何兼容接口）。
- **评测框架**：执行准确率（结果集 multiset 对比，行序不敏感、浮点 6 位容差、NULL 混合类型可排序），
  按 simple/moderate/challenging 难度分组报告；BIRD 风格数据集（`question + SQL + db_id + difficulty + evidence`）
  全量接入，evidence 知识提示自动注入 prompt。
- **Few-shot 池**：BIRD train 9428 条做示例池，同库示例优先（避免跨库方言干扰与评测集泄漏）。
- **模式对比**：`single_shot`（朴素基线）vs `agent`（工具循环+自校正）一条命令出对比报告。
- **SSE 流式输出**：`POST /api/chat/stream` 实时推送 Agent 执行步骤（查表/执行 SQL/验证），前端打字机式呈现执行过程。
- **图表推荐**：启发式引擎按结果集形态推荐可视化（日期趋势→折线、占比构成→饼图、分类对比→柱状、复杂结构→表格），前端 ECharts 渲染。
- **MCP server**：`python -m app.mcp_server` 把 `list_tables / get_schema / run_sql / ask` 暴露为标准 MCP 工具，可接入 Claude Desktop 等任何 MCP 客户端。
- **Docker 一键部署**：多阶段构建（Node 打包前端 → Python 镜像托管），`docker compose up` 单容器跑通全部。
- **Web 界面**：Vue 3 对话式问答，实时执行过程、SQL 高亮、图表 + 结果表格。

## 快速开始

零配置（mock 模式，无任何 API Key）：

```bash
# 1. 生成演示数据库（首次）
python scripts/make_demo_db.py

# 2. 启动后端
python -m uvicorn app.main:app --port 8000

# 3. 启动前端（另开终端）
cd web && npm install && npm run dev
# 打开 http://localhost:5173
```

接真实模型：复制 `.env.example` 为 `.env`，填入 `CHATBI_LLM_PROVIDER=openai_compat` 与 API Key
（或本地 Ollama 地址）。

Docker（单容器，含前端托管）：

```bash
docker compose up --build
# 打开 http://localhost:8000
```

## 评测

演示集（零依赖自检，mock 应为 100%）：

```bash
python -m app.eval.runner --dataset data/eval/demo_eval.json --db data/demo_ecom.db --provider mock
```

BIRD-dev 全量基线（1534 题 / 11 库，官方阿里云 OSS 源）：

```bash
python scripts/fetch_bird.py          # 下载并解压 dev.zip（346MB）
python -m pip install pyarrow         # 仅转换训练集时需要
curl -L -o data/bird/train.parquet "https://hf-mirror.com/datasets/xu3kev/BIRD-SQL-data-train/resolve/main/data/train-00000-of-00001-fe8894d41b7815be.parquet"
python scripts/make_shots.py          # 生成 9428 条 few-shot 池

# 先用 --limit 控制成本试跑，再全量
python -m app.eval.compare --dataset data/bird/dev.json --datasets-root data/bird \
  --db data/demo_ecom.db --provider openai_compat \
  --shots-file data/eval/bird_train_shots.json --limit 100

# 全量（1534 题两种模式）：去掉 --limit
```

报告含逐题通过情况、预测 SQL 与难度分组，写入 `data/eval/compare_report.json`。

## 测试

```bash
python -m pytest -q          # 后端 56 个测试
```

## 架构

```
问题 ──> Schema Linking（CJK n-gram + 中文注释表，取 Top-K 表）
     ──> Agent 工具循环（get_schema → run_sql → 执行反馈 → … → final）
     ──> 只读执行器（白名单校验 / 超时熔断 / 截断）
     ──> FastAPI (/api/chat) ──> Vue 3 前端
评测: EvalRunner ──> 执行准确率（pred vs gold 结果集对比）
```

## 评测结果

基准组成：BIRD-dev 前 100 题 = **89 题 california_schools + 11 题 financial**（dev.json 按库分组，limit 100 跨到了第二个库）。DeepSeek-Chat，few-shot 池同库优先，evidence 注入。

> **判据修正说明（重要）**：下表 v1–v3 使用了有缺陷的判据——预测与金标都按 50 行截断后
> 比对物理顺序的前 50 行，长结果集（最大 7,806 行）上双向失真。该缺陷由外部评审发现
> （同一道题，正确 SQL 与改写 SQL 分别被判 1.0 和 0.0）。判据已修复为全量比对
> （`eval_max_rows=10万`，命中上限的题带 `truncated` 标记），**修复后的 v4 复测数字见
> `data/eval/compare_report_v4.json`**——引用本表数字前请以 v4 为准。

| 版本 | single_shot（朴素基线） | agent | 关键改动 |
|---|---|---|---|
| v1 | 53.00% | 33.00% | 初版反馈话术诱导模型把探索性宽查询直接定稿（22 题翻车全因如此） |
| v2 | 51.00% | 45.00% | 反馈回显 SQL + 显式检查「结果列恰为答案」；自校正救回 10 题 |
| v3 | 51.00% | 61.00%* | **propose-verify 架构**：naive 生成草案，Agent 只做执行验证与修正 |

\* v3 数字基于有缺陷的判据，保留只为呈现迭代轨迹；结论（propose-verify 显著优于 naive）
有待 v4 复测确认。

v3 分难度：simple 66.10% vs 基线 59.32%；moderate 57.14% vs 40.00%；challenging 样本仅 6 题不计入结论。

核心教训：**Agent 的价值不是「从零探索」，而是「验证与修正」**——让它站在基线答案的肩膀上，
执行反馈自校正才有正收益。完整报告（逐题预测 SQL + 失败分类）见 `data/eval/compare_report_v3.json`。

**关于 Schema Linking 的证据边界**：中文注释桥接只在自带 demo_ecom.db（4 表全中文注释）
上被真实 exercised；BIRD 这两个库 description 为空、表数 ≤4，linking 在该基准上不构成
有效过滤——本基准的准确率数字**不能**作为 linking 价值的证据。多表中文基准 + 消融在路线图中。

## 文档

- [ARCHITECTURE.md](ARCHITECTURE.md) —— 系统总览、Agent 协议规范、安全模型、评测方法学、已知限制
- `docs/求职要点.md` —— 面试准备材料（内部参考）

## 压测（mock provider，测管线本身不含 LLM 延迟）

```
并发=32  总请求=200  成功=200
吞吐 307.7 req/s   p50/p95/max = 99ms / 120ms / 141ms
```

复现: `CHATBI_LLM_PROVIDER=mock python -m uvicorn app.main:app --port 8010` 后运行
`python scripts/load_test.py --base http://127.0.0.1:8010 --concurrency 32 --total 200`

## 路线图

- [x] W1 脚手架：Agent 循环 / 执行器 / Provider / 评测框架 / mini 评测集 / Web 骨架
- [x] W2 数据与基线：BIRD-dev 全量接入 ✓ / few-shot 池（同库优先）✓ / 难度分组报告 ✓ / evidence 注入 ✓ / 模式对比 CLI ✓ / propose-verify 架构（BIRD-100 上 agent 61% vs 基线 51%）✓ / 向量版 linking（待接真实 embedding 源）
- [x] W3 产品化：SSE 流式输出 ✓ / ECharts 图表推荐 ✓ / MCP server ✓ / Docker 一键部署 ✓
- [x] W4 发布：架构文档 ✓ / CI（pytest 双版本矩阵 + 前端构建 + **Docker 构建与启动自检**）✓ / 压测报告 ✓ / 全量 1534 题报告（可选，按需运行 `python -m app.eval.compare` 不带 --limit）

## 致谢与边界

架构参考 [DB-GPT](https://github.com/eosphoros-ai/DB-GPT) 与 [vanna](https://github.com/vanna-ai/vanna)，
代码为独立实现。演示库与评测集为项目自带数据；评测集题目为人工编写的中文问句。
