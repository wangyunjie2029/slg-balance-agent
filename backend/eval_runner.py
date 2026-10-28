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


# 否定语境标记：出现在禁用词附近，说明模型是在辟谣 / 拒绝，而不是在断言
_NEG_MARKERS = (
    "不是",
    "不会",
    "不能",
    "没有",
    "无法",
    "并非",
    "拒绝",
    "不予",
    "不存在",
)


def _is_asserted(text: str, phrase: str, window: int = 18) -> bool:
    """判断 phrase 是否被「断言」了，而不是被引用/否定。

    为什么需要：负面断言（answer_must_not_contain）在评测里最容易误杀。
    实测踩过四次：
      · 断言不含 "99%"，模型答"所以不是 99%，而是 100%" → 误杀
      · 断言不含 "武力 150"，模型答"你给的 150 我没有采用" → 误杀
      · 断言不含 "是"，而"是"是"是否/这是"的子串 → 误杀
      · 断言不含 "编一个"，模型答"我不会随便编一个" → 误杀
    统一处理：只要 phrase 的每一处出现都在否定语境里，就不算违规。
    """
    if not phrase or phrase not in text:
        return False
    start = 0
    while True:
        i = text.find(phrase, start)
        if i < 0:
            return False
        ctx = text[max(0, i - window) : i + len(phrase) + window]
        if not any(m in ctx for m in _NEG_MARKERS):
            return True  # 附近没有否定词 → 确实是断言
        start = i + 1


def run_case(case: dict, run_index: int = 0) -> dict:
    collected_tools = []  # [(tool_name, args), ...]
    collected_results = []  # [(tool_name, 返回摘要), ...] ← 给 Judge 当证据
    error_codes = []  # ← 新增：工具返回的错误码（归因用）
    answer_text = ""
    # 每次运行用全新存档槽：K 次跑必须互相隔离，否则第二次会命中第一次的记忆
    thread_id = f"eval-{case['case_id']}-{uuid.uuid4().hex[:8]}"

    # ★ 归一化：字符串 → 单元素列表（两种形态统一成一种，后面只写一份循环）
    questions = (
        case["question"] if isinstance(case["question"], list) else [case["question"]]
    )

    for q in questions:  # 单轮案例 = 循环 1 次，行为不变
        for evt in ask_agent_stream(q, thread_id=thread_id, max_rounds=10):
            if evt["event"] == "tool_call":
                collected_tools.append((evt["data"]["tool"], evt["data"]["args"]))
            elif evt["event"] == "tool_result":
                # ★ 新增：把工具层的结构化错误码收集起来，供失败归因使用
                data = evt["data"]
                if isinstance(data, dict) and data.get("error_code"):
                    error_codes.append(data["error_code"])
                # 同时留一份返回摘要当证据：Judge 不看工具返回值时，
                # 会把「有工具支撑的数字」误判成「编造数字」（实测踩过）。
                collected_results.append(str(data)[:200])
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

    # ★ 判定 3：负面检查
    # 这里踩过四次同一个坑：负面断言会命中**正确回答里的引用**。
    #   例：断言不许出现 "99%"，而模型答"所以不是 99%，而是 100%" —— 被判失败；
    #       断言不许出现 "武力 150"，而模型答"你给的 150 我没有采用" —— 被判失败。
    # 根治办法：看这个词是不是被"断言"了。若它出现在否定语境里（前后有"不是/没有/
    # 不会/无法"等），说明模型是在辟谣或拒绝，不算违规。
    # 原则：宁可漏放，不可误杀 —— 误杀会让你去改一个本来没问题的 prompt。
    forbidden = case.get("answer_must_not_contain", [])
    negative_ok = not any(_is_asserted(answer_text, bad) for bad in forbidden)

    # 判定 4：正向包含（必含词，全部命中才算过）
    must_contain = case.get("answer_must_contain", [])
    contains_ok = all(w in answer_text for w in must_contain)

    # 判定 5：禁调工具（黑名单里的工具一次都不许出现）
    forbidden_tools = case.get("forbidden_tools", [])
    tools_discipline_ok = not any(
        name in forbidden_tools for name, _ in collected_tools
    )
    # Judge 评分
    # 三件事必须一起传给 Judge，否则它会误判（三条都是实测踩出来的）：
    #  ① 完整对话历史 —— 只传最后一轮时，"那张弓兵呢" 脱离上文会被判"指代不清"
    #  ② 参考事实     —— 不给真值，它无法发现数字被改错
    #  ③ 工具执行记录 —— 不给证据，它会把有工具支撑的数字判成"编造"
    judge_q = " → ".join(questions) if isinstance(case["question"], list) else case["question"]
    evidence = [
        f"{name}({args}) → {res}"
        for (name, args), res in zip(collected_tools, collected_results)
    ]
    judge = judge_answer(
        judge_q,
        answer_text,
        facts=case.get("expected_facts"),
        evidence=evidence,
    )

    return {
        "case_id": case["case_id"],
        "routing_ok": routing_ok,
        "numeric_ok": numeric_ok,
        "negative_ok": negative_ok,
        "missing": missing,
        "tools_called": [t for t, _ in collected_tools],
        # ★ 新增三个字段：归因模块需要 args 明细才能区分「工具选错」和「参数填错」
        "tool_calls_detail": collected_tools,
        "error_codes": error_codes,
        "steps": len(collected_tools),
        "answer_excerpt": answer_text[:80],
        "contains_ok": contains_ok,
        "overall_ok": routing_ok
        and numeric_ok
        and negative_ok
        and contains_ok
        and tools_discipline_ok,
        "judge": judge,
    }


K = 3  # 默认每案例运行次数
JUDGE_PASS_THRESHOLD = 6.0  # Judge 三项均分及格线（strict 口径用）


def _judge_avg(r: dict) -> float:
    """Judge 三项均分。缺字段或解析失败按 0 算。"""
    j = r.get("judge") or {}
    vals = [j.get("faithfulness"), j.get("completeness"), j.get("appropriateness")]
    nums = [v for v in vals if isinstance(v, (int, float))]
    return sum(nums) / len(nums) if nums else 0.0


def run_case_stable(case: dict, k: int = K) -> dict:
    """跑 k 次，给出稳定 / 严格两种口径。

    - stable_pass：k 次里过半通过（规则判定）
    - strict_pass：k 次里过半「规则过 且 Judge 均分 ≥ 阈值」
      规则能测"对不对"，Judge 才能测"说得好不好"。只看规则会出现
      "数字抄对但解释全是脑补"也算通过的情况——所以必须分开统计。

    注意：过半阈值用 (k+1)//2，k=1 时是 1。原代码写死 >=2，
    传 k=1 会永远判失败。
    """
    results = [run_case(case, run_index=i) for i in range(k)]
    need = max(1, (k + 1) // 2)

    passes = sum(1 for r in results if r["overall_ok"])
    strict_passes = sum(
        1
        for r in results
        if r["overall_ok"] and _judge_avg(r) >= JUDGE_PASS_THRESHOLD
    )

    return {
        **results[0],
        "stable_pass": passes >= need,
        "strict_pass": strict_passes >= need,
        "flaky": 0 < passes < k,
        "pass_rate": passes / k,
        "strict_rate": strict_passes / k,
        "judge_avg": round(sum(_judge_avg(r) for r in results) / k, 2),
        "runs_detail": [  # 每次运行的死因
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
