"""
LangGraph 状态图：等价迁移 agent.py 的手写循环。
"""

import os
from typing import Annotated

from agent import TOOLS, dispatch  # 复用已有工具定义与执行
from data import GENERALS, UNITS
from dotenv import load_dotenv
from langchain_core.messages import AnyMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import Field

load_dotenv()  # graph.py 自己读 .env，别依赖别的文件先执行


@tool
def simulate_matchup(
    unit_a: Annotated[str, Field(description="A 方兵种名")],
    general_a: Annotated[str, Field(description="A 方武将名")],
    troop_a: Annotated[str, Field(description="A 方兵种类型")],
    unit_b: Annotated[str, Field(description="B 方兵种名")],
    general_b: Annotated[str, Field(description="B 方武将名")],
    troop_b: Annotated[str, Field(description="B 方兵种类型")],
) -> dict:
    """模拟两支阵容的对战，返回 A 方胜率。用于回答'谁赢/胜率多少'类问题。"""
    from battle import Army
    from data import GENERALS, UNITS
    from mc_sim import run_mc_sim

    unit = UNITS.get(unit_a)
    gen_a = GENERALS.get(general_a)
    if unit is None or gen_a is None:
        return {
            "error": f"未知兵种或武将: {unit_a}/{general_a}，可用兵种: {list(UNITS)}，可用武将: {list(GENERALS)}"
        }

    army_a = Army(unit=UNITS[unit_a], general=GENERALS[general_a], troop_type=troop_a)
    army_b = Army(unit=UNITS[unit_b], general=GENERALS[general_b], troop_type=troop_b)
    r = run_mc_sim(army_a, army_b, n=500, damage_jitter=0.2, seed=42)
    return {
        "wins_a": r.wins_a,
        "wins_b": r.wins_b,
        "draws": r.draws,
        "win_rate_a": r.win_rate_a,
    }


@tool
def get_unit_info(
    unit_name: Annotated[str, Field(description="兵种名，如'骑兵'")],
) -> dict:
    """查询一个兵种的完整基础数值（攻击/防御/血量/速度/造价/训练时间）。"""
    unit = UNITS.get(unit_name)
    if unit is None:
        return {"error": f"未知兵种: {unit_name}，可用: {list(UNITS)}"}
    from dataclasses import asdict

    return asdict(unit)  # dataclass 一行转 dict


@tool
def calc_army_power(
    general_name: Annotated[str, Field(description="武将名，如'张飞'")],
    troop_type: Annotated[str, Field(description="兵种类型，如'骑兵'")],
) -> dict:
    """计算某武将带某兵种时的阵容战力。"""
    general = GENERALS.get(general_name)
    unit = UNITS.get(troop_type)
    if general is None or unit is None:
        return {
            "error": f"未知武将或兵种: {general_name}/{troop_type}，可用武将: {list(GENERALS)}，可用兵种: {list(UNITS)}"
        }
    from combat import calc_army_power

    return {"power": calc_army_power(unit, general, troop_type)}


@tool
def get_counter_relation(
    troop_type: Annotated[str, Field(description="兵种类型，如'骑兵'")],
) -> dict:
    """查询某兵种的克制关系：它克制谁、被谁克制。"""
    from troops import COUNTER, TROOP_TYPES

    counters = COUNTER.get(troop_type, [])
    countered_by = [t for t in TROOP_TYPES if troop_type in COUNTER.get(t, [])]
    return {"troop": troop_type, "克制": counters, "被克制": countered_by}


@tool
def diagnose_balance_tool() -> dict:
    """诊断全部兵种的平衡性：跑全兵种对阵矩阵，用 Z-score 检测过强/过弱的兵种。
    当用户询问'数值平衡吗/哪个兵种太强/需要调整吗'时调用。注意：诊断需要跑
    20 场模拟，耗时约 1 分钟，属重工具。"""
    from diagnose import diagnose_balance

    return diagnose_balance()


@tool
def diagnose_balance_tool() -> dict:
    """诊断全部兵种的平衡性：……"""
    from diagnose import diagnose_balance

    return diagnose_balance()


TOOLS_FOR_GRAPH = [
    simulate_matchup,
    get_unit_info,
    calc_army_power,
    get_counter_relation,
    diagnose_balance_tool,
]


SYSTEM_PROMPT = (
    "你是 SLG 数值平衡助手。涉及对战/战力/胜率的问题必须调用工具获取真实数据，"
    "禁止凭记忆编造数字。解释兵种克制关系时，必须先调用 get_counter_relation 工具核实，"
    "禁止凭常识推断克制；未核实克制关系时，要明确说明'克制关系未核实'。"
)


def call_model(state: MessagesState):
    llm = ChatOpenAI(
        model="deepseek-chat",
        openai_api_base="https://api.deepseek.com",
        openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
        timeout=30,  # 单次调用 30 秒超时，防止流被无限挂起
        max_retries=2,  # 失败自动重试 2 次（SDK 内置指数退避）
    )
    model_with_tools = llm.bind_tools(TOOLS_FOR_GRAPH)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + state["messages"]
    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


tool_node = ToolNode(TOOLS_FOR_GRAPH)


def should_continue(state: MessagesState) -> str:
    """条件边：最后一条消息有 tool_calls → 去工具节点，否则结束。"""
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


# TODO 3: 建图
graph_builder = StateGraph(MessagesState)
graph_builder.add_node("call_model", call_model)
graph_builder.add_node("tools", tool_node)
graph_builder.add_edge(START, "call_model")
graph_builder.add_conditional_edges(
    "call_model", should_continue, {"tools": "tools", END: END}
)
graph_builder.add_edge("tools", "call_model")

checkpointer = MemorySaver()
graph = graph_builder.compile(checkpointer=checkpointer)
