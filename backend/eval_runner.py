"""评测 runner（雏形版）：跑单案例，判定工具路由 + 数值命中。"""

import json
import uuid

from agent import ask_agent_stream


def run_case(case: dict) -> dict:
    collected_tools = []  # [(tool_name, args), ...]
    answer_text = ""
    thread_id = f"eval-{case['case_id']}-{uuid.uuid4().hex[:8]}"  # 每次运行全新存档槽

    # ★ 归一化：字符串 → 单元素列表（两种形态统一成一种，后面只写一份循环）
    questions = (
        case["question"] if isinstance(case["question"], list) else [case["question"]]
    )

    for q in questions:  # 单轮案例 = 循环 1 次，行为不变
        for evt in ask_agent_stream(q, thread_id=thread_id, max_rounds=10):
            if evt["event"] == "tool_call":
                collected_tools.append((evt["data"]["tool"], evt["data"]["args"]))
            elif evt["event"] == "answer":
                answer_text = evt["data"]["text"]  # 多轮时自然留下最后一轮的回答

    # 判定 1：工具路由（期望的每个 (工具名, 关键参数) 都被调用过）
    routing_ok = True
    for exp_tool, exp_args in case.get("expected_tools", []):
        hit = any(
            name == exp_tool and all(args.get(k) == v for k, v in exp_args.items())
            for name, args in collected_tools
        )
        if not hit:
            routing_ok = False

    # 判定 2：数值命中（answer 里出现 expected_facts 的数字，容差 ±0.02）
    numeric_ok = True
    missing = []
    for key, val in case.get("expected_facts", {}).items():
        variants = {
            str(round(val, 3)),  # 1.0
            f"{round(val * 100, 1)}%",  # 100.0%
            f"{round(val * 100)}%",  # 100%
            f"{round(val * 100, 2)}%",
        }

        found = any(v in answer_text for v in variants)

        if not found:
            numeric_ok = False
            missing.append(key)

    # ★ 判定 3：负面检查（新增这两行加在这里）
    forbidden = case.get("answer_must_not_contain", [])
    negative_ok = not any(bad in answer_text for bad in forbidden)

    # 判定 4：正向包含（必含词，全部命中才算过）
    must_contain = case.get("answer_must_contain", [])
    contains_ok = all(w in answer_text for w in must_contain)

    return {
        "case_id": case["case_id"],
        "routing_ok": routing_ok,
        "numeric_ok": numeric_ok,
        "negative_ok": negative_ok,
        "missing": missing,
        "tools_called": [t for t, _ in collected_tools],
        "answer_excerpt": answer_text[:80],
        "contains_ok": contains_ok,
    }


if __name__ == "__main__":
    cases = json.load(open("eval_cases.json", encoding="utf-8"))
    for c in cases:
        r = run_case(c)
        mark = (
            "PASS"
            if (
                r["routing_ok"]
                and r["numeric_ok"]
                and r["negative_ok"]
                and r["contains_ok"]
            )
            else "FAIL"
        )
        print(
            f"[{mark}] {r['case_id']} | tools={r['tools_called']} | missing={r['missing']}"
        )
        print(f"       answer: {r['answer_excerpt']}...")
