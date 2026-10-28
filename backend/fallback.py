"""
LLM 失败降级：从「抱歉，服务不可用」升级为「少给解释，但保住数据」。

三级降级：
    L1 正常     LLM 编排 + 工具
    L2 规则兜底  从问题里抽参数 → 直接调引擎 → 模板化输出（完全不经 LLM）
    L3 明确失败  告诉用户不可用，不假装回答

为什么值得做（面试会问）：
    LLM 会挂：限流、超时、余额不足、上游故障。挂了只回「抱歉」是偷懒——因为
    用户要的核心信息（谁赢、胜率多少）根本不依赖 LLM，引擎自己就能算。
    降级的目标不是「保持智能」，而是「保住可用性」。

设计要点：
    1. 失败计数按 thread_id 隔离——A 会话挂了不该影响 B 会话
    2. 成功一次就清零——避免偶发抖动累积成永久降级
    3. 兜底回答必须明确标注「这是降级结果」，不能冒充正常回答
"""

from config import DAMAGE_JITTER, FAILURE_THRESHOLD, SIM_N, SIM_SEED
from data import GENERALS, UNITS
from mc_sim import run_mc_sim

# thread_id -> 连续失败次数
_failures: dict[str, int] = {}


# ============================================================
# 1. 失败计数
# ============================================================


def record_failure(thread_id: str) -> int:
    """记一次失败，返回当前连续失败次数。"""
    n = _failures.get(thread_id, 0) + 1
    _failures[thread_id] = n
    return n


def record_success(thread_id: str) -> None:
    """成功一次就清零——抖动不该累积成永久降级。"""
    _failures.pop(thread_id, None)


def failure_count(thread_id: str) -> int:
    return _failures.get(thread_id, 0)


def should_fallback(thread_id: str) -> bool:
    """连续失败达到阈值 → 走兜底。"""
    return failure_count(thread_id) >= FAILURE_THRESHOLD


def reset(thread_id: str | None = None) -> None:
    """测试用：清空计数。"""
    if thread_id is None:
        _failures.clear()
    else:
        _failures.pop(thread_id, None)


# ============================================================
# 2. 规则抽取：从自然语言里捞参数
# ============================================================


def extract_matchup(question: str) -> dict | None:
    """从问题里抽「两个武将 + 两个兵种」。

    做法：记录所有已知名字在问题中的出现位置，按位置排序，
    前两个武将 + 前两个兵种 → A 方，后两个 → B 方。

    这不是"理解语义"，是"兜底"——宁可粗糙，也要给出数据。
    抽不到（比如用户问的是"哪个兵种太强"）就返回 None，交给上层说不可用。
    """
    hits: list[tuple[int, str, str]] = []

    for name in GENERALS:
        pos = question.find(name)
        if pos >= 0:
            hits.append((pos, "general", name))
    for name in UNITS:
        pos = question.find(name)
        if pos >= 0:
            hits.append((pos, "unit", name))

    hits.sort(key=lambda x: x[0])

    generals = [n for _, kind, n in hits if kind == "general"]
    units = [n for _, kind, n in hits if kind == "unit"]

    if len(generals) < 2 or len(units) < 2:
        return None

    return {
        "unit_a": units[0],
        "general_a": generals[0],
        "troop_a": units[0],
        "unit_b": units[1],
        "general_b": generals[1],
        "troop_b": units[1],
    }


# ============================================================
# 3. 确定性回答（不经 LLM）
# ============================================================


def deterministic_answer(question: str) -> str | None:
    """不调 LLM 直接出答案。抽不到参数返回 None。"""
    args = extract_matchup(question)
    if not args:
        return None

    from battle import Army  # 延迟导入：避免和 graph 的导入链互相牵制

    army_a = Army(
        unit=UNITS[args["unit_a"]],
        general=GENERALS[args["general_a"]],
        troop_type=args["troop_a"],
    )
    army_b = Army(
        unit=UNITS[args["unit_b"]],
        general=GENERALS[args["general_b"]],
        troop_type=args["troop_b"],
    )
    r = run_mc_sim(
        army_a, army_b, n=SIM_N, damage_jitter=DAMAGE_JITTER, seed=SIM_SEED
    )

    a_name = f"{args['general_a']}带{args['troop_a']}"
    b_name = f"{args['general_b']}带{args['troop_b']}"
    rate_b = r.wins_b / r.n

    if r.win_rate_a >= 0.55:
        verdict = f"{a_name} 占优"
    elif r.win_rate_a <= 0.45:
        verdict = f"{b_name} 占优"
    else:
        verdict = "双方接近平衡"

    return (
        "（模型服务暂时不可用，以下是引擎直接计算的数据，暂无文字分析）\n\n"
        f"{a_name} vs {b_name}\n"
        f"  A 方胜率 {r.win_rate_a:.1%}（{r.wins_a}/{r.n} 局）\n"
        f"  B 方胜率 {rate_b:.1%}（{r.wins_b}/{r.n} 局）\n"
        f"  平局 {r.draws} 局\n"
        f"  结论：{verdict}"
    )


def fallback_answer(question: str) -> str:
    """降级的最终出口：能算就给数据，算不了就诚实说不可用。

    宁可说"我不知道"，也不要让模型在不可靠状态下编一段话。
    """
    answer = deterministic_answer(question)
    if answer:
        return answer
    return (
        "模型服务暂时不可用，且这个问题需要语义理解才能处理"
        "（我能直接算的是「X 带 A 打 Y 带 B」这类对战问题）。"
        "请稍后重试，或把问题改成具体的阵容对战后我再试一次。"
    )
