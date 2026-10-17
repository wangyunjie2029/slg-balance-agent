"""
诊断引擎：全兵种对阵矩阵 + Z-score 平衡性检验。
"""

from battle import Army
from data import UNITS
from generals import General
from mc_sim import run_mc_sim
from troops import TROOP_TYPES

# 标准武将：诊断时每个兵种都用同一个"中性武将"带队，
# 消除武将差异的干扰，只量兵种本身（实验设计的"控制变量法"）
# 诊断专用武将：全 A 适性（控制变量），中性六维；只在本模块使用，不进 data.py
DIAGNOSTIC_GENERAL = General(
    general_id="diag-001",
    name="校验武将",
    faction="诊断",
    rarity=0,
    force=60,
    intellect=60,
    leadership=60,
    speed=60,
    politics=60,
    charm=60,
    aptitude={t: "A" for t in TROOP_TYPES},  # ← 字典推导式：五系全 A
)


def build_army(troop_type: str) -> Army:
    return Army(
        unit=UNITS[troop_type],
        general=DIAGNOSTIC_GENERAL,  # ← 不再从 GENERALS 取袁绍
        troop_type=troop_type,
    )


def calc_matchup_matrix(n: int = 300) -> dict[str, dict[str, float]]:
    """全部兵种两两对阵（A 攻 B），返回胜率矩阵。对角线无意义留空。"""

    matrix = {}
    for a in TROOP_TYPES:
        matrix[a] = {}
        for b in TROOP_TYPES:
            if a == b:
                continue
            r = run_mc_sim(
                build_army(a), build_army(b), n=n, damage_jitter=0.2, seed=42
            )
            matrix[a][b] = r.win_rate_a
    return matrix


def diagnose_balance(z_threshold: float = 2.0, n: int = 300) -> dict:
    """诊断兵种平衡性：每兵种平均胜率做 Z-score，|Z|>阈值 判失衡。"""

    matrix = calc_matchup_matrix(n=n)

    all_rates = []
    for row in (
        matrix.values()
    ):  # row = {"盾兵": 1.0, "骑兵": 0.0, ...} 某兵种打其余四家的胜率
        for rate in row.values():  # 双层遍历：先兵种、再对手
            all_rates.append(rate)  # 20 场对局的胜率全收集（5 兵种 × 4 对手）

    extremes = [r for r in all_rates if r >= 0.9 or r <= 0.1]  # 过于一边倒的对局
    extreme_ratio = round(len(extremes) / len(all_rates), 3) if all_rates else 0

    avg_rates = {
        a: sum(matrix[a].values()) / (len(TROOP_TYPES) - 1) for a in TROOP_TYPES
    }

    μ = sum(avg_rates.values()) / len(avg_rates)

    σ = (sum((x - μ) ** 2 for x in avg_rates.values()) / len(avg_rates)) ** 0.5

    z_scores = {a: (avg_rates[a] - μ) / σ if σ else 0 for a in TROOP_TYPES}
    imbalanced = [
        {"troop": a, "z": round(z, 3), "direction": "过强" if z > 0 else "过弱"}
        for a, z in z_scores.items()
        if abs(z) > z_threshold
    ]

    healthy = [a for a, z in z_scores.items() if abs(z) <= z_threshold]

    return {
        "matrix": matrix,
        "avg": avg_rates,
        "z": z_scores,
        "imbalanced": imbalanced,
        "healthy": healthy,
        "extreme_ratio": extreme_ratio,  # 过于一边倒的对局占比
    }
