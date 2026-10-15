"""
兵种类型、兵种克制与兵种适性。
参考《三国志·战略版》《三国志·谋定天下》。
"""

# ===== 兵种常量（变量名英文，值用游戏里的中文名）=====
CAVALRY = "骑兵"
SHIELD = "盾兵"
ARCHER = "弓兵"
SPEAR = "枪兵"
SIEGE = "器械"

TROOP_TYPES = [CAVALRY, SHIELD, ARCHER, SPEAR, SIEGE]

# ===== 兵种克制：key 克制 value（一个兵种可克制多个，用列表）=====
# 主循环：骑克盾、盾克弓、弓克枪、枪克骑；
# 另外器械被骑兵、盾兵、弓兵、枪兵全部克制。
COUNTER = {
    CAVALRY: [SHIELD, SIEGE],
    SHIELD: [ARCHER, SIEGE],
    ARCHER: [SPEAR, SIEGE],
    SPEAR: [CAVALRY, SIEGE],
}

# 克制时的伤害加成（三谋为 +15%；三战可用同参数，作为可配置项）
COUNTER_DAMAGE_BONUS = 0.15

# ===== 兵种适性系数（三战：S=120%、A=100%、B=85%、C=70%）=====
APTITUDE_RATE = {
    "S": 1.20,
    "A": 1.00,
    "B": 0.85,
    "C": 0.70,
}


def get_counter_bonus(attacker_troop: str, defender_troop: str) -> float:
    """攻击方克制防守方时返回伤害加成，否则返回 0。"""
    # 防守方在攻击方"克制列表"里，就说明被克制
    if defender_troop in COUNTER.get(attacker_troop, []):
        return COUNTER_DAMAGE_BONUS
    return 0.0


def get_aptitude_rate(aptitude: str) -> float:
    """按适性等级返回系数；未知等级一律按 A（100%）处理，避免程序崩溃。"""
    return APTITUDE_RATE.get(aptitude.upper(), 1.00)
