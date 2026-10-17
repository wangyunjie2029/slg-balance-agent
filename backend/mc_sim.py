"""
蒙特卡洛对战模拟：跑 N 场带随机的战斗，统计胜率。
Step 1 第 6 小步。
"""

import random
from dataclasses import dataclass

from battle import Army, simulate_battle


@dataclass
class McResult:
    """千场模拟的统计结果。"""

    n: int  # 总场次
    wins_a: int
    wins_b: int
    draws: int
    win_rate_a: float  # = wins_a / n，保留 3 位小数


def run_mc_sim(
    army_a: Army,
    army_b: Army,
    n: int = 1000,
    damage_jitter: float = 0.35,
    seed: int | None = None,  # ← 传种子则结果可复现
) -> McResult:
    """蒙特卡洛模拟：跑 n 场战斗，统计胜率。"""
    if seed is not None:
        random.seed(seed)

    wins_a = 0
    wins_b = 0
    draws = 0

    for _ in range(n):
        result = simulate_battle(army_a, army_b, damage_jitter=damage_jitter)
        if result.winner == "A":
            wins_a += 1
        elif result.winner == "B":
            wins_b += 1
        else:
            draws += 1

    win_rate_a = round(wins_a / n, 3)
    return McResult(
        n=n, wins_a=wins_a, wins_b=wins_b, draws=draws, win_rate_a=win_rate_a
    )
