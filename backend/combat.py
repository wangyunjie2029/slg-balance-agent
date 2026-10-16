"""
阵容战力计算：兵种基础数值 × 武将加成。
Step 1 第 4 小步。
"""

from generals import General, calc_general_base
from models import UnitStats
from troops import get_aptitude_rate

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
