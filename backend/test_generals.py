from data import GENERALS, UNITS
from generals import calc_general_combat_power

# 兵种
qibing = UNITS["骑兵"]
dunbing = UNITS["盾兵"]
gongbing = UNITS["弓兵"]
qiangbing = UNITS["枪兵"]
qixie = UNITS["器械"]

# 武将
zhangfei = GENERALS["张飞"]
zhugeliang = GENERALS["诸葛亮"]
yuanshao = GENERALS["袁绍"]


assert (
    calc_general_combat_power(zhangfei, "骑兵") == 89
)  # 张飞基数74.3 × 骑兵S 1.20 = 89.16 → 89
assert (
    calc_general_combat_power(zhangfei, "盾兵") == 74
)  # 张飞基数74.3 × 盾兵A 1.00 = 74.3 → 74
assert (
    calc_general_combat_power(zhugeliang, "器械") == 76
)  # 诸葛亮基数74.3 × 器械S 1.02 = 75.79 → 76
assert (
    calc_general_combat_power(yuanshao, "弓兵") == 84
)  # 袁绍基数74.3 × 弓兵S 1.13 = 83.96 → 84

assert (
    calc_general_combat_power(zhangfei, "弓兵") == 63
)  # 张飞基数74.3 × 弓兵B 0.85 = 63.16 → 63

assert calc_general_combat_power(yuanshao, "弓兵") > calc_general_combat_power(
    zhangfei, "弓兵"
)  # 袁绍的弓兵战斗力大于张飞的弓兵战斗力

assert (
    calc_general_combat_power(zhangfei, "攻城车") == 74
)  # 张飞基数74.3 × 攻城车C 0.99 = 73.56 → 74
