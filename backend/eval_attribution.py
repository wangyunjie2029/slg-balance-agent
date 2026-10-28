"""
评测失败归因：把「哪条没过」升级成「为什么没过、该改哪里」。

为什么需要它：
    eval_runner 现在只告诉你 missing=['win_rate_a']，你改哪个 prompt？
    归因模块把失败映射成「失败类型 + 该改的组件 + 负责人」，这样每次迭代
    都有明确目标，而不是盲改 prompt。

用法：
    from eval_attribution import attribute, aggregate, render_report
    rows = [attribute(case, run_result) for ...]
    print(render_report(aggregate(rows)))

数据来源约定（重要）：
    attribute() 需要 case（用例定义）和 result（run_case_stable 的返回）两个 dict。
    result 里必须能拿到：
      - routing_ok / numeric_ok / negative_ok / contains_ok / tools_discipline_ok
      - tools_called: [str]             调过的工具名序列
      - answer_excerpt: str             回答前 80 字（判断是否幻觉用）
      - judge: {faithfulness, completeness, appropriateness}
    如果你要让归因更准，在 eval_runner 里额外记录（TODO，见文件末尾）。
"""

from collections import Counter
from dataclasses import dataclass, field

# ============================================================
# 1. 失败分类表：类型 → 根因组件 → 修法
#    这张表决定归因质量，比代码逻辑重要。想加类型就往这里加。
# ============================================================

TAXONOMY = {
    "INTENT_MISUNDERSTAND": {
        "desc": "没有调用任何工具，直接凭记忆回答",
        "component": "system prompt",
        "fix": "在 system prompt 里强化「涉及数据必须调工具」；或加 few-shot 示例",
        "owner": "prompt",
    },
    "WRONG_TOOL": {
        "desc": "调了工具但工具名或关键参数不对",
        "component": "工具描述 / 工具边界",
        "fix": "检查 description 是否说清了适用场景；考虑拆分或合并工具",
        "owner": "tool",
    },
    "WRONG_ARGUMENT": {
        "desc": "工具选对了，但参数值填错（指代解析错、A/B 方搞反）",
        "component": "prompt 指代解析 / few-shot",
        "fix": "给 1-2 个多轮指代的 few-shot；或要求模型先复述「你要比的是 X vs Y」再调用",
        "owner": "prompt",
    },
    "BAD_ARGUMENT": {
        "desc": "参数非法导致工具执行失败（不存在的武将/兵种名、缺字段）",
        "component": "JSON Schema / 参数描述",
        "fix": "在 description 里列出可选值；或加 enum 约束",
        "owner": "tool",
    },
    "TOOL_FAILURE": {
        "desc": "工具执行失败（超时 / 内部异常）",
        "component": "工具层",
        "fix": "加超时、重试、降级；检查引擎在大输入下的耗时",
        "owner": "tool",
    },
    "NUMERIC_MISS": {
        "desc": "工具调对了，但关键数字没出现在回答里",
        "component": "prompt / 结果注入",
        "fix": "要求回答必须引用工具返回的关键数字；考虑用模板渲染数字",
        "owner": "prompt",
    },
    "HALLUCINATION": {
        "desc": "回答里出现了数字，但与真值不符（复述失真或编造）",
        "component": "结果注入 / 数据源",
        "fix": "结构化返回 + 模板渲染；禁止模型自行换算或四舍五入",
        "owner": "data",
    },
    "FORBIDDEN_CONTENT": {
        "desc": "出现了不应出现的内容（越权承诺、编造机制）",
        "component": "system prompt",
        "fix": "加负面约束；对敏感表述做输出校验",
        "owner": "prompt",
    },
    "MISSING_REQUIRED": {
        "desc": "缺少必含要点（如未给出调整建议）",
        "component": "prompt 结构",
        "fix": "在 prompt 里规定回答结构（结论/依据/建议三段）",
        "owner": "prompt",
    },
    "TOOL_DISCIPLINE": {
        "desc": "调用了黑名单里的工具（越权/不该调）",
        "component": "工具权限",
        "fix": "按场景做工具白名单；在工具层加权限校验",
        "owner": "tool",
    },
    "LOOP_GUARD": {
        "desc": "触发重复调用检测或步数上限，被强制停机",
        "component": "停机条件 / 工具幂等",
        "fix": "检查工具结果是否让模型误判为失败；考虑返回更明确的成功信号",
        "owner": "orchestration",
    },
    "LOW_QUALITY": {
        "desc": "规则全过但 Judge 分低（常见：faithfulness 低 = 脑补因果）",
        "component": "prompt / 数据依据",
        "fix": "要求因果解释必须引用工具字段；禁止用通用常识解释机制",
        "owner": "prompt",
    },
}

