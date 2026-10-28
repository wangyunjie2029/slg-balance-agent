"""Judge 校准：用「锚点集」验证 LLM 评审官是否可信。

为什么需要这个文件
------------------
eval_attribution 里 JUDGE_THRESHOLD = 6.0 是拍出来的。面试官只要问一句
「你怎么知道 Judge 打的分是准的？」，答不出来整段评测就不可信。

校准的标准做法（不是本项目发明的，是评价学里的通用方法）：
  1. 造一批**已知好坏**的样本（金标）
  2. 让 Judge 打分
  3. 看 Judge 的判定与金标的一致率 —— 一致率低，说明 Judge 不可用

本项目的锚点集构造方式
----------------------
取 6 个真实问题，每个问题配 4 个答案变体，共 24 条：

  clean      完全正确：数字来自引擎、因果有依据、结论方向一致
  num_err    数字错：故意改错胜率/战力，且与结论自相矛盾
  missing    缺要点：只给定性结论，不给任何数字
  fabricated 编造因果：数字对，但把机制说错（如"枪兵免疫骑兵伤害"）

金标只有两档（可接受 / 不可接受），因为真实使用场景里 Judge 只用来
做一道是非题（strict_pass 需要它），不是给人打审美分。

指标
----
- 一致率（accuracy）：Judge 判定 == 金标 的比例
- 精确率/召回率：把"不可接受"当正类（这是防护场景里更贵的一侧）
- 逐维度贡献：哪一类缺陷是靠哪个维度抓到的 —— 决定阈值该怎么用

产出
----
reports/judge-calibration.json
"""

import json
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from battle import Army  # noqa: E402
from combat import calc_army_power  # noqa: E402
from config import DAMAGE_JITTER, SIM_N, SIM_SEED  # noqa: E402
from data import GENERALS, UNITS  # noqa: E402
from eval_judge import judge_answer  # noqa: E402
from mc_sim import run_mc_sim  # noqa: E402
from troops import COUNTER  # noqa: E402

OUT = Path("reports/judge-calibration.json")

CANDIDATE_THRESHOLDS = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]


def _rate(ga: str, ta: str, gb: str, tb: str) -> float:
    return run_mc_sim(
        Army(UNITS[ta], GENERALS[ga], ta),
        Army(UNITS[tb], GENERALS[gb], tb),
        n=SIM_N,
        damage_jitter=DAMAGE_JITTER,
        seed=SIM_SEED,
    ).win_rate_a


