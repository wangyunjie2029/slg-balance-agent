"""
战斗结算：阵容相撞、克制加成、胜负判定。
Step 1 第 5 小步。
"""

import random
from dataclasses import dataclass

from combat import (
    DAMAGE_FACTOR,
    calc_army_attack,
    calc_army_health_pool,
    calc_army_power,
)
from generals import General
from models import UnitStats
from troops import get_counter_bonus

MAX_ROUNDS = 200  # 回合上限，超过判平局（防止 while 死循环，对应三战"60回合平"）


@dataclass
class Army:  # 一支阵容 = 兵种 + 武将 + 兵种类型
    unit: "UnitStats"
    general: "General"
    troop_type: str


@dataclass
class BattleResult:  # 战斗结果
    winner: str  # "A" / "B" / "draw"
    rounds: int  # 打了多少回合


def calc_counter_multiplier(attacker_troop: str, defender_troop: str) -> float:
    """克制乘数 = 1 + 克制加成（不克制就是 1.0）。"""
    return 1.0 + get_counter_bonus(attacker_troop, defender_troop)


def simulate_battle(
    army_a: Army,
    army_b: Army,
    damage_jitter: float = 0.0,
) -> BattleResult:
    """确定性战斗模拟：A 先手，按回合互相扣血，血池见底者负。"""

    attack_a = calc_army_attack(army_a.unit, army_a.general, army_a.troop_type)
    attack_b = calc_army_attack(army_b.unit, army_b.general, army_b.troop_type)
    hp_a = calc_army_health_pool(army_a.unit)
    hp_b = calc_army_health_pool(army_b.unit)

    rounds = 0
    while rounds < MAX_ROUNDS:
        rounds += 1
        damage_a = (
            attack_a
            / DAMAGE_FACTOR
            * calc_counter_multiplier(army_a.troop_type, army_b.troop_type)
            * random.uniform(1 - damage_jitter, 1 + damage_jitter)
        )
        damage_b = (
            attack_b
            / DAMAGE_FACTOR
            * calc_counter_multiplier(army_b.troop_type, army_a.troop_type)
            * random.uniform(1 - damage_jitter, 1 + damage_jitter)
        )
        hp_b -= damage_a
        if hp_b <= 0:
            return BattleResult(winner="A", rounds=rounds)
        hp_a -= damage_b
        if hp_a <= 0:
            return BattleResult(winner="B", rounds=rounds)
    return BattleResult(winner="draw", rounds=rounds)