# 严重度：决定修复优先级。工具层的错会污染下游，优先级最高。
SEVERITY = {
    "TOOL_DISCIPLINE": 3,
    "TOOL_FAILURE": 3,
    "BAD_ARGUMENT": 3,
    "WRONG_TOOL": 3,
    "WRONG_ARGUMENT": 3,
    "INTENT_MISUNDERSTAND": 3,
    "HALLUCINATION": 3,
    "LOOP_GUARD": 2,
    "NUMERIC_MISS": 2,
    "FORBIDDEN_CONTENT": 2,
    "MISSING_REQUIRED": 1,
    "LOW_QUALITY": 1,
}

# 归一化阈值：Judge 三项均值低于它就算质量问题
# 6.0 是经验值；核心集实测 Judge 均分 8.23，说明这个阈值偏宽松，
# 但**尚未与人工标注校准**，所以先不动 —— 未经校准的调参只是自欺。
# 归一化阈值：Judge 三项均值低于它就算质量问题。
# ★ 已校准（不是拍的）：eval_judge_calibration.py 用 30 条锚点样本
#   （6 问 × 5 变体：正确 / 数字错 / 缺要点 / 编造因果 / 越界）验证，
#   在 6.5 上一致率 30/30、零误杀零漏放（干净样本最低 8.33，缺陷样本最高 6.33）。
#   复现：python eval_judge_calibration.py → reports/judge-calibration.json
JUDGE_THRESHOLD = 6.5


@dataclass
class Finding:
    case_id: str
    kind: str
    evidence: str
    severity: int = 0
    owner: str = ""
    fix: str = ""

    def __post_init__(self):
        meta = TAXONOMY.get(self.kind, {})
        self.owner = self.owner or meta.get("owner", "unknown")
        self.fix = self.fix or meta.get("fix", "")


@dataclass
class Attribution:
    case_id: str
    passed: bool
    findings: list[Finding] = field(default_factory=list)

    @property
    def primary(self) -> Finding | None:
        """根因：取严重度最高的那条。同严重度按 TAXONOMY 顺序。"""
        if not self.findings:
            return None
        return max(self.findings, key=lambda f: f.severity)


# ============================================================
# 2. 归因主逻辑
# ============================================================


def attribute(case: dict, result: dict) -> Attribution:
    """把一条评测结果翻译成「失败类型 + 修法」。

    判定顺序很重要：先判"上游"（工具有没有调对），再判"下游"（数字/表达）。
    因为上游错了，下游的错只是症状，不是根因。
    """
    cid = case.get("case_id", result.get("case_id", "?"))
    tools = result.get("tools_called") or []
    answer = result.get("answer_excerpt") or ""
    findings: list[Finding] = []

    # ---------- 上游：工具层 ----------
    if not result.get("routing_ok", True):
        if not tools:
            findings.append(
                Finding(cid, "INTENT_MISUNDERSTAND", "expected tools but none called")
            )
        else:
            # 关键区分：工具名对上过吗？
            #   名字对上但整体不匹配 → 参数值填错（WRONG_ARGUMENT）
            #   名字都没对上      → 工具选错（WRONG_TOOL）
            # 这需要 result 里带 args 明细，见文件末尾 TODO ①
            expected = case.get("expected_tools", [])
            expected_names = [t for t, _ in expected]
            detail = result.get("tool_calls_detail") or []  # [(name, args), ...]
            if detail:
                called_names = [n for n, _ in detail]
                name_hit = any(n in expected_names for n in called_names)
                if name_hit:
                    findings.append(
                        Finding(
                            cid,
                            "WRONG_ARGUMENT",
                            f"tool name ok but args mismatch: "
                            f"called={detail} expected={expected}",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            cid,
                            "WRONG_TOOL",
                            f"tool name mismatch: called={called_names} expected={expected_names}",
                        )
                    )
            else:
                findings.append(
                    Finding(
                        cid,
                        "WRONG_TOOL",
                        f"called={tools} expected={expected_names} "
                        f"(证据不足：缺 args 明细，无法区分选错工具还是填错参数)",
                    )
                )

    if not result.get("tools_discipline_ok", True):
        forbidden = case.get("forbidden_tools", [])
        findings.append(
            Finding(
                cid,
                "TOOL_DISCIPLINE",
                f"called forbidden {[t for t in tools if t in forbidden]}",
            )
        )

    # 工具执行失败：需要 result 里有 error_codes（见文件末尾 TODO）
    for code in result.get("error_codes", []) or []:
        if code == "BAD_ARGUMENT":
            findings.append(Finding(cid, "BAD_ARGUMENT", "tool returned BAD_ARGUMENT"))
        elif code in ("TIMEOUT", "INTERNAL"):
            findings.append(Finding(cid, "TOOL_FAILURE", f"tool returned {code}"))

    # 被强制停机：从回答文本识别（也是 TODO 更稳妥的做法是从事件流识别）
    if "步数上限" in answer or "重复调用" in answer:
        findings.append(Finding(cid, "LOOP_GUARD", "hit loop guard / step budget"))

    # ---------- 下游：数据与表达 ----------
    missing = result.get("missing") or []
    has_numbers = any(ch.isdigit() for ch in answer)

    if not result.get("numeric_ok", True):
        # 区分：回答里有数字但不对（幻觉/失真） vs 根本没有数字（漏引用）
        kind = "HALLUCINATION" if has_numbers else "NUMERIC_MISS"
        findings.append(Finding(cid, kind, f"missing keys={missing}"))

    if not result.get("negative_ok", True):
        bad = case.get("answer_must_not_contain", [])
        findings.append(Finding(cid, "FORBIDDEN_CONTENT", f"hits {bad}"))

    if not result.get("contains_ok", True):
        need = case.get("answer_must_contain", [])
        findings.append(Finding(cid, "MISSING_REQUIRED", f"missing words {need}"))

    # ---------- 质量：Judge ----------
    judge = result.get("judge") or {}
    scores = [
        judge.get("faithfulness"),
        judge.get("completeness"),
        judge.get("appropriateness"),
    ]
    valid = [s for s in scores if isinstance(s, (int, float))]
    if valid and sum(valid) / len(valid) < JUDGE_THRESHOLD:
        low_dims = [
            name
            for name, s in zip(
                ("faithfulness", "completeness", "appropriateness"), scores
            )
            if isinstance(s, (int, float)) and s < JUDGE_THRESHOLD
        ]
        findings.append(Finding(cid, "LOW_QUALITY", f"low dims={low_dims}"))

    return Attribution(
        case_id=cid,
        passed=bool(result.get("overall_ok", False)),
        findings=findings,
    )