def build_samples() -> list[dict]:
    """用引擎真实数据造锚点。数字全部现算，不手写，避免锚点本身过期。"""
    r1 = _rate("张飞", "骑兵", "关羽", "枪兵")
    r2 = _rate("张飞", "骑兵", "袁绍", "盾兵")
    r3 = _rate("张飞", "骑兵", "袁绍", "弓兵")
    p_zf = calc_army_power(UNITS["骑兵"], GENERALS["张飞"], "骑兵")
    p_gy = calc_army_power(UNITS["骑兵"], GENERALS["关羽"], "骑兵")
    counters = COUNTER.get("骑兵", [])
    q1 = "张飞带骑兵打关羽带枪兵，胜率多少？"
    q2 = "张飞带骑兵和关羽带骑兵，哪个战力更高？"
    q3 = "骑兵克制哪些兵种？"
    q4 = "张飞带骑兵打袁绍的盾兵和弓兵，哪个胜率更高？"
    q5 = "帮我诊断一下现在的数值平衡问题。"
    q6 = "今天上海天气怎么样？"

    s = []

    # ---------- Q1 对战胜率 ----------
    s += [
        dict(
            id="C1-clean",
            question=q1,
            answer=(
                f"模拟 500 局的结果：张飞骑兵方胜率 {r1:.1%}，即 {round(r1 * SIM_N)} 胜 "
                f"{SIM_N - round(r1 * SIM_N)} 负。张飞骑兵被枪兵克制，攻防两端都被压制，"
                "因此明显处于劣势。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C1-num_err",
            question=q1,
            answer=(
                "模拟结果显示张飞骑兵方胜率 63.0%，处于明显优势。原因是骑兵机动性更强、"
                "能先手压制枪兵。"
            ),
            gold="bad",
            defect="numeric_error",
        ),
        dict(
            id="C1-missing",
            question=q1,
            answer="张飞处于劣势，主要因为兵种被克制。",
            gold="bad",
            defect="missing_number",
        ),
        dict(
            id="C1-fabricated",
            question=q1,
            answer=(
                f"胜率 {r1:.1%}。原因是枪兵对骑兵的伤害完全免疫，骑兵冲锋的伤害全部被抵消，"
                "而且张飞的武力值低于关羽，所以必败。"
            ),
            gold="bad",
            defect="fabricated_causality",
        ),
    ]

    # ---------- Q2 战力比较 ----------
    winner = "张飞" if p_zf >= p_gy else "关羽"
    s += [
        dict(
            id="C2-clean",
            question=q2,
            answer=(
                f"计算结果是张飞骑兵战力 {p_zf:.1f}，关羽骑兵 {p_gy:.1f}，"
                f"{winner}更高，差距 {abs(p_zf - p_gy):.1f}。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C2-num_err",
            question=q2,
            answer="张飞骑兵战力 412.5，关羽骑兵 655.8，所以关羽明显更高。",
            gold="bad",
            defect="numeric_error",
        ),
        dict(
            id="C2-missing",
            question=q2,
            answer=f"{winner}的战力更高一些。",
            gold="bad",
            defect="missing_number",
        ),
        dict(
            id="C2-swapped",
            question=q2,
            answer=(
                f"张飞骑兵战力 {p_zf:.1f}，关羽骑兵 {p_gy:.1f}，"
                f"所以{'关羽' if winner == '张飞' else '张飞'}更高。"
            ),
            gold="bad",
            defect="wrong_conclusion",
        ),
    ]

    # ---------- Q3 克制关系 ----------
    s += [
        dict(
            id="C3-clean",
            question=q3,
            answer=f"骑兵克制：{'、'.join(counters)}。这是兵种表里的固定关系，非推测。",
            gold="ok",
            defect="none",
        ),
        dict(
            id="C3-wrong",
            question=q3,
            answer="骑兵克制枪兵和盾兵，被弓兵克制。",
            gold="bad",
            defect="factual_error",
        ),
        dict(
            id="C3-vague",
            question=q3,
            answer="骑兵比较灵活，能克制一些机动性差的兵种。",
            gold="bad",
            defect="missing_number",
        ),
        dict(
            id="C3-fabricated",
            question=q3,
            answer=(
                f"骑兵克制：{'、'.join(counters)}。原因是在真实三国战场上，"
                "骑兵的冲锋能直接冲散步兵方阵，历史上吕布就是靠这个取胜的。"
            ),
            gold="bad",
            defect="fabricated_causality",
        ),
    ]

    # ---------- Q4 多目标对比（模型最容易只答一半） ----------
    s += [
        dict(
            id="C4-clean",
            question=q4,
            answer=(
                f"两场都跑了 500 局：对盾兵胜率 {r2:.1%}，对弓兵胜率 {r3:.1%}。"
                f"所以对{'弓兵' if r3 > r2 else '盾兵'}更高。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C4-half",
            question=q4,
            answer=f"对盾兵的胜率是 {r2:.1%}，盾兵防御高，所以打起来比较吃力。",
            gold="bad",
            defect="missing_required",  # 只答了一个目标
        ),
        dict(
            id="C4-num_err",
            question=q4,
            answer="对盾兵胜率 45.0%，对弓兵胜率 30.0%，所以打盾兵更有利。",
            gold="bad",
            defect="numeric_error",
        ),
        dict(
            id="C4-fabricated",
            question=q4,
            answer=(
                f"对盾兵 {r2:.1%}，对弓兵 {r3:.1%}。主要因为弓兵在近战时会自动溃散，"
                "所以任何骑兵打弓兵都是稳赢。"
            ),
            gold="bad",
            defect="fabricated_causality",
        ),
    ]

    # ---------- Q5 诊断类（应该跑矩阵，而不是凭感觉） ----------
    s += [
        dict(
            id="C5-clean",
            question=q5,
            answer=(
                "跑了全兵种对阵矩阵并用 Z-score 检测：器械胜率显著偏低（对多数兵种低于 20%），"
                "属于过弱；骑兵对盾兵的优势超出合理区间。建议先调 DAMAGE_FACTOR，"
                "再做一轮复诊确认。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C5-missing",
            question=q5,
            answer="目前数值还算平衡，各兵种都有各自优势，建议继续观察。",
            gold="bad",
            defect="missing_number",
        ),
        dict(
            id="C5-fabricated",
            question=q5,
            answer=(
                "我凭经验判断：器械太弱，因为历史上攻城器械本来就不适合野战；"
                "弓兵太强，因为远程输出没有代价。"
            ),
            gold="bad",
            defect="fabricated_causality",
        ),
        dict(
            id="C5-offtopic",
            question=q5,
            answer="这个问题建议你去看一下官方的数值说明文档，或者联系策划同学确认。",
            gold="bad",
            defect="off_topic",
        ),
    ]

    # ---------- Q6 越界提问（应该拒绝，不应编造） ----------
    s += [
        dict(
            id="C6-clean",
            question=q6,
            answer=(
                "我无法查询天气，我的工具只覆盖 SLG 兵种、武将、克制与对战模拟这几块，"
                "没有接任何天气数据源。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C6-hallucinate",
            question=q6,
            answer="上海今天多云，气温 22~27 度，东南风 3 级，适合外出。",
            gold="bad",
            defect="hallucination",
        ),
        dict(
            id="C6-partial",
            question=q6,
            answer="上海今天应该挺热的，具体气温我不太确定，大概 25 度左右吧。",
            gold="bad",
            defect="hallucination",
        ),
        dict(
            id="C6-offtopic",
            question=q6,
            answer="天气对行军有影响，古代作战讲究天时，比如赤壁之战就是靠东南风。",
            gold="bad",
            defect="off_topic",
        ),
    ]
    # ---------- 对照组：同样是「正确」但风格不同 ----------
    # 目的：验证 Judge 不会因为回答简短/啰嗦/口语化就误杀。
    # 如果这几条被判成 bad，说明阈值定得太高，会冤枉真实的好回答。
    s += [
        dict(
            id="C1-clean-short",
            question=q1,
            answer=f"胜率 {r1:.1%}，张飞方劣势，原因是兵种被枪兵克制。",
            gold="ok",
            defect="none",
        ),
        dict(
            id="C2-clean-verbose",
            question=q2,
            answer=(
                f"我分别算了两边的阵容战力：张飞带骑兵是 {p_zf:.1f}，"
                f"关羽带骑兵是 {p_gy:.1f}。两边都是骑兵适性 S，所以差距主要来自武将六维。"
                f"结论是{winner}更高，差距 {abs(p_zf - p_gy):.1f}，属于同一档位，"
                "实战胜负还要看兵种克制和随机波动。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C3-clean-short",
            question=q3,
            answer=f"骑兵克制{'、'.join(counters)}（来自兵种表，非推测）。",
            gold="ok",
            defect="none",
        ),
        dict(
            id="C4-clean-structured",
            question=q4,
            answer=(
                "两项对比：\n"
                f"· 对盾兵：{r2:.1%}\n"
                f"· 对弓兵：{r3:.1%}\n"
                f"结论：对{'弓兵' if r3 > r2 else '盾兵'}更有利。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C5-clean-short",
            question=q5,
            answer=(
                "器械最弱（多数对局低于 20%），骑兵对盾兵优势偏大。"
                "建议先动 DAMAGE_FACTOR，再复诊一轮。"
            ),
            gold="ok",
            defect="none",
        ),
        dict(
            id="C6-clean-short",
            question=q6,
            answer="查不了，我没有天气数据源，只能回答 SLG 数值相关的问题。",
            gold="ok",
            defect="none",
        ),
    ]

    # ---------- 挂上参考事实 ----------
    # 这是校准实验的关键变量：不给真值时 Judge 无法识别「数字被改错」，
    # 给真值后它才有核对依据。每个问题对应的真值都由引擎现算。
    facts_by_q = {
        q1: {"A方胜率": round(r1, 3), "局数": SIM_N, "A方": "张飞带骑兵", "B方": "关羽带枪兵"},
        q2: {"张飞骑兵战力": round(p_zf, 1), "关羽骑兵战力": round(p_gy, 1)},
        q3: {
            "骑兵克制": counters,
            "来源": "克制关系是项目内数值表（COUNTER）的设定，不是由史料或现实战例推导的",
        },
        q4: {"对盾兵胜率": round(r2, 3), "对弓兵胜率": round(r3, 3)},
        q5: {"器械": "多数对局胜率低于 20%，属过弱", "骑兵对盾兵": "优势超出合理区间"},
        q6: {"可用工具范围": "兵种/武将/克制关系/对战模拟/战力计算/平衡诊断；无任何天气数据源"},
    }
    for x in s:
        x["facts"] = facts_by_q.get(x["question"], {})

    return s


def _mean(j: dict) -> float:
    return round(
        (j.get("faithfulness", 0) + j.get("completeness", 0) + j.get("appropriateness", 0))
        / 3,
        2,
    )


def evaluate(rows: list[dict]) -> dict:
    """在候选阈值上评估一致率，并把「金标 bad」当正类算精确率/召回率。"""
    n = len(rows)
    sweep = []
    for t in CANDIDATE_THRESHOLDS:
        tp = fp = tn = fn = 0
        for r in rows:
            pred_bad = r["judge_mean"] < t  # 分数低 → 判为不可接受
            gold_bad = r["gold"] == "bad"
            if pred_bad and gold_bad:
                tp += 1
            elif pred_bad and not gold_bad:
                fp += 1
            elif not pred_bad and gold_bad:
                fn += 1
            else:
                tn += 1
        acc = (tp + tn) / n
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        sweep.append(
            dict(
                threshold=t,
                accuracy=round(acc, 3),
                precision=round(prec, 3),
                recall=round(rec, 3),
                f1=round(f1, 3),
                tp=tp,
                fp=fp,
                tn=tn,
                fn=fn,
            )
        )

    # 阈值选择策略：优先「零误杀」，再比召回率。
    # 理由：误杀会把真实的好回答判成失败 → 既低估通过率，也会把改进方向带偏
    # （你会去改一个本来没问题的 prompt）。漏放只是让评测变宽松，代价小得多。
    # 只有在没有任何阈值能做到零误杀时，才退回按 F1 选。
    safe = [x for x in sweep if x["fp"] == 0]
    if safe:
        best = sorted(safe, key=lambda x: (-x["recall"], -x["f1"], x["threshold"]))[0]
        best["policy"] = "zero_false_positive"
    else:
        best = sorted(sweep, key=lambda x: (-x["f1"], x["threshold"]))[0]
        best["policy"] = "max_f1"

    # 逐缺陷类型：看 Judge 抓住了哪几类、漏了哪几类
    by_defect = defaultdict(lambda: {"total": 0, "caught": 0})
    for r in rows:
        if r["gold"] != "bad":
            continue
        d = by_defect[r["defect"]]
        d["total"] += 1
        if r["judge_mean"] < best["threshold"]:
            d["caught"] += 1

    # 维度贡献：clean 的均值 vs 各类缺陷的均值，看哪个维度区分度最大
    dim_stat = {}
    for dim in ("faithfulness", "completeness", "appropriateness"):
        clean = [r["judge"][dim] for r in rows if r["gold"] == "ok"]
        bad = [r["judge"][dim] for r in rows if r["gold"] == "bad"]
        dim_stat[dim] = dict(
            clean_avg=round(sum(clean) / len(clean), 2) if clean else None,
            bad_avg=round(sum(bad) / len(bad), 2) if bad else None,
            gap=round(sum(clean) / len(clean) - sum(bad) / len(bad), 2)
            if clean and bad
            else None,
        )

    return dict(
        n=n,
        sweep=sweep,
        best=best,
        by_defect={k: dict(v, rate=round(v["caught"] / v["total"], 2)) for k, v in by_defect.items()},
        dim_stat=dim_stat,
    )


def render(rows: list[dict], res: dict) -> str:
    lines = []
    lines.append("=" * 62)
    lines.append(f"Judge 校准报告（锚点集 {res['n']} 条：6 问 × 4 变体）")
    lines.append("=" * 62)
    lines.append("")
    lines.append("阈值扫描（金标 bad 当正类）：")
    lines.append(f"  {'阈值':<6}{'一致率':<8}{'精确率':<8}{'召回率':<8}{'F1':<7}误杀/漏放")
    for s in res["sweep"]:
        lines.append(
            f"  {s['threshold']:<6}{s['accuracy']:<8.3f}{s['precision']:<8.3f}"
            f"{s['recall']:<8.3f}{s['f1']:<7.3f}{s['fp']}/{s['fn']}"
        )
    b = res["best"]
    lines.append("")
    lines.append(
        f"→ 推荐阈值 {b['threshold']}：一致率 {b['accuracy']:.1%}，"
        f"误杀 {b['fp']} 条、漏放 {b['fn']} 条"
    )
    lines.append("")
    lines.append("按缺陷类型（Judge 是否抓住）：")
    for k, v in sorted(res["by_defect"].items()):
        flag = "✅" if v["rate"] == 1.0 else ("⚠️" if v["rate"] >= 0.5 else "❌")
        lines.append(f"  {flag} {k:<22} {v['caught']}/{v['total']}")
    lines.append("")
    lines.append("维度区分度（clean 均值 − bad 均值，越大越能分辨）：")
    for dim, v in res["dim_stat"].items():
        lines.append(f"  {dim:<18} clean {v['clean_avg']} / bad {v['bad_avg']} → 差 {v['gap']}")
    lines.append("")
    # 逐条明细，便于人工复核
    lines.append("逐条明细：")
    for r in rows:
        mark = "OK " if r["gold"] == "ok" else "BAD"
        pred = "判可接受" if r["judge_mean"] >= b["threshold"] else "判不可接受"
        hit = "✓" if (r["gold"] == "bad") == (r["judge_mean"] < b["threshold"]) else "✗"
        lines.append(
            f"  {hit} {r['id']:<16} 金标 {mark:<4} Judge {r['judge_mean']:<5} {pred}"
        )
    return "\n".join(lines)


def main() -> None:
    samples = build_samples()
    rows = []
    for i, s in enumerate(samples, 1):
        j = judge_answer(s["question"], s["answer"], facts=s.get("facts"))
        rows.append({**s, "judge": j, "judge_mean": _mean(j)})
        print(f"[{i}/{len(samples)}] {s['id']:<16} mean={rows[-1]['judge_mean']}", flush=True)

    res = evaluate(rows)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"summary": res, "rows": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print()
    print(render(rows, res))
    print()
    print(f"已落盘：{OUT}")


if __name__ == "__main__":
    main()
