"""
阵容战力计算：兵种基础数值 × 武将加成。
Step 1 第 4 小步。
"""

from generals import General, calc_general_base
from models import UnitStats
from troops import get_aptitude_rate

# ===== 战斗数值常量（战力层拥有，战斗层导入使用）=====
HP_POOL_FACTOR = 10  # 血池 = (hp + defense) × 此系数
DAMAGE_FACTOR = 2  # 每回合伤害 = 攻击分 ÷ 此系数 × 克制乘数


UNIT_BASE_WEIGHTS = {"attack": 1.0, "defense": 1.0, "hp": 0.1}


def calc_unit_base_power(unit: UnitStats) -> float:
    """兵种基础战力 = 攻防血加权（不含武将、不含适性）。"""
    # 结构和 calc_general_base 一样：遍历权重表 + getattr 累加
    base = 0.0
    for attr_name, weight in UNIT_BASE_WEIGHTS.items():
        base += getattr(unit, attr_name) * weight
    return base


def calc_army_power(unit: UnitStats, general: "General", troop_type: str) -> int:
    """阵容战力 = (兵种基础战力 + 武将战斗基数) × 适性系数，四舍五入取整。"""
    unit_base = calc_unit_base_power(unit)
    general_base = calc_general_base(general)
    aptitude_level = general.aptitude.get(troop_type, "A")
    aptitude_coefficient = get_aptitude_rate(aptitude_level)
    return round((unit_base + general_base) * aptitude_coefficient)


ATTACK_WEIGHT = 0.3  # 武将基数参与攻击的权重（兵种底子主导输出）


def calc_army_attack(unit: UnitStats, general: "General", troop_type: str) -> int:
    """攻击分：兵种攻击 + 武将基数×权重，再乘适性。"""
    base = unit.attack + calc_general_base(general) * ATTACK_WEIGHT
    aptitude = get_aptitude_rate(general.aptitude.get(troop_type, "A"))
    return round(base * aptitude)


def calc_army_health_pool(unit: UnitStats) -> int:
    """血池：兵种 hp + defense（防御=另一种血），武将不参与承伤（第一版简化）。"""
    return (unit.hp + unit.defense) * HP_POOL_FACTOR
