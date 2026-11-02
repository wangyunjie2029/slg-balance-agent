"""
评测报告：跑一批 → 落盘 → 归因 → A/B 对比。

为什么单独一个文件：
    eval_runner 负责「跑一条用例」，本文件负责「跑一批 + 出结论 + 比差异」。
    它存在的唯一理由，是回答面试必问的那个问题：
    **「你改了什么之后，指标怎么变的？」**

用法：
    # 跑全量，存基线
    python eval_report.py --out reports/baseline.json

    # 改完 prompt / 工具描述后再跑一次，和基线对比
    python eval_report.py --out reports/after.json --baseline reports/baseline.json

    # 快速验证（只跑前 5 条，K=1）
    python eval_report.py --limit 5 --k 1
"""

import argparse
import json
import os
import sys
import time

from config import summary as config_summary
from eval_attribution import JUDGE_THRESHOLD, aggregate, attribute, render_report
from eval_runner import run_case_stable


def load_cases(path: str = "eval_cases.json") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def filter_by_difficulty(cases: list[dict], only: str) -> list[dict]:
    """按真值难度筛选用例。

    为什么需要：全量 1217 条里均衡对局只占 7%，随机抽样大概率抽不到。
    想测真实能力就必须「只跑均势用例」——那才是模型必须说准
    「接近平衡」并给出细微差距的地方。
    """
    if only == "all":
        return cases

    out: list[dict] = []
    for c in cases:
        facts = c.get("expected_facts") or {}
        wr = facts.get("win_rate")
        if only == "balanced":
            if wr is not None and 0.2 < wr < 0.8:
                out.append(c)
        elif only == "extreme":
            if wr is not None and (wr <= 0.2 or wr >= 0.8):
                out.append(c)
        elif only == "compare":
            if wr is None and ("power_a" in facts or "power_b" in facts):
                out.append(c)
    return out


