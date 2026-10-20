# SLG 数值平衡 Agent 🎯

一个面向 SLG 游戏数值策划的 AI 助手：用自然语言查询兵种数值、克制关系、
阵容战力，并模拟对战给出**可复现的真实胜率**。

> 评测驱动的改进闭环实测：工具路由正确率 **0% → 100%**（详见评测体系）

## 🌐 在线体验

- **前端**：https://slg-balance-agent-frontend.onrender.com
- **后端 API**：https://slg-balance-agent.onrender.com/ping

（免费档冷启动约 1 分钟：首次访问若转圈，是在唤醒服务器——再刷新一次即可）

## ✨ 功能亮点

- **确定性引擎**：兵种 / 克制 / 武将 / 战力 / 战斗 / 蒙特卡洛六大模块，
  同参数结果逐位可复现（seed 固定）——LLM 编排，代码计算
- **LangGraph 编排**：5 个工具、多轮会话记忆（SqliteSaver 持久化）、
  SSE 事件流（tool_call / tool_result / answer 全程可视化）
- **双层评测集**：20 条精选案例（能力覆盖）+ 215 条生成案例（参数密度），
  确定性五判定 + k=3 多数表决 + LLM-as-Judge 三维评分
- **安全实测**：注入对抗（指令覆盖 / 参数注入 / 权限提升诱导）全部防御通过，
  详见 [SECURITY.md](SECURITY.md)

## 🏗️ 架构
```
Next.js (TS) → FastAPI + SSE → LangGraph 状态图 → 5 工具 → 确定性引擎
                                              ↓
                                   Langfuse 可观测（轨迹 / token / 延迟）
```
LLM 只负责理解意图和编排工具；所有数字来自确定性引擎，禁止凭记忆编造。

## 📊 量化战绩

| 指标 | 数字 |
|---|---|
| 评测集 | 235 条（20 精选 + 215 组合生成） |
| 评测回归 | 20/20 stable（k=3 多数表决） |
| 工具路由修复 | 正确率 0% → 100%，零回归 |
| 上下文裁剪 | 输入 token -65%（记忆与指代无损） |
| 注入防御实测 | R20/R21/R22 全部 3/3 通过 |

## 🚀 快速启动

首次安装：

​```powershell
git clone https://github.com/wangyunjie2029/slg-balance-agent.git
cd slg-balance-agent\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example ..\.env    # 然后填入你的 DeepSeek API Key
cd ..\frontend
npm install
​```

日常启动（仓库根目录）：

​```powershell
.\start-backend.bat     # 后端 http://localhost:8000
.\start-frontend.bat    # 前端 http://localhost:3000
​```

浏览器打开 localhost:3000，向军师提问即可。

## 🔍 评测体系

- **精选层**（20 条）：覆盖路由 / 数值 / 多轮指代 / 拒答幻觉 / 注入对抗
- **组合层**（215 条）：`gen_cases.py` 模板 × 组合 × 引擎取证自动生成
- **判定**：确定性五判定 + k=3 多数表决 + LLM-as-Judge 三维评分
- **改进闭环**：评测发现路由缺陷 → system 定向改进 → 复测零回归

安全态势见 [SECURITY.md](SECURITY.md)。

## 🗺️ Roadmap

- [x] 确定性引擎 / LangGraph Agent / 双层评测 / 可观测 / 安全加固
- [ ] 多 Agent 世界模拟器（游戏领域纵深）
- [ ] Agent 轨迹评测台（下一个项目：给任意 Agent 当裁判）
