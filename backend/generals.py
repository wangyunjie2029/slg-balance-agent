"""
武将模型与武将带兵战力计算。
Step 1 第 3 小步。
"""

from dataclasses import dataclass

from troops import get_aptitude_rate


@dataclass
class General:
    # 标识
    general_id: str  # 武将 ID
    name: str  # 武将中文名
    faction: str  # 阵营
    rarity: int  # 稀有度（星级）

    # 战斗四维
    force: int  # 武力
    intellect: int  # 智力
    leadership: int  # 统率
    speed: int  # 速度（决定出手顺序）

    # 内政二维
    politics: int  # 政治（影响内政）
    charm: int  # 魅力（影响招募）

    aptitude: dict[str, str]  # 适性（兵种名 -> 适性等级）


COMBAT_WEIGHTS = {"force": 0.4, "intellect": 0.3, "leadership": 0.3}


def calc_general_combat_power(general: "General", troop_type: str) -> int:

    base = 0.0
    for attr_name, weight in COMBAT_WEIGHTS.items():
        base += getattr(general, attr_name) * weight

    aptitude_level = general.aptitude.get(troop_type, "A")
    aptitude_coefficient = get_aptitude_rate(aptitude_level)
    return round(base * aptitude_coefficient)