# ============================================================
# 3. 汇总：告诉你「先改哪里最划算」
# ============================================================


def aggregate(rows: list[Attribution]) -> dict:
    """按失败类型和负责组件聚合，输出改进优先级。"""
    kinds = Counter()
    owners = Counter()
    for r in rows:
        # 每个 case 只计一次主因，避免同一条用例被重复计数
        p = r.primary
        if p:
            kinds[p.kind] += 1
            owners[p.owner] += 1

    total = len(rows)
    failed = sum(1 for r in rows if not r.passed)

    return {
        "total_cases": total,
        "failed_cases": failed,
        "pass_rate": round((total - failed) / total, 3) if total else 0.0,
        "by_kind": kinds.most_common(),
        "by_owner": owners.most_common(),
        # 一句话结论：改哪一块收益最大
        "top_action": (
            f"先改 {owners.most_common(1)[0][0]}（影响 {owners.most_common(1)[0][1]} 条）"
            if owners
            else "全部通过"
        ),
    }


def render_report(summary: dict, rows: list[Attribution] | None = None) -> str:
    """把汇总渲染成可读报告（也可以直接贴进飞书/周报）。"""
    lines = [
        f"通过率 {summary['pass_rate']:.1%}（{summary['total_cases'] - summary['failed_cases']}/{summary['total_cases']}）",
        "",
        "失败类型分布：",
    ]
    for kind, n in summary["by_kind"]:
        meta = TAXONOMY.get(kind, {})
        lines.append(f"  {kind:<22} {n:>3}  → {meta.get('component', '?')}")

    lines += ["", "按组件聚合（修复优先级）："]
    for owner, n in summary["by_owner"]:
        lines.append(f"  {owner:<14} {n:>3} 条")

    lines += ["", f"结论：{summary['top_action']}"]

    if rows:
        lines += ["", "失败明细："]
        for r in rows:
            p = r.primary
            if p:
                lines.append(f"  [{p.kind}] {r.case_id} — {p.evidence}")
                lines.append(f"       修法：{p.fix}")

    return "\n".join(lines)


# ============================================================
# 与 eval_runner 的契约（已完成）
#
# eval_runner.run_case 现在会返回下面三个字段，归因靠它们区分「选错工具」和「填错参数」：
#   tool_calls_detail : [(name, args), ...]  实际调用明细
#   error_codes       : ["BAD_ARGUMENT", ...] 工具层结构化错误码
#   steps             : int                  工具调用次数（步数）
#
# 仍待办（按重要性）：
#   ① ~~JUDGE_THRESHOLD 未校准~~ 已完成：eval_judge_calibration.py 用 30 条
#      锚点样本校准，6.5 阈值下一致率 30/30、零误杀。局限：锚点是我自己按
#      评分定义造的，不是第三方标注，所以只能说"Judge 与定义一致"，不能说
#      "Judge 与人类专家一致"。
#   ② LOOP_GUARD 目前靠回答文本里出现「步数上限 / 重复调用」来识别，
#      更稳的做法是从事件流里读 agent 的停机原因（需要一个 stop_reason 字段）。
#   ③ 若要把归因结果喂给看板，加一个 save_json 落盘即可。
# ============================================================
