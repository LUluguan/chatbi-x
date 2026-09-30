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

## 安全模型（三层，各层职责明确）

1. **白名单校验**（`validate_sql`）：对**掩码后**的文本做检查——先把字符串字面量、
   引号标识符、行/块注释替换为空白，再判断开头（`SELECT/WITH/VALUES`，允许括号前缀）、
   单语句（掩码后无内部分号）、禁用词（`PRAGMA/ATTACH/...`）。
   语境盲视的校验会误杀 6 类合法只读 SQL（如 `SELECT 'a;b'`、`LIKE '%attach%'`、
   注释含 vacuum——商品名带"吸尘器"的真实业务场景），掩码是必须的；
2. **只读连接** `mode=ro`：锁主库写入；
   **已知边界**：`mode=ro` 不约束 `ATTACH` 的外部库——绕过第 1 层的 SQL 可以
   `ATTACH` 别的文件并写入。第 3 层补上这一格；
3. **连接级 `PRAGMA query_only=ON`**：ATTACH 写入同样被拦（有回归测试锁定）。

- **超时熔断**：`set_progress_handler` 每 5000 条 VM 指令检查 deadline，
  递归 CTE 死循环实测 200ms 内被杀（sqlite3 会把中断转成 `OperationalError: interrupted`，已映射回超时语义）；
- **行数截断**：`fetchmany(max_rows+1)` 探测并标记 `truncated`；
- 注入面：不拼接用户输入进 SQL（SQL 全部由模型生成并由执行器校验），HTTP 层无鉴权——
  部署定位是个人/内网工具，公网部署需加反向代理鉴权（已知限制）。

## Schema Linking：中文问题 → 英文表名（消融结论：上下文工具，不是准确率杠杆）

中文问句与英文 schema 无词面重叠，桥接两件套：库内 `schema_comments` 中文注释表 +
CJK 字符 n-gram 相似度排序（纯 Python，无重依赖）；few-shot 检索同打分，同库示例优先。

**多表中文基准实测**（15 表教务库 / 48 题中文问句，`data/eval/academic_eval.json`）：

- 召回率（金标表进前 k 位）：Top-4 = 90.3%、Top-6 = 98.3%、**Top-8 = 100%**
  —— 多表 JOIN 的题需要 k 余量，k 过小直接把金标表挤出 prompt（必然失败）；
- prompt 体积（schema 部分）：全 schema 3,524 字节/题 → k=4 省 74%、k=8 省 47%；
- **准确率消融**（DeepSeek-Chat，single_shot，无 few-shot，配对）：
  - k=4：83.33% vs 全 schema 89.58%（McNemar p=0.25，k=4 组含 1 例 exec_fail = 召回缺失所致）
  - k=8：85.42% vs 89.58%（McNemar p=0.5，exec_fail 消失）

**结论**：在 15 表规模，全 schema 塞得下且准确率最优；linking 的价值是**上下文预算与
扩展空间**（47-74% 的省宽，schema 数百表时全量方案不可行），而非本规模下的准确率提升。
诚实边界：纯词面匹配，同义改写无覆盖；注释热词会过度触发（如「学生」使 scholarship_awards
在无关问题中排进前列）——向量版 linking 与 k 的自适应策略列入路线图。

**Join 闭包（外键补桥）**：`rank_tables(closure=True)` 用声明外键 + `*_id` 词干唯一命中
推断（有歧义即弃权）构建表连接图，BFS 补齐种子间的桥表。15 表基准实测（完整召回率 =
金标表全部落入输出集合的问题占比）：

| 配置 | Top-4 | Top-6+ |
|---|---|---|
| 仅词面 | 83.3% (40/48) | 95.8% / 100% |
| + join 闭包 | **97.9% (47/48)** | 100% |

闭包的前提是库里**声明了外键**（bench 库建表时写 `REFERENCES`，真实导出常自带）；
能力边界：闭包只能补「种子之间」的桥，**救不了种子选错**——"平均GPA最高的院系"的
Top-4 种子里 students/departments 不同时在场，图上无路径可补，这是打分问题（向量
linking 的地盘）。且召回↑不保证准确率↑：预计仅能捞回约 1 题（≈+2 点），McNemar
大概率仍不显著。默认关闭（`CHATBI_FK_CLOSURE=1` 开启），因为除召回外尚无准确率证据。

闭包的上下文账分两个视角（48 题实测字符数，`schema_prompt` 口径）：
- **同字节**：闭包 k=4 = 48,985 字符 @ 97.9%，无闭包 k=6 = 49,287 字符 @ 95.8% —— 同等字节数下闭包 +2.1 点；
- **同覆盖（100%）**：无闭包 k=8 = 65,798 字符，闭包 k=6 = 72,970 字符 —— 100% 点上闭包贵约 11%（桥表平均多 1.8 张）。

评测/消融工具已支持闭包（`run_eval(fk_closure=)`、`ablation_linking.py --fk-closure`），
带闭包的准确率消融随时可跑，因 API 成本暂缓。

## 评测方法学（app/eval/）

- **执行准确率**：预测 SQL 与金标 SQL 各自在真实库上执行，比较结果集
  multiset（行序不敏感、重复行敏感、浮点 6 位容差、NULL/混合类型用类型感知排序键）。
  **判据按全量结果集比对**（`eval_max_rows` 默认 10 万行，与 Agent 预览的 50 行严格分离，
  命中上限的题在报告里带 `truncated` 标记）——早期版本按预览行数截断两边再比，
  长结果集上双向失真，此缺陷由外部评审发现后修复并有回归测试锁定；
- **失败分类**：每题带 `category` 字段：`correct / empty_sql / exec_fail / max_steps / result_mismatch`，
  模式间对比可下钻到题级；
- **难度分组**：simple/moderate/challenging 分别报告；
- **泄漏控制**：few-shot 池来自 train 集（9428 条），评测时过滤同题；
- **oracle check**：mock provider 预设=金标 SQL，验证评测管线本身（BIRD 真实数据 8/8）。

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
