"""评测 runner（雏形版）：跑单案例，判定工具路由 + 数值命中。"""

import json
import re
import sqlite3
import uuid

from agent import ask_agent_stream
from eval_judge import judge_answer


def extract_percentages(text: str) -> list[float]:
    """从文本提取所有百分数，返回小数形式列表。'胜率 100%' -> [1.0]，'98.2%' -> [0.982]"""
    return [round(float(m) / 100, 4) for m in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)]


def extract_numbers(text: str) -> list[float]:
    """提取所有独立数字（含整数），用于战力类真值。'战力 238' -> [238.0]"""
    return [float(m) for m in re.findall(r"\d+(?:\.\d+)?", text)]


def cleanup_eval_threads(db_path: str = "checkpoints.db"):
    conn = sqlite3.connect(db_path)
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]
    deleted = 0
    for t in ("checkpoints", "writes"):  # langgraph-sqlite 的两张表（以实际为准）
        if t in tables:
            cur = conn.execute(f"DELETE FROM {t} WHERE thread_id LIKE 'eval-%'")
            deleted += cur.rowcount
    conn.commit()
    conn.close()
    print(f"[cleanup] 已清理旧评测线程 {deleted} 行")


def run_case(case: dict, run_index: int = 0) -> dict:
    thread_id = f"eval-{case['case_id']}-run{run_index}"
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

    # 判定 2：数值命中（2-11c 升级：提取池 + 容差比对，替代子串变体匹配）
    numeric_ok = True
    missing = []
    for key, val in case.get("expected_facts", {}).items():
        # 胜率/比率语义的键 → 从百分数池比对；其余（战力等）→ 整数池
        is_rate_like = "rate" in key.lower() or "ratio" in key.lower()
        pool = (
            extract_percentages(answer_text)
            if is_rate_like
            else extract_numbers(answer_text)
        )
        found = any(abs(p - val) <= 0.02 for p in pool)  # 容差比较，不是子串
        if not found:
            numeric_ok = False
            missing.append(key)

    # ★ 判定 3：负面检查（新增这两行加在这里）
    forbidden = case.get("answer_must_not_contain", [])
    negative_ok = not any(bad in answer_text for bad in forbidden)

    # 判定 4：正向包含（必含词，全部命中才算过）
    must_contain = case.get("answer_must_contain", [])
    contains_ok = all(w in answer_text for w in must_contain)

    # 判定 5：禁调工具（黑名单里的工具一次都不许出现）
    forbidden_tools = case.get("forbidden_tools", [])
    tools_discipline_ok = not any(
        name in forbidden_tools for name, _ in collected_tools
    )
    # Judge 评分（多轮案例评最后一轮的回答）
    judge_q = (
        case["question"] if isinstance(case["question"], str) else case["question"][-1]
    )
    judge = judge_answer(judge_q, answer_text)

    return {
        "case_id": case["case_id"],
        "routing_ok": routing_ok,
        "numeric_ok": numeric_ok,
        "negative_ok": negative_ok,
        "missing": missing,
        "tools_called": [t for t, _ in collected_tools],
        "answer_excerpt": answer_text[:80],
        "contains_ok": contains_ok,
        "overall_ok": routing_ok
        and numeric_ok
        and negative_ok
        and contains_ok
        and tools_discipline_ok,
        "judge": judge,
    }


K = 3  # 每案例运行次数


def run_case_stable(case: dict) -> dict:
    results = [run_case(case, run_index=i) for i in range(K)]
    passes = sum(1 for r in results if r["overall_ok"])
    return {
        **results[0],
        "stable_pass": passes >= 2,
        "flaky": 0 < passes < K,
        "pass_rate": passes / K,
        "runs_detail": [  # ← 新增：每次运行的死因
            (r["overall_ok"], r["missing"], r["tools_called"]) for r in results
        ],
    }


if __name__ == "__main__":
    cases = json.load(open("eval_cases.json", encoding="utf-8"))
    for c in cases:
        r = run_case_stable(c)
        mark = "PASS" if r["stable_pass"] else "FAIL"
        if mark == "FAIL":
            for i, (ok, miss, tools) in enumerate(r["runs_detail"]):
                print(
                    f"       run{i}: {'OK ' if ok else 'FAIL'} missing={miss} tools={tools}"
                )

        stab = (
            "flaky" if r["flaky"] else ("stable" if r["stable_pass"] else "stable_fail")
        )
        print(
            f"[{mark}] {r['case_id']} | {stab} ({r['pass_rate']:.0%}) | tools={r['tools_called']}"
        )
        print(f"       answer: {r['answer_excerpt']}...")
        avg = (
            r["judge"]["faithfulness"]
            + r["judge"]["completeness"]
            + r["judge"]["appropriateness"]
        ) / 3
        print(
            f"       judge: {avg:.1f}/10 | 忠实 {r['judge']['faithfulness']} 引用 {r['judge']['completeness']} 得体 {r['judge']['appropriateness']}"
        )
