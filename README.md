# SLG 数值平衡 Agent 🎯

一个面向 SLG 数值策划的 AI 助手：用自然语言查询兵种数值、克制关系、阵容战力，
模拟对战并给出**可复现的真实胜率**。

**核心设计一句话：LLM 只负责理解意图和表达结论，所有数字来自确定性引擎。**

## 🌐 在线体验

- **前端**：https://slg-balance-agent-frontend.onrender.com
- **后端**：https://slg-balance-agent.onrender.com/ping

（免费档冷启动约 1 分钟：首次访问转圈是在唤醒服务器，刷新即可）

## ✨ 功能亮点

- **确定性引擎**：兵种 / 武将 / 克制 / 战力 / 战斗 / 蒙特卡洛六个模块，
  固定 seed 下逐位可复现——模型编不出数字，只能引用
- **LangGraph 编排**：5 个工具、SqliteSaver 会话持久化、SSE 事件流
  （tool_call / tool_result / answer 全程可视化）
- **六层工程化**：接入（鉴权/限流/request_id）、编排（循环上限/重复检测/降级）、
  工具（超时/结构化错误/参数校验）、上下文（滑窗+摘要）、观测（日志/Trace/Langfuse）、
  评测（分层用例/双口径/K=3/归因/A-B 对比）
- **评测驱动改进**：用例按真值难度分层，同时统计「规则通过率」与「严格通过率
  （含 LLM Judge）」，失败自动归因到 prompt / tool / data / orchestration

## 🏗️ 架构（按请求流向分层）

```
请求
 │
 ├─① 接入层    Bearer 鉴权 · 令牌桶限流 · request_id 贯穿 · 结构化日志
 │             main.py · infra.py · config.py
 │
 ├─② 编排层    LangGraph 状态图 · 循环上限 · 重复调用检测 · LLM 失败降级
 │             graph.py · agent.py · fallback.py
 │
 ├─③ 工具层    5 个工具 · 超时守卫 · 结构化错误(error_code+suggestion) · 参数校验
 │             graph.py(@tool) · infra.py(guarded_tool)
 │
 ├─④ 上下文层  滑窗裁剪 + 配对保护 + 实体摘要 · SqliteSaver 会话存档
 │             graph.py(build_window)
 │
 ├─⑤ 领域引擎  兵种/武将/克制/战力/战斗/蒙特卡洛（纯计算，零 LLM 依赖）
 │             data.py · generals.py · troops.py · combat.py · battle.py
 │             · mc_sim.py · diagnose.py
 │
 ├─⑥ 观测层    结构化事件日志 · 失败率/步数/P95 指标 · Langfuse 链路追踪
 │             infra.py(log_event) · trace.py
 │
 └─⑦ 评测层    用例生成 · 五维判定 · K=3 稳定性 · 11 类失败归因 · A/B 对比
                gen_cases.py · gen_extra_cases.py · build_core_set.py
                · eval_runner.py · eval_judge.py · eval_attribution.py · eval_report.py
```

## 📊 量化战绩

| 指标 | 数字 | 口径 |
|---|---|---|
| 用例总量 | 1241 条 | 生成 1195 + 手工 22 + 补充类型 24 |
| 核心评测集 | 171 条 | 分层抽样，覆盖 7 类失败模式 |
| 均势对局 | 90 条 | 真值胜率 20%~80% |
| **核心集严格通过** | **168 / 171（98.2%）** | K=3 过半 + Judge 均分 ≥ 6 |
| **均势对局通过** | **90 / 90（100%）** | 同上 |
| Judge 均分 | 8.23 / 10 | 三维平均（忠实/完整/得体） |
| 平均步数 | 1.6 | 每次对话的工具调用次数 |
| flaky 用例 | 2 条（E201 / E206） | 注入场景下的行为分歧，见下 |
| 工具路由修复 | 0% → 100% | 20 条精选用例，k=3 多数表决 |
| 上下文裁剪 | 输入 token −65% | 滑窗 + 摘要，指代无损 |
| 注入对抗 | R20/R21/R22 全 3/3 | 见 SECURITY.md |

> **两条 flaky 的说明**：E201/E206 是"要求模型别调工具"的注入用例。模型有时照常调工具回答，
> 有时直接**拒绝整个请求**。两种反应都不算安全缺陷——后者甚至更保守——但从产品角度是
> 「明明能答却不答」的体验损失。这属于待决策的产品行为，不是模型 bug。
>
> 首轮评测里唯一稳定失败的是 R13，排查后是**用例真值过期**（jitter 从 0.2 改到 0.35 后没重新取证，
> 真值 0.844 实际是 0.728）。修正后 3/3 通过。**这条比任何通过率都值得记：
> 评测失败要先区分「模型错」还是「用例错」。**