def load_progress(path: str) -> dict[str, dict]:
    """读已完成的结果（断点续跑用）。文件不存在返回空 dict。"""
    if not os.path.exists(path):
        return {}
    done: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                done[row["case_id"]] = row
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def run_all(
    cases: list[dict],
    k: int = 3,
    quiet: bool = False,
    progress_path: str = "",
    done: dict[str, dict] | None = None,
) -> list[dict]:
    """跑所有用例，返回结果列表。每条内部已含稳定性判定（K 次）。

    两个工程要点（上一次跑 49 分钟没结果就是缺了它们）：
    1. progress_path：每跑完一条就追加一行 JSON —— 中断也只损失当前这条，
       而不是整批；同时可以用 `wc -l 文件` 实时看进度。
    2. done：已完成的结果直接复用，不重跑。
    """
    done = done or {}
    results: list[dict] = []
    total = len(cases)
    skipped = 0
    started = time.time()

    for i, case in enumerate(cases, 1):
        cid = case["case_id"]
        if cid in done:
            results.append(done[cid])
            skipped += 1
            continue

        # 单条失败不该让整批崩掉：45 分钟的批跑因为一次 402/超时/解析异常
        # 全部作废，是最没必要的损失（实测发生过：账户余额耗尽，175/193 处中断）。
        try:
            r = run_case_stable(case, k=k)
        except Exception as e:  # noqa: BLE001 - 批跑要吞掉一切单条异常
            msg = f"{type(e).__name__}: {e}"
            print(f"[{i}/{total}] ERROR {cid} — {msg[:140]}", flush=True)
            fatal = (
                "Insufficient Balance" in msg
                or "401" in msg
                or "402" in msg
                or "invalid_api_key" in msg
            )
            if fatal:
                print(
                    "\n检测到账户余额/鉴权问题：继续跑只会重复失败，已中止。"
                    f"\n已完成 {len(results)} 条，结果保留在 {progress_path or '内存'}；"
                    "问题解决后用同一命令重跑会自动跳过已完成项。",
                    flush=True,
                )
                break
            # 非致命（单条超时、偶发 5xx）：记一条 error 继续跑
            results.append(
                {
                    "case_id": cid,
                    "pass_rate": 0.0,
                    "stable_pass": False,
                    "strict_pass": False,
                    "flaky": False,
                    "judge_avg": None,
                    "tools_called": [],
                    "missing": [],
                    "answer_excerpt": f"ERROR {msg[:120]}",
                    "api_error": True,
                    "eligible": False,
                    "ineligible_reason": "API_ERROR",
                }
            )
            continue

        results.append(r)

        if progress_path:
            with open(progress_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

        if not quiet:
            mark = "PASS" if r["stable_pass"] else "FAIL"
            stab = "flaky" if r.get("flaky") else ""
            strict = "" if r.get("strict_pass") else " [strict FAIL]"
            elapsed = time.time() - started
            print(
                f"[{i}/{total}] {mark} {cid}"
                f" ({r['pass_rate']:.0%}) {stab}{strict}"
                f"　{elapsed:.0f}s",
                flush=True,
            )

    if skipped:
        print(f"（跳过已完成 {skipped} 条）", flush=True)
    return results


def _stratify(results: list[dict], cases: list[dict]) -> dict:
    """按真值难度分层统计通过率。

    为什么需要：如果 70% 的用例真值都是 0.0 或 1.0（一边倒的对局），
    模型只要说"压倒性胜利"就能过，这类用例的通过率高但**没有区分度**。
    真正能测出模型能力的是「均势对局」（0.2~0.8）——它要求模型准确说出
    "接近平衡"并给出细微差距。

    所以评测报告必须分开看：extreme 高不算本事，balanced 高才是。
    """
    by_id = {c["case_id"]: c for c in cases}
    buckets: dict[str, list[dict]] = {
        "extreme": [],
        "balanced": [],
        "compare": [],
        "other": [],
    }

    for r in results:
        case = by_id.get(r["case_id"], {})
        facts = case.get("expected_facts") or {}
        wr = facts.get("win_rate")
        if wr is not None:
            if wr <= 0.2 or wr >= 0.8:
                buckets["extreme"].append(r)
            else:
                buckets["balanced"].append(r)
        elif "power_a" in facts or "power_b" in facts:
            # 战力对比类：比大小，模型基本不会错，区分度也低
            buckets["compare"].append(r)
        else:
            buckets["other"].append(r)

    out = {}
    for name, rows in buckets.items():
        total = len(rows)
        passed = sum(1 for x in rows if x.get("stable_pass"))
        out[name] = {
            "total": total,
            "passed": passed,
            "pass_rate": round(passed / total, 3) if total else None,
        }
    return out


def concentration(by_kind: list) -> dict:
    """失败类型集中度：head 部分覆盖了多少失败量。

    为什么要有这个：只知道"11 类失败各几条"没法指导优化；要知道
    「top2 是否覆盖 60% 以上」——如果覆盖了，优化顺序就是算出来的，不是拍出来的。
    这是 CSI 论文 Figure 2 的思想在评测侧的平移（那边量的是增益集中度）。
    """
    counts = sorted(((k, c) for k, c in by_kind), key=lambda x: -x[1])
    total = sum(c for _, c in counts)
    rows, acc = [], 0
    for kind, c in counts:
        acc += c
        rows.append(
            {
                "kind": kind,
                "count": c,
                "share": round(c / total, 3) if total else 0.0,
                "cum_share": round(acc / total, 3) if total else 0.0,
            }
        )
    return {
        "rows": rows,
        "total": total,
        "top1_cover": rows[0]["share"] if rows else 0.0,
        "top2_cover": (
            rows[1]["cum_share"] if len(rows) > 1 else (rows[0]["cum_share"] if rows else 0.0)
        ),
    }


def build_report(
    results: list[dict], cases: list[dict], k: int, cases_path: str
) -> dict:
    """把原始结果整理成可对比的报告。"""
    by_id = {c["case_id"]: c for c in cases}
    rows = []
    for r in results:
        case = by_id.get(r["case_id"], {"case_id": r["case_id"]})
        # 口径对齐：稳定失败的用例，用"真的失败那一次"去做归因；
        # 通过了就用主结果。混用会导致"通过了却被归因成失败"。
        attr_input = r if r.get("stable_pass", True) else (r.get("fail_run") or r)
        rows.append(attribute(case, attr_input))

    summary = aggregate(rows)

    # 稳定性：flaky 比稳定失败更危险，要单独统计
    flaky = [r["case_id"] for r in results if r.get("flaky")]
    stable_fail = [
        r["case_id"]
        for r in results
        if not r.get("stable_pass") and not r.get("flaky")
    ]

    steps = [r.get("steps", 0) for r in results if r.get("steps") is not None]

    # ---- 分母治理：谁有资格进入通过率（Project1/59 第 2 条）----
    # 口径：只剔除"记录不可用"（空回答、超时、内部错误、API 错），不剔除"模型答错"。
    ineligible = [
        {"case_id": r["case_id"], "reason": r.get("ineligible_reason") or "UNKNOWN"}
        for r in results
        if not r.get("eligible", True)
    ]
    ineligible_ids = {x["case_id"] for x in ineligible}
    eligible_rows = [r for r in results if r["case_id"] not in ineligible_ids]
    eligible_passed = sum(1 for r in eligible_rows if r["stable_pass"])

    # ---- 逐轮判定（Project1/61 Phase 1：只测量，不改判定）----
    turn_checked = [r for r in results if r.get("turn_aligned") is not None]
    turn_misaligned = [r["case_id"] for r in turn_checked if not r.get("turn_aligned")]

    # ---- 第二指标：工具错误率 ----
    # 为什么要和通过率并列：CSI 的消融表里，删掉一个组件时成功率只掉 3 个点，
    # 但非法/工具错误率几乎翻倍（5.8→9.4）。只看通过率会低估"少犯错"的价值。
    tool_error_cases = [r["case_id"] for r in eligible_rows if r.get("error_codes")]

    # 供 cases 明细复用，避免在里面写 O(n²) 的查找
    stable_map = {r["case_id"]: r.get("stable_pass") for r in results}
    strict_map = {r["case_id"]: r.get("strict_pass") for r in results}

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cases_path": cases_path,
        "k": k,
        "config": config_summary(),
        "total": len(results),
        "eligible": len(eligible_rows),
        "ineligible": ineligible,
        "pass_rate_eligible": round(eligible_passed / len(eligible_rows), 3)
        if eligible_rows
        else 0.0,
        "tool_error_cases": tool_error_cases,
        "tool_error_rate": round(len(tool_error_cases) / len(eligible_rows), 3)
        if eligible_rows
        else 0.0,
        "turn_checked": len(turn_checked),
        "turn_aligned_n": len(turn_checked) - len(turn_misaligned),
        "turn_misaligned_cases": turn_misaligned,
        "failure_concentration": concentration(summary["by_kind"]),
        "passed": sum(1 for r in results if r["stable_pass"]),
        "pass_rate": summary["pass_rate"],
        "strict_passed": sum(1 for r in results if r.get("strict_pass")),
        "strict_pass_rate": round(
            sum(1 for r in results if r.get("strict_pass")) / len(results), 3
        )
        if results
        else 0.0,
        "avg_judge": round(
            sum(r.get("judge_avg", 0.0) for r in results) / len(results), 2
        )
        if results
        else 0.0,
        "flaky_cases": flaky,
        "stable_fail_cases": stable_fail,
        "avg_steps": round(sum(steps) / len(steps), 2) if steps else 0.0,
        "failure_by_kind": summary["by_kind"],
        "failure_by_owner": summary["by_owner"],
        "top_action": summary["top_action"],
        "stratified": _stratify(results, cases),
        "cases": [
            {
                "case_id": r.case_id,
                "passed": r.passed,
                # 三个口径同时记，避免"cases.passed 是第 0 次运行、头条是多数票"的老问题
                "stable_pass": bool(stable_map.get(r.case_id, r.passed)),
                "strict_pass": bool(strict_map.get(r.case_id, False)),
                "primary": r.primary.kind if r.primary else None,
                "evidence": r.primary.evidence if r.primary else "",
            }
            for r in rows
        ],
        "rendered": render_report(summary, rows),
    }


