"""
Agent：Function Calling 工具注册与编排循环。
"""

import json

from battle import Army
from data import GENERALS, UNITS
from fallback import fallback_answer, record_failure, record_success, should_fallback
from infra import guarded_tool, is_error, log_event
from langfuse.langchain import CallbackHandler
from langgraph.errors import GraphRecursionError
from mc_sim import run_mc_sim
from trace import store

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "simulate_matchup",
            "description": "模拟两支阵容的对战，返回 A 方胜率。用于回答'谁赢/胜率多少'类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_a": {"type": "string", "description": "A 方兵种名，如'骑兵'"},
                    "general_a": {
                        "type": "string",
                        "description": "A 方武将名，如'张飞'",
                    },
                    "troop_a": {"type": "string", "description": "A 方兵种类型"},
                    "unit_b": {"type": "string", "description": "B 方兵种名"},
                    "general_b": {"type": "string", "description": "B 方武将名"},
                    "troop_b": {"type": "string", "description": "B 方兵种类型"},
                },
                "required": [
                    "unit_a",
                    "general_a",
                    "troop_a",
                    "unit_b",
                    "general_b",
                    "troop_b",
                ],
            },
        },
    }
]


@guarded_tool("simulate_matchup", timeout=30.0)
def _simulate_matchup(args: dict) -> dict:
    """真实模拟。被 guarded_tool 包住：
    - 超过 30s     → {"error_code": "TIMEOUT"}
    - 武将名不存在 → {"error_code": "BAD_ARGUMENT"}
    - 其他异常     → {"error_code": "INTERNAL"}
    返回给模型的是「能读懂的失败描述」，不是栈回溯。
    """
    army_a = Army(
        unit=UNITS[args["unit_a"]],
        general=GENERALS[args["general_a"]],
        troop_type=args["troop_a"],
    )
    army_b = Army(
        unit=UNITS[args["unit_b"]],
        general=GENERALS[args["general_b"]],
        troop_type=args["troop_b"],
    )
    r = run_mc_sim(army_a, army_b, n=500, damage_jitter=0.2, seed=42)
    return {
        "wins_a": r.wins_a,
        "wins_b": r.wins_b,
        "draws": r.draws,
        "win_rate_a": r.win_rate_a,
    }


def dispatch(name: str, args: dict) -> dict:
    """执行真实引擎函数——LLM 只能'点菜'，做菜的是这里。"""
    if name == "simulate_matchup":
        result = _simulate_matchup(args)
        # 每次工具调用都留痕：成功/失败、耗时、错误码。
        # 这是 trace 的源头，也是「工具失败率」指标的数据来源。
        log_event(
            "tool",
            tool=name,
            args=args,
            ok=not is_error(result),
            ms=result.get("_elapsed_ms"),
            error_code=result.get("error_code"),
        )
        return result
    return {
        "error": f"未知工具: {name}",
        "error_code": "BAD_ARGUMENT",
        "suggestion": "可用工具只有 simulate_matchup",
    }


