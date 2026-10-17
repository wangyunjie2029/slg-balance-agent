from combat import calc_army_power, calc_unit_base_power
from data import GENERALS, UNITS

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

# ===== 黄金值（2-8 数值补丁后重生成：骑兵攻 80→60 / 盾 30-90-165 / 弓 90-30-80 / 枪 70-45-90）=====
# 手算示例：张飞骑兵 = (120 + 74.3) × 1.2 = 233.16 → 233

assert calc_unit_base_power(qibing) == 120

assert calc_army_power(qibing, zhangfei, "骑兵") == 233

assert calc_army_power(dunbing, zhangfei, "盾兵") == 211

assert calc_army_power(gongbing, yuanshao, "弓兵") == 238

assert calc_army_power(gongbing, zhangfei, "弓兵") == 172


assert calc_army_power(gongbing, yuanshao, "弓兵") > calc_army_power(
    gongbing, zhangfei, "弓兵"
)

print("test_combat.py 全部通过 ✓")
