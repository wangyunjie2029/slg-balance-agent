"""上下文滑窗的 token 节省测算 —— 简历「输入 token −65%」的复现脚本。

为什么需要这个文件：
    「−65%」如果只说结论，面试官一定会追问「在多少轮对话下测的、怎么算的」。
    而这个比例**强依赖对话轮数**（轮数越多省越多），所以必须带着口径说。
    本脚本把口径固定下来，可当场运行、可复现。

用法：
    python token_demo.py                 # 扫 5/10/20/40 轮，看比例随轮数的变化
    python token_demo.py --rounds 10     # 只看某一档（对应简历上的 −65%）

口径（面试时必须一起说）：
    - 一轮 = user + AI(发起工具调用) + tool 结果 + AI(最终回答)，共 4 条消息
    - token 用字符数近似（中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token），
      与真实 token 同比例，因此「减少比例」可直接引用
    - 摘要走规则（不额外调 LLM），成本≈0，所以裁剪后的总量 = 窗口 + 摘要
    - 滑窗大小取 config.WINDOW_SIZE（默认 12 条 ≈ 3 轮）
"""

import argparse

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from config import WINDOW_SIZE
from graph import build_window

# 一轮对话的真实形态：问 → 调工具 → 工具返回 → 总结
_QUESTION = "张飞带骑兵打关羽带枪兵，胜率多少？"
_TOOL_RESULT = '{"wins_a": 18, "wins_b": 482, "win_rate_a": 0.036}'
_ANSWER = "张飞骑兵对关羽枪兵胜率约 3.6%（500 局模拟），枪兵克制骑兵，差距明显。"


def build_history(rounds: int) -> list:
    """构造 rounds 轮真实形态的对话历史（每轮 4 条消息）。"""
    msgs: list = []
    for i in range(rounds):
        msgs.append(HumanMessage(content=f"[第{i + 1}轮] {_QUESTION}"))
        msgs.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "simulate_matchup",
                        "args": {
                            "unit_a": "骑兵",
                            "general_a": "张飞",
                            "troop_a": "骑兵",
                            "unit_b": "枪兵",
                            "general_b": "关羽",
                            "troop_b": "枪兵",
                        },
                        "id": f"call_{i}",
                    }
                ],
            )
        )
        msgs.append(ToolMessage(content=_TOOL_RESULT, tool_call_id=f"call_{i}"))
        msgs.append(AIMessage(content=_ANSWER))
    return msgs


def chars(msgs: list) -> int:
    """按消息内容估算 token 量（字符数近似）。"""
    total = 0
    for m in msgs:
        content = m.content if isinstance(m.content, str) else str(m.content)
        total += len(content)
        # 工具调用的参数也算 token
        for tc in getattr(m, "tool_calls", None) or []:
            total += len(str(tc.get("args", ""))) + len(tc.get("name", ""))
    return total


def measure(rounds: int) -> dict:
    msgs = build_history(rounds)
    window, summary = build_window(msgs, max_messages=WINDOW_SIZE)

    full = chars(msgs)
    after = chars(window) + len(summary)

    return {
        "rounds": rounds,
        "msgs_full": len(msgs),
        "msgs_window": len(window),
        "chars_full": full,
        "chars_after": after,
        "cut_pct": 1 - after / full if full else 0.0,
        "summary_chars": len(summary),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="只测某一档轮数（0 = 扫描 5/10/20/40）",
    )
    args = ap.parse_args()

    tiers = [args.rounds] if args.rounds else [5, 10, 20, 40]

    print(f"滑窗大小 WINDOW_SIZE = {WINDOW_SIZE} 条消息（约 {WINDOW_SIZE // 4} 轮）")
    print()
    print(f"{'轮数':>4} {'消息数':>12} {'字符(全量)':>11} {'字符(裁剪后)':>13} {'减少':>7}")
    print("-" * 54)
    rows = []
    for r in tiers:
        m = measure(r)
        rows.append(m)
        print(
            f"{m['rounds']:>4} "
            f"{m['msgs_full']:>5} → {m['msgs_window']:<4} "
            f"{m['chars_full']:>10} "
            f"{m['chars_after']:>12} "
            f"{m['cut_pct']:>6.1%}"
        )
    print("-" * 54)
    print("注：token 用字符数近似，减少比例可直接引用；摘要走规则不调 LLM，成本≈0。")
    print()
    print("面试话术（带口径）：")
    for m in rows:
        if m["rounds"] in (10, 20):
            print(
                f"  · {m['rounds']} 轮对话时，发送量 {m['chars_full']} → "
                f"{m['chars_after']} 字符，减少 {m['cut_pct']:.1%}"
            )


if __name__ == "__main__":
    main()