def ask_agent(question: str) -> str:
    """完整 Agent 循环：提问 → (LLM 要工具 → 执行 → 回传)*N → 最终回答。"""
    from llm import get_client

    client = get_client()
    messages = [
        {
            "role": "system",
            "content": "你是 SLG 数值平衡助手。涉及对战/战力/胜率的问题必须调用工具获取真实数据，禁止凭记忆编造数字。",
        },
        {"role": "user", "content": question},
    ]
    while True:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:  # 模型不再要工具 → 拿到最终回答
            return msg.content
        messages.append(msg)  # 工具调用请求也要进历史
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = dispatch(tc.function.name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,  # 告诉模型这条结果对应哪次调用
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        # 循环继续：带着工具结果再问模型，直到它给出最终回答


# 函数签名加一个参数（给调用方灵活控制的口子）
def ask_agent_stream(question: str, thread_id: str = "default", max_rounds: int = 10):
    """流式 Agent（LangGraph 版）。max_rounds：工具调用轮数上限。"""
    from graph import graph

    handler = CallbackHandler()  # 会话 = 存档槽
    rounds = 0  # ← 自己的业务计数器
    last_tool_sig = None  # ← 新增：上一次 tool_call 的签名
    try:
        for chunk in graph.stream(
            {"messages": [("user", question)]},
            stream_mode="updates",
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": max_rounds * 2 + 2,
                "callbacks": [handler],
                "metadata": {  # ← 新版绑定会话的方式
                    "langfuse_session_id": thread_id,
                    "langfuse_user_id": "local-dev",
                },
            },
        ):
            for node_name, update in chunk.items():
                for msg in update["messages"]:
                    # call_model 节点：计数 + 判上限 + 分发事件
                    if getattr(msg, "tool_calls", None):
                        rounds += 1
                        if rounds > max_rounds:
                            yield {
                                "event": "answer",
                                "data": {
                                    "text": "已达推理步数上限，请缩小问题范围后重试。"
                                },
                            }
                            return
                        for tc in msg.tool_calls:
                            # ★ 新增：重复调用检测
                            sig = (
                                tc["name"],
                                json.dumps(
                                    tc["args"], sort_keys=True, ensure_ascii=False
                                ),
                            )
                            if sig == last_tool_sig:
                                yield {
                                    "event": "answer",
                                    "data": {
                                        "text": "检测到连续重复调用同一工具且参数相同，已停止以节省资源。"
                                        "如果确实需要重试，请换个问法或补充信息。"
                                    },
                                }
                                return
                            last_tool_sig = sig
                            # 落 trace：工具调用明细。store.stats() 的失败率/步数都靠它
                            store.log(
                                "tool_call",
                                thread_id=thread_id,
                                tool=tc["name"],
                                args=tc["args"],
                            )
                            yield {
                                "event": "tool_call",
                                "data": {"tool": tc["name"], "args": tc["args"]},
                            }
                    # tools 节点：引擎结果（容忍非 JSON 内容——如 ToolNode 的纯文本错误消息）
                    elif msg.type == "tool":
                        try:
                            data = json.loads(msg.content)
                        except (json.JSONDecodeError, TypeError):
                            data = {"raw": str(msg.content)}
                        store.log(
                            "tool_result",
                            thread_id=thread_id,
                            ok="error_code" not in data,
                            error_code=data.get("error_code"),
                            # 工具耗时来自 guarded_tool 注入的 _elapsed_ms，
                            # 没有它 stats() 的 P95 永远是 0
                            ms=data.get("_elapsed_ms"),
                        )
                        yield {"event": "tool_result", "data": data}
                    # 模型最终回答
                    else:
                        record_success(thread_id)  # 正常收尾 → 清零失败计数
                        store.log(
                            "answer",
                            thread_id=thread_id,
                            chars=len(msg.content or ""),
                        )
                        yield {"event": "answer", "data": {"text": msg.content}}
    except GraphRecursionError:
        # 注意：这不属于"服务故障"，不该计入降级计数——
        # 模型是好的，只是我们主动刹车了。
        store.log("loop_guard", thread_id=thread_id, reason="recursion_limit")
        yield {
            "event": "answer",
            "data": {
                "text": "抱歉，这个问题我推演了太多步仍未得出结论，已停止以节省资源。请尝试把问题拆小一点。"
            },
        }
    except Exception as e:  # ← 兜底一切：LLM 连续失败 / 网络中断 / 解析异常
        n = record_failure(thread_id)
        print(f"[agent] 异常（第 {n} 次连续失败）: {type(e).__name__}: {e}")
        store.log(
            "error",
            thread_id=thread_id,
            error=type(e).__name__,
            consecutive_failures=n,
        )

        # 连续失败达到阈值 → 走确定性兜底，而不是继续让用户看"请重试"
        if should_fallback(thread_id):
            text = fallback_answer(question)
            degraded = True
            log_event("fallback", thread_id=thread_id, failures=n, raw_error=str(e)[:120])
        else:
            text = (
                "军师暂时无法处理这个问题（服务波动），请稍后重试。"
                "若持续失败，可换个问法或联系维护者。"
            )
            degraded = False

        yield {"event": "answer", "data": {"text": text, "degraded": degraded}}
