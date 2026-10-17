"""
LangGraph 状态图：等价迁移 agent.py 的手写循环。
"""

import os
from typing import Annotated

from agent import TOOLS, dispatch  # 复用已有工具定义与执行
from dotenv import load_dotenv
from langchain_core.messages import AnyMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
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


TOOLS_FOR_GRAPH = [simulate_matchup]


def call_model(state: MessagesState):
    llm = ChatOpenAI(
        model="deepseek-chat",
        openai_api_base="https://api.deepseek.com",
        openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
    )
    model_with_tools = llm.bind_tools(TOOLS_FOR_GRAPH)
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


# TODO 2: 工具节点
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
graph_builder.add_edge("tools", "call_model")  # 工具执行完回模型——闭环！
graph = graph_builder.compile()  # checkpointer 是 2-5b 的事
