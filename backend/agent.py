"""
Agent：Function Calling 工具注册与编排循环。
"""

import json

from battle import Army
from data import GENERALS, UNITS
from mc_sim import run_mc_sim

# TODO 2: 工具说明书（JSON Schema——给 LLM 看的"使用手册"）
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


def dispatch(name: str, args: dict) -> dict:
    """执行真实引擎函数——LLM 只能'点菜'，做菜的是这里。"""
    if name == "simulate_matchup":
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
    return {"error": f"未知工具: {name}"}


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


def ask_agent_stream(question: str):
    """流式 Agent：yield {"event": ..., "data": ...} 字典序列。"""
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
        if not msg.tool_calls:
            yield {"event": "answer", "data": {"text": msg.content}}
            return
        messages.append(msg)
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)

            yield {
                "event": "tool_call",
                "data": {"tool": tc.function.name, "args": args},
            }
            result = dispatch(tc.function.name, args)
            yield {"event": "tool_result", "data": result}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
