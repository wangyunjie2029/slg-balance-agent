"""构建「核心评测集」：数量做减法，类型做加法。

为什么需要：
    全量 1217 条里，595 条 compare + 505 条 extreme 本质是同一个模式的重复。
    测 595 次「比大小」和测 15 次发现的问题类型完全一样，但成本是 40 倍。
    而真正有区分度的 90 条 balanced 必须全保留。

    核心集的构成原则：
      - E 系列（多轮/注入/拒绝/工具异常/边界）：全保留 —— 类型覆盖
      - R 系列（手工设计用例）：全保留
      - G 系列 balanced（均势）：全保留 —— 这是区分度来源
      - G 系列 other（克制查询）：全保留（量少）
      - G 系列 extreme / compare：各抽 15 条做代表 —— 只留信号，不留冗余

用法：
    python build_core_set.py                 # 输出 eval_cases_core.json
    python eval_report.py --cases eval_cases_core.json --k 3
"""

import json
import random
from collections import Counter

EXTREME_SAMPLE = 15
COMPARE_SAMPLE = 15
SEED = 42


def classify(case: dict) -> str:
    """按真值难度分类。与 eval_report._stratify 保持同一套口径。"""
    facts = case.get("expected_facts") or {}
    wr = facts.get("win_rate")
    if wr is not None:
        return "balanced" if 0.2 < wr < 0.8 else "extreme"
    if "power_a" in facts or "power_b" in facts:
        return "compare"
    return "other"


def main() -> None:
    cases = json.load(open("eval_cases.json", encoding="utf-8"))

    keep: list[dict] = []
    buckets: dict[str, list[dict]] = {
        "balanced": [],
        "extreme": [],
        "compare": [],
        "other": [],
    }
    manual = 0
    extra = 0

    for c in cases:
        cid = c["case_id"]
        if not cid.startswith("G"):
            keep.append(c)  # R 系列 + E 系列：全保留
            if cid.startswith("E"):
                extra += 1
            else:
                manual += 1
        else:
            buckets[classify(c)].append(c)

    random.seed(SEED)
    core = list(keep)
    core += buckets["balanced"]  # 全保留
    core += buckets["other"]  # 全保留

    ext = random.sample(buckets["extreme"], min(EXTREME_SAMPLE, len(buckets["extreme"])))
    cmp_ = random.sample(buckets["compare"], min(COMPARE_SAMPLE, len(buckets["compare"])))
    core += ext + cmp_

    # 按 case_id 排序，保证可复现
    core.sort(key=lambda c: c["case_id"])

    json.dump(
        core, open("eval_cases_core.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2
    )

    # ---------- 报告 ----------
    print(f"全量 {len(cases)} 条 → 核心集 {len(core)} 条（减少 {1 - len(core) / len(cases):.0%}）")
    print()
    print("构成：")
    print(f"  手工设计 (R)      {manual}")
    print(f"  补充类型 (E)      {extra}")
    print(f"  均势 (G-balanced) {len(buckets['balanced'])}   全保留")
    print(f"  克制 (G-other)    {len(buckets['other'])}    全保留")
    print(f"  一边倒 (G-extreme){len(ext):>3}/{len(buckets['extreme'])}  抽样")
    print(f"  比大小 (G-compare){len(cmp_):>3}/{len(buckets['compare'])}  抽样")

    cats = Counter(c.get("category", "?") for c in core)
    print()
    print("类型覆盖（这才是核心集的价值）：")
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {k:<14} {v:>4}")

    print()
    print(f"已写入 eval_cases_core.json　（跑 K=3 约 {len(core) * 3} 次调用）")


if __name__ == "__main__":
    main()
