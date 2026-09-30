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
- **MCP server**：`python -m app.mcp_server` 把 `list_tables / get_schema / run_sql / ask` 暴露为标准 MCP 工具，可接入 Claude Desktop 等任何 MCP 客户端；CI 中以**真实 stdio 协议**端到端验证（握手 → list_tools → call_tool）。
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

接真实模型：复制 `.env.example` 为 `.env`，取消 `CHATBI_LLM_PROVIDER=openai_compat` 相关注释并填入 API Key
（或本地 Ollama 地址）。
**⚠ 计费提醒**：openai_compat 模式下每次提问/评测都会调用真实 API 产生费用——服务启动横幅、
`/api/health` 的 `billing` 字段、前端左上角徽章三处都会明确提示；演示请保持 mock。

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
python -m pytest -q          # 全量测试
```

> 注：MCP 协议端到端测试在 CI（Linux）真实运行；本机若 pywin32/site 环境异常，
> 这 2 条会如实 skip（其余全部应绿）——本地输出形如 `126 passed, 2 skipped` 属正常。

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

> **判据修正说明**：v1–v3 的判据把预测与金标都按 50 行截断后比对物理顺序的前 50 行。
> 该缺陷在逻辑上可双向失真（等价改写 `SELECT * FROM (gold) ORDER BY 1` 被判 0.0——有反向验证），
> 但**在本样本上的净效应是单向虚高**：用修复后判据重判 v3 的既有预测（零 LLM 成本，
> `python -m app.eval.rejudge`），single_shot 51%→49%、agent 61%→58%，翻转全部是「对→错」。
> v4 为真实重跑（含采样方差与 top_k=6），**headline 数字以 v4 为准**。

| 版本 | single_shot（朴素基线） | agent | 关键改动 |
|---|---|---|---|
| v1 | 53.00% | 33.00% | 初版反馈话术诱导模型把探索性宽查询直接定稿（22 题翻车全因如此） |
| v2 | 51.00% | 45.00% | 反馈回显 SQL + 显式检查「结果列恰为答案」；自校正救回 10 题 |
| v3* | 51.00% | 61.00% | **propose-verify 架构**（判据有缺陷，保留仅为呈现迭代轨迹；重判后 49% / 58%） |
| **v4** | **53.00%** | **63.00%（+10）** | 修复后判据全量复测 + top_k 6（召回 100%）；**agent 的失败全部为 result_mismatch，exec_fail/empty_sql/max_steps 均为 0** |

**统计呈现（配对视角）**：同一批 100 题是配对实验——仅 agent 对 12 题、仅基线对 2 题，
McNemar 精确检验（双侧）**p = 0.0129**。两个边际准确率的 95% Wilson 区间
（[43.3%, 62.5%] 与 [53.2%, 71.8%]）虽有重叠，但配对检验显著——「自校正有正收益」是
统计结论而非观感，这也是为什么不该只用「63% vs 53%」来呈现。

v4 分难度：simple 69.49% vs 基线 61.02%；moderate 57.14% vs 42.86%；challenging 样本仅 6 题不计入结论。
模式间逐题对比：基线错→agent 对 12 题，基线对→agent 错 2 题（自校正净收益 +10）。

核心教训：**Agent 的价值不是「从零探索」，而是「验证与修正」**——让它站在基线答案的肩膀上，
执行反馈自校正才有正收益。完整报告（逐题预测 SQL + 失败分类）见 `data/eval/compare_report_v4.json`。

**关于 Schema Linking 的消融证据**（15 表中文教务库 / 48 题，`data/eval/academic_eval.json`）：
召回率 Top-8 = 100%（Top-4 = 90.3%，多表 JOIN 需 k 余量）；prompt 省 47-74%；但准确率
消融显示 **linking 在 15 表规模不提升准确率**（k=4: 83.33% / k=8: 85.42% vs 全 schema 89.58%，
McNemar p≥0.25）——它的价值是上下文预算与百表级扩展空间，不是本规模的准确率杠杆。
完整数据与结论见 ARCHITECTURE.md 与 `data/eval/linking_ablation*.json`。

## 文档

- [ARCHITECTURE.md](ARCHITECTURE.md) —— 系统总览、Agent 协议规范、安全模型、评测方法学、已知限制
- `docs/求职要点.md` —— 面试准备材料（内部参考）

## 压测与流式实测

**管线本身**（mock provider，不含 LLM 延迟）：

```
并发=32  总请求=200  成功=200
吞吐 307.7 req/s   p50/p95/max = 99ms / 120ms / 141ms
```

**真实模型**（DeepSeek-Chat，4 并发 × 8 请求，同一套 load_test 脚本）：

```
并发=4  总请求=8  成功=8
吞吐 3.0 req/s   p50/p95 = 1218ms / 1503ms
```

对照结论：应用自身开销（SSE 调度 + SQL 执行）相比 LLM 延迟可忽略，
瓶颈在模型侧 —— 管线优化空间不在吞吐而在提示词与调用次数。

**SSE 增量递送验证**（`scripts/smoke_sse.py`，真实模型事件时间线）：

```
+  1152ms  step    SELECT p.name, SUM(oi.qty * oi.unit_price) AS revenue ...
+  2189ms  step    （final 定稿）
+  2190ms  result  销售额最高的商品是机械键盘，销售额约23425.58
```

事件随 Agent 执行进度递送（step 先于 result，首末间隔秒级），非末尾一次性缓冲。

复现:
```bash
# 管线压测
CHATBI_LLM_PROVIDER=mock python -m uvicorn app.main:app --port 8010
python scripts/load_test.py --base http://127.0.0.1:8010 --concurrency 32 --total 200
# 真实模型压测 / SSE 时间线（产生少量 API 费用）
CHATBI_LLM_PROVIDER=openai_compat python -m uvicorn app.main:app --port 8010
python scripts/load_test.py --base http://127.0.0.1:8010 --concurrency 4 --total 8
python scripts/smoke_sse.py --base http://127.0.0.1:8010 --min-spread-ms 300
```

前端产物按需加载：echarts 拆为独立 chunk（1,134KB，仅首次渲染图表时下载），
主包 71.6KB（gzip 29KB）。

## 路线图

- [x] W1 脚手架：Agent 循环 / 执行器 / Provider / 评测框架 / mini 评测集 / Web 骨架
- [x] W2 数据与基线：BIRD-dev 全量接入 ✓ / few-shot 池（同库优先）✓ / 难度分组报告 ✓ / evidence 注入 ✓ / 模式对比 CLI ✓ / propose-verify 架构（BIRD-100 上 agent 61% vs 基线 51%）✓ / 向量版 linking（待接真实 embedding 源）
- [x] W3 产品化：SSE 流式输出 ✓ / ECharts 图表推荐 ✓ / MCP server ✓ / Docker 一键部署 ✓
- [x] W4 发布：架构文档 ✓ / CI（pytest 双版本矩阵 + 前端构建 + **Docker 构建与启动自检**）✓ / 压测报告 ✓ / 全量 1534 题报告（可选，按需运行 `python -m app.eval.compare` 不带 --limit）
- [x] W5 深水区：15 表中文基准 + linking 消融（召回 100%@k8、prompt 省 47-74%、准确率无增益——诚实结论）✓ / 配对统计（McNemar+Wilson）✓ / rejudge 零成本复测 ✓ / SSE 与真实模型压测实测 ✓ / 三轮外部评审闭环 ✓

## 致谢与边界

架构参考 [DB-GPT](https://github.com/eosphoros-ai/DB-GPT) 与 [vanna](https://github.com/vanna-ai/vanna)，
代码为独立实现。演示库与评测集为项目自带数据；评测集题目为人工编写的中文问句。