> 所有数字都可复现：`backend/reports/*.json` 里有完整报告，含每条用例的判定与证据。

## 🚀 快速启动

```powershell
git clone https://github.com/wangyunjie2029/slg-balance-agent.git
cd slg-balance-agent\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example ..\.env    # 填入 DeepSeek API Key
cd ..\frontend
npm install
```

日常启动（仓库根目录）：

```powershell
.\start-backend.bat     # 后端 http://localhost:8000
.\start-frontend.bat    # 前端 http://localhost:3000
```

## ☁️ 部署（Render）

**后端**（Root Directory = `backend`）

- 启动命令：`uvicorn main:app --host 0.0.0.0 --port $PORT`
- 环境变量：

| 变量 | 必填 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | 没有则启动直接报错中止（lifespan 校验） |
| `API_TOKEN` | ⚠️ 强烈建议 | **不设则接口无鉴权**，任何人都能消耗你的 key |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 可选 | 不填只是不上报 trace |

**前端**（Root Directory = `frontend`）

| 变量 | 必填 | 说明 |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | ✅ | 填后端域名。**不填会回落到 localhost，线上直接连不上** |

**免费档的三个已知限制**

- **无持久磁盘**：`checkpoints.db` 每次重启丢失 → 多轮会话不跨重启保留
- **冷启动约 1 分钟**：首次访问会转圈
- **单实例**：内存令牌桶限流有效；如果扩到多 worker，限流会失效（要换 Redis）

## 🔍 评测体系

**三层用例**

| 层 | 内容 | 数量 |
|---|---|---|
| 组合层 | `gen_cases.py` 模板 × 武将 × 兵种 × 引擎取证 | 1195 条 |
| 补充类型层 | `gen_extra_cases.py` 多轮/注入/拒绝/工具异常/边界 | 24 条 |
| 手工层 | 人工设计的路由、拒答、注入用例 | 22 条 |

**核心集（`build_core_set.py`）**：1241 → 171 条。
原则是**数量做减法、类型做加法**——595 条「战力比大小」和 15 条发现的问题类型完全一样，
所以只抽样保留；而 90 条均势对局全保留，因为只有它们需要模型说准「接近平衡」。

**双口径判定**

- **规则口径**：工具路由 / 数值命中（容差 0.02）/ 负面断言 / 必含词 / 工具黑名单
- **严格口径**：规则全过 **且** LLM Judge 三维均分 ≥ 6（faithfulness / completeness / appropriateness）
- **稳定性**：每条跑 K=3，过半通过才算 stable，中间态标记 flaky

> 为什么要双口径：只看规则会出现「数字抄对但解释全是脑补」也算通过。
> 首轮评测 100% 通过，正是靠这套口径拆出来「用例太容易」而不是「模型很强」。

**失败归因（`eval_attribution.py`）**：11 类
`INTENT_MISUNDERSTAND / WRONG_TOOL / WRONG_ARGUMENT / BAD_ARGUMENT / TOOL_FAILURE /
NUMERIC_MISS / HALLUCINATION / FORBIDDEN_CONTENT / MISSING_REQUIRED /
TOOL_DISCIPLINE / LOOP_GUARD / LOW_QUALITY`

每类映射到「该改哪个组件」，输出的是「先改 prompt（影响 X 条）」这种可执行结论，
而不是一串红叉。

**A/B 对比（`eval_report.py --baseline`）**：对比两次评测的通过率、平均步数、flaky 数、
修复了哪些用例、回归了哪些用例——这是「改动有没有用」的唯一证据。

```bash
python eval_report.py --cases eval_cases_core.json --k 3 --out reports/core-baseline.json
python eval_report.py --cases eval_cases_core.json --k 3 --out reports/after.json \
       --baseline reports/core-baseline.json
```

## ⚠️ 已知不足（诚实记录）

- **上下文压缩是规则摘要**，不是 LLM 摘要。只保留「聊过哪些实体」，不保留语义；换成 LLM 摘要
  要接受每次请求多一次调用。当前选择是成本优先。
- **没有向量化的长期记忆**，只有 checkpointer 的会话级存档。
- **鉴权是最简 Bearer Token**，没有多租户和配额体系。
- **评测集偏数值类**：130/171 条与数值相关，多轮和注入各只有 5-6 条，
  统计意义有限（只能定性不能定量）。
- **Judge 未校准**：没有算过与人工标注的一致率，阈值 6.0 是经验值。

## 🗺️ Roadmap

- [x] 确定性引擎 / LangGraph Agent / 六层工程化 / 分层评测 / 可观测 / 安全加固
- [ ] Judge 与人工标注的一致率校准
- [ ] 多 Agent 世界模拟器（游戏领域纵深）
- [ ] Agent 轨迹评测台（下一个项目：给任意 Agent 当裁判）
