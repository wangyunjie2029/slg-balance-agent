from battle import Army, calc_counter_multiplier, simulate_battle
from data import GENERALS, UNITS
from troops import COUNTER_DAMAGE_BONUS

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


assert calc_counter_multiplier("骑兵", "器械") == 1.0 + COUNTER_DAMAGE_BONUS
assert calc_counter_multiplier("盾兵", "骑兵") == 1.0

A = Army(unit=qibing, general=zhangfei, troop_type="骑兵")
B = Army(unit=qibing, general=zhangfei, troop_type="骑兵")

mirror_result = simulate_battle(A, B)
assert mirror_result.winner == "A"  # 先手优势

A = Army(unit=qibing, general=zhangfei, troop_type="骑兵")
B = Army(unit=qixie, general=zhugeliang, troop_type="器械")
upset_result = simulate_battle(A, B)
assert upset_result.winner == "A"  # 克制翻盘：257 < 275 却赢了