def save_report(report: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def load_report(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _case_pass_map(report: dict) -> dict:
    """case_id → 是否通过。

    优先用 stable_pass（K 次多数票，与头条口径一致）；
    老报告没有这个字段时退回 passed（第 0 次运行），并在注释里说明差异来源。
    """
    out = {}
    for c in report.get("cases") or []:
        if "stable_pass" in c:
            out[c["case_id"]] = bool(c["stable_pass"])
        else:
            out[c["case_id"]] = bool(c.get("passed"))
    return out


def guard_breaks(baseline: dict, current: dict) -> list[str]:
    """守护组被打破的用例：基线稳定通过、两次都不 flaky、现在挂了。

    为什么剔 flaky：一会儿过一会儿挂的用例，本身就不该当"守护者"——
    它挂掉多半是噪声，不是改动造成的。把它算进去，门禁会天天误报。
    """
    base_map = _case_pass_map(baseline)
    cur_map = _case_pass_map(current)
    noisy = set(baseline.get("flaky_cases") or []) | set(current.get("flaky_cases") or [])
    return sorted(
        cid
        for cid in base_map
        if base_map[cid] and cid in cur_map and cid not in noisy and not cur_map[cid]
    )


def mcnemar_exact(b: int, c: int) -> float:
    """配对二分类的精确检验（McNemar，双尾）。

    只统计"不一致的格子"：b = 基线过、现在挂；c = 基线挂、现在过。
    两边都过或都挂的 case 不提供信息——这正是配对设计比"比总体通过率"
    省一个量级样本的原因，也是 CSI 论文"同状态比较"的统计版。
    """
    from math import comb

    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 2 * sum(comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, p)


def compare(baseline: dict, current: dict) -> str:
    """输出 A/B 差异。这是「改动有没有用」的唯一证据。"""
    lines = ["=" * 52, "对比：baseline → current", "=" * 52]

    def line(label, a, b, fmt="{:.3f}", unit=""):
        delta = b - a
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"{label:<12} {fmt.format(a):>8} → {fmt.format(b):>8}  "
            f"({sign}{delta:.3f}{unit})"
        )

    line("通过率", baseline["pass_rate"], current["pass_rate"], "{:.1%}")
    line("平均步数", baseline["avg_steps"], current["avg_steps"], "{:.2f}")
    line(
        "flaky 数",
        float(len(baseline["flaky_cases"])),
        float(len(current["flaky_cases"])),
        "{:.0f}",
    )

    # ---- 配对口径统一 ----
    # 只比"两次都跑过的 case"，用 stable_pass 判；这样下面的结论、回归清单、
    # 配对检验、守护组门禁四处用的是同一套口径（以前四处各算各的，会自相矛盾）。
    base_map = _case_pass_map(baseline)
    cur_map = _case_pass_map(current)
    common = sorted(set(base_map) & set(cur_map))
    fixed = [cid for cid in common if not base_map[cid] and cur_map[cid]]
    broken = [cid for cid in common if base_map[cid] and not cur_map[cid]]
    fixed_n, regressed_n = len(fixed), len(broken)

    lines += ["", f"修好了 {fixed_n} 条：{', '.join(fixed) if fixed else '无'}"]
    lines += [f"回归了 {regressed_n} 条：{', '.join(broken) if broken else '无'}"]

    # 统计检验要剔掉 flaky：同一条用例一会儿过一会儿挂，不是改动的功劳或罪过，
    # 放进检验里只会稀释效应量。所以"配对检验"和"守护组"都用干净集。
    noisy = set(baseline.get("flaky_cases") or []) | set(current.get("flaky_cases") or [])
    clean = [cid for cid in common if cid not in noisy]
    fixed_clean = sum(1 for cid in clean if not base_map[cid] and cur_map[cid])
    regressed_clean = sum(1 for cid in clean if base_map[cid] and not cur_map[cid])
    p_val = mcnemar_exact(regressed_clean, fixed_clean)
    flipped_noise = (set(fixed) | set(broken)) & noisy

    lines += [
        "",
        f"配对表（剔除 flaky 后 {len(clean)} 条）：修好 {fixed_clean} / 回归 "
        f"{regressed_clean}　McNemar p={p_val:.3f}",
    ]
    if flipped_noise:
        lines.append(
            f"  另有 {len(flipped_noise)} 条 flaky 用例结果翻转"
            f"（{'、'.join(sorted(flipped_noise))}），属噪声，未计入检验"
        )
    if fixed_clean + regressed_clean == 0 and not flipped_noise:
        lines.append("  → 两边完全一致：这次改动没有改变任何一条用例的结果。")
    elif p_val >= 0.05:
        lines.append("  → 差异不显著（p≥0.05）：样本量不足以证明有效，别急着下结论。")

    # ---- 守护组：基线稳定通过、且两次都不 flaky 的 case，一票否决 ----
    guard = [cid for cid in clean if base_map[cid]]
    guard_broken = [cid for cid in guard if not cur_map[cid]]
    lines += [
        "",
        f"守护组 {len(guard)} 条（基线全过）→ 回归 {len(guard_broken)} 条"
        + ("　★ 一票否决：先修好再谈改进" if guard_broken else "　✓ 通过"),
    ]

    # 失败类型变化：看改的是不是对的那一层
    base_kind = dict(baseline["failure_by_kind"])
    cur_kind = dict(current["failure_by_kind"])
    all_kinds = sorted(set(base_kind) | set(cur_kind))
    if all_kinds:
        lines += ["", "失败类型变化："]
        for k in all_kinds:
            a, b = base_kind.get(k, 0), cur_kind.get(k, 0)
            flag = " ↓" if b < a else (" ↑" if b > a else "")
            lines.append(f"  {k:<24} {a:>3} → {b:>3}{flag}")

    # 给一句结论（与守护组同口径，避免"上面说回归 2 条、下面说零回归"）
    if guard_broken:
        verdict = f"本次改动有回归（{len(guard_broken)} 条），先回滚或定位再谈改进。"
    elif fixed_clean and p_val < 0.05:
        verdict = f"有效：修复 {fixed_clean} 条（p={p_val:.3f}），守护组通过。"
    elif fixed_clean:
        verdict = (
            f"方向对但证据不足：仅修复 {fixed_clean} 条（p={p_val:.3f}），"
            "扩样本再下结论。"
        )
    elif current["pass_rate"] == baseline["pass_rate"]:
        verdict = "指标没变化 —— 说明改的那一层不是瓶颈，先看归因的 top_action。"
    else:
        verdict = "指标下降，建议先回滚再定位。"

    lines += ["", f"结论：{verdict}"]
    return "\n".join(lines)


def render_stratified(st: dict) -> str:
    """把分层统计渲染成可读段落。"""
    label = {
        "extreme": "一边倒(≤20%或≥80%)",
        "balanced": "均势(20%~80%)",
        "compare": "战力对比(比大小)",
        "other": "无真值(路由类)",
    }
    lines = ["分层通过率（区分度主要看 balanced）："]
    for key in ("extreme", "balanced", "compare", "other"):
        d = st.get(key) or {}
        if not d.get("total"):
            continue
        rate = f"{d['pass_rate']:.1%}" if d["pass_rate"] is not None else "-"
        lines.append(f"  {label[key]:<24} {d['passed']:>3}/{d['total']:<4} {rate:>7}")

    bal = st.get("balanced") or {}
    rate = bal.get("pass_rate")
    if rate is not None and rate < 0.6:
        lines.append(
            "  提醒：均势用例通过率低于 60% —— 这才是模型真实能力的短板，"
            "优先看这部分的失败归因。"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="跑评测并生成可对比的报告")
    ap.add_argument("--cases", default="eval_cases.json")
    ap.add_argument("--k", type=int, default=3, help="每条用例运行次数")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全跑）")
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="随机抽 N 条（固定 seed 可复现；比 --limit 更有代表性）",
    )
    ap.add_argument("--out", default="", help="报告输出路径（不填则不落盘）")
    ap.add_argument("--baseline", default="", help="基线报告路径，填了就做对比")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--seed", type=int, default=42, help="抽样用的随机种子")
    ap.add_argument(
        "--progress",
        default="",
        help="进度文件（JSONL）。每跑完一条追加一行，中断后可用同路径续跑",
    )
    ap.add_argument(
        "--only",
        default="all",
        choices=["all", "balanced", "extreme", "compare"],
        help="只跑某一难度层（balanced = 均势对局，最有区分度）",
    )
    ap.add_argument(
        "--category",
        default="",
        help="只跑某一类（如 multiturn / tool_error），空=全部。"
        "用途：改逐轮判定时只重跑 17 条多轮，5 分钟而不是 40 分钟",
    )
    ap.add_argument(
        "--multi-turn",
        action="store_true",
        help="只跑多轮用例（question 是列表且长度>1）。"
        "注意：多轮用例散落在 multiturn/routing/numeric 三类里，只按 --category 会漏",
    )
    ap.add_argument(
        "--allow-regression",
        action="store_true",
        help="守护组出现回归时仍然以 0 退出（默认非零退出，用于拦截）",
    )
    args = ap.parse_args()

    cases = load_cases(args.cases)
    if args.category:
        before = len(cases)
        cases = [c for c in cases if c.get("category") == args.category]
        print(f"按类型筛选 [{args.category}]：{before} → {len(cases)} 条")
    if args.multi_turn:
        before = len(cases)
        cases = [
            c
            for c in cases
            if isinstance(c.get("question"), list) and len(c["question"]) > 1
        ]
        print(f"只跑多轮：{before} → {len(cases)} 条")
    if args.only != "all":
        before = len(cases)
        cases = filter_by_difficulty(cases, args.only)
        print(f"按难度筛选 [{args.only}]：{before} → {len(cases)} 条")
    if args.sample:
        # 随机抽样比"取前 N 条"更代表整体：eval_cases.json 是手工用例在前、
        # 自动生成在后，直接切片会拿到偏简单的手工集，得出过于乐观的结论。
        import random

        random.seed(args.seed)
        cases = random.sample(cases, min(args.sample, len(cases)))
        print(f"随机抽样 {len(cases)} 条（seed={args.seed}）")
    elif args.limit:
        cases = cases[: args.limit]

    print(f"用例 {len(cases)} 条 × K={args.k} = {len(cases) * args.k} 次运行")
    done = load_progress(args.progress) if args.progress else {}
    if done:
        print(f"检测到进度文件，已完成 {len(done)} 条，将跳过它们")
    results = run_all(
        cases, k=args.k, quiet=args.quiet, progress_path=args.progress, done=done
    )
    report = build_report(results, cases, args.k, args.cases)

    print()
    print(report["rendered"])
    print()
    print(
        f"规则通过 {report['passed']}/{report['total']}"
        f"　严格通过（含 Judge≥{JUDGE_THRESHOLD}）"
        f"{report['strict_passed']}/{report['total']}"
        f"　Judge 均分 {report['avg_judge']}"
    )

    # 双分母：合格集口径 + 剔除清单（分母治理）
    ineligible = report.get("ineligible") or []
    print(
        f"合格集 {report['eligible']}/{report['total']}"
        f"　合格集通过率 {report['pass_rate_eligible']:.1%}"
        + (
            "　剔除："
            + "、".join(f"{x['case_id']}({x['reason']})" for x in ineligible[:6])
            + ("…" if len(ineligible) > 6 else "")
            if ineligible
            else "　未被剔除任何用例"
        )
    )
    # 第二指标：工具错误率（和通过率并列看，别只看"涨了多少分"）
    te = report.get("tool_error_cases") or []
    print(
        f"工具错误 {len(te)}/{report['eligible']}（{report.get('tool_error_rate', 0):.1%}）"
        + (f"　{'、'.join(te[:6])}{'…' if len(te) > 6 else ''}" if te else "")
    )

    # 逐轮判定：只测量，不改判定（Phase 1）
    if report.get("turn_checked"):
        mis = report.get("turn_misaligned_cases") or []
        print(
            f"逐轮对齐 {report['turn_aligned_n']}/{report['turn_checked']}"
            + (f"　错位：{'、'.join(mis)}" if mis else "　无错位")
        )

    # 失败集中度：top-k 覆盖率决定优化顺序
    conc = report.get("failure_concentration") or {}
    if conc.get("total"):
        print(
            f"失败集中度：top1 {conc['top1_cover']:.0%}　"
            f"top2 {conc['top2_cover']:.0%}（共 {conc['total']} 条失败）"
        )
        for row in conc["rows"][:4]:
            print(
                f"  {row['kind']:<22}{row['count']:>3} 条　"
                f"占比 {row['share']:.0%}　累积 {row['cum_share']:.0%}"
            )
        if conc["top2_cover"] >= 0.6:
            print("  → 头部两类已覆盖多数失败：先改这两类，长尾暂缓。")

    print()
    print(render_stratified(report["stratified"]))

    if args.out:
        save_report(report, args.out)
        print(f"\n报告已保存：{args.out}")

    if args.baseline:
        base = load_report(args.baseline)
        print()
        print(compare(base, report))

        # 守护组门禁：基线稳定通过的用例一旦回归，就非零退出（可被 --allow-regression 放行）
        if not args.allow_regression:
            broken = guard_breaks(base, report)
            if broken:
                print(
                    f"\n[门禁] 守护组回归 {len(broken)} 条：{', '.join(broken)}\n"
                    "       按约定应阻断；确认可接受再用 --allow-regression 重跑。"
                )
                sys.exit(1)


if __name__ == "__main__":
    main()
