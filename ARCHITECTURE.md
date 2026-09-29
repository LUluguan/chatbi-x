# 架构文档

## 系统总览

```
                 ┌──────────────────────────────────────────────────┐
                 │                    FastAPI (app/main.py)          │
 Vue 3 ────────▶ │  POST /api/chat        同步问答                    │
 (web/)          │  POST /api/chat/stream SSE 流式（step/result 事件）│
                 │  GET  /api/schema      库表元数据                  │
                 │  GET  /api/health      存活探针                    │
                 └──────┬───────────────────────────────────────────┘
                        │ schema linking（每问动态 Top-K 表）
                        ▼
                 ┌───────────────────────────────┐
                 │  ChatAgent (app/agent.py)      │  propose-verify 工具循环
                 │  协议: 单行 JSON action         │
                 └──┬──────────────┬─────────────┘
          provider.chat│             │ executor.run_sql
                       ▼             ▼
          ┌──────────────────┐  ┌──────────────────────────┐
          │ LLM Provider 层   │  │ 只读执行器 app/executor.py│
          │ mock / openai_compat│ │ 白名单+单语句+只读连接     │
          │ 瞬时故障自动重试    │  │ +超时熔断+行数截断        │
          └──────────────────┘  └──────────────────────────┘

 旁路: MCP server (app/mcp_server.py) 复用同一套工具函数，stdio 暴露 4 个标准工具
       评测 (app/eval/) 不走 HTTP，直接驱动 provider + executor + agent
```

## Agent 协议规范

模型每轮只允许输出**一行 JSON**（`parse_action` 用正则从可能的噪声文本中提取）：

| action | 参数 | 语义 | Agent 行为 |
|---|---|---|---|
| `get_schema` | `table` | 查看表结构/样例/中文注释 | 把 `table_prompt` 拼回对话 |
| `run_sql` | `sql` | 执行只读查询 | 执行并回显结果预览 + SQL 原文 |
| `final` | `sql`, `summary` | 定稿 | SQL 未验证过则**再执行一次**；与已成功执行的 SQL 一致才走快速路径 |

**propose-verify 启动方式**：评测与线上默认先 `single_shot_sql` 生成草案，
以「初始 SQL 草案（未验证）」注入首条 user 消息。Agent 的职责从「从零探索」
收敛为「验证与修正」——这是 v1(33%)→v3(61%) 迭代的核心架构结论，数据见 README。

**执行反馈**：`run_sql` 失败时把数据库错误原文拼回对话（自校正的信号源）；
成功时反馈包含**SQL 原文回显**与「检查结果列是否恰好为答案」的显式指令，
防止模型把探索性宽查询直接定稿（v1 的 20 分差距即由此而来）。

## 安全模型

- **白名单**：仅 `SELECT`/`WITH` 开头；拒绝多语句、`PRAGMA/ATTACH/...`；
- **只读连接**：`file:...?mode=ro` URI，驱动层杜绝写入；
- **超时熔断**：`set_progress_handler` 每 5000 条 VM 指令检查 deadline，
  递归 CTE 死循环实测 200ms 内被杀（sqlite3 会把中断转成 `OperationalError: interrupted`，已映射回超时语义）；
- **行数截断**：`fetchmany(max_rows+1)` 探测并标记 `truncated`；
- 注入面：不拼接用户输入进 SQL（SQL 全部由模型生成并由执行器校验），HTTP 层无鉴权——
  部署定位是个人/内网工具，公网部署需加反向代理鉴权（已知限制）。

## Schema Linking：中文问题 → 英文表名

中文问句与英文 schema 无词面重叠，两件套桥接：

1. **库内注释表** `schema_comments(name, description)`：建库时写中文业务描述，
   `load_schema` 折叠进 `TableInfo.description`，同时进入 prompt 与检索语料；
2. **CJK 字符 n-gram 相似度**（`app/linker.py`）：unigram+bigram 的 cosine，
   纯 Python 无重依赖；few-shot 检索用同一打分，**同数据库示例优先**（SQL 方言一致性）。

局限：纯词面匹配，同义改写无覆盖——向量版 linking 列入路线图（需要 embedding 源）。

## 评测方法学（app/eval/）

- **执行准确率**：预测 SQL 与金标 SQL 各自在真实库上执行，比较结果集
  multiset（行序不敏感、重复行敏感、浮点 6 位容差、NULL/混合类型用类型感知排序键）；
- **难度分组**：simple/moderate/challenging 分别报告；
- **泄漏控制**：few-shot 池来自 train 集（9428 条），评测时过滤同题；
- **oracle check**：mock provider 预设=金标 SQL，验证评测管线本身（BIRD 真实数据 8/8）；
- **逐题留痕**：`compare_report*.json` 保留每题预测 SQL 与错误分类（empty_sql / exec_fail / result_mismatch），
  模式间对比可下钻到题级。真实数据接入当轮即抓出 NULL 排序崩溃，即方法学的价值证明。

## 部署拓扑

| 模式 | 进程 | 适用 |
|---|---|---|
| 开发 | uvicorn :8000 + vite :5173（proxy /api） | 热更新 |
| 容器 | 单容器：`CHATBI_WEB_DIST` 下 StaticFiles 托管前端 | 演示/自托管 |

Provider 层与部署解耦：`mock`（零依赖演示/CI）与 `openai_compat`（DeepSeek/Ollama/vLLM）仅由环境变量切换。

## 已知限制（诚实清单）

1. 仅 SQLite（多数据源需为执行器加方言适配层）；
2. linking 为词面启发式，同义改写无覆盖；
3. Agent `max_steps` 上限 6，极端错误修正可能耗尽步数（此时回退最后成功查询）；
4. 无多轮会话记忆（每问独立，上下文含 Top-K 表 + 2 条 few-shot）；
5. challenging 难度评测样本过少（6/1534），该档数字不具统计意义；
6. 无鉴权与配额（公网部署需自理）。
