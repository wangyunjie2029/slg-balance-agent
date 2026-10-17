from battle import Army
from combat import calc_army_attack
from data import GENERALS, UNITS
from mc_sim import run_mc_sim

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


zhangfei_cavalry = Army(unit=qibing, general=zhangfei, troop_type="骑兵")
yuanshao_shield = Army(unit=dunbing, general=yuanshao, troop_type="盾兵")
zhuge_siege = Army(unit=qixie, general=zhugeliang, troop_type="器械")
yuanshao_siege = Army(unit=qixie, general=yuanshao, troop_type="器械")
mirror = Army(unit=qibing, general=zhangfei, troop_type="骑兵")


# 0. 坦克防线（2-8 数值补丁后重标定）：骑兵攻击分 99（nerf 后靠适性 S 回血）
#    打盾兵血池 2550 → 138 回合击穿；盾兵攻击分 51 需 287 回合追不上 → 骑兵全胜
shield_hold = run_mc_sim(
    Army(unit=qibing, general=zhangfei, troop_type="骑兵"),
    Army(unit=dunbing, general=yuanshao, troop_type="盾兵"),
    n=1000,
    damage_jitter=0.2,
    seed=42,
)
assert shield_hold.win_rate_a > 0.9  # 骑兵 138 回合取胜，盾兵追不上


# 1. 确定性回归：jitter=0 → 同一对局确定性复现 → 骑兵全胜
result0 = run_mc_sim(zhangfei_cavalry, yuanshao_shield, n=100, damage_jitter=0.0)
assert result0.win_rate_a == 1.0

# 2. 五五开：镜像对决 + 随机 → 先手方占优但不碾压（实测 seed=42 时 0.612）
mirror_result = run_mc_sim(mirror, mirror, n=1000, damage_jitter=0.2, seed=42)
assert 0.5 < mirror_result.win_rate_a < 0.75

# 3. 克制对位（2-8 数值补丁后重标定）：骑兵攻击分 99 < 器械攻击分 203（攻击劣势），
#    但器械血池仅 700，克制 +15% 直接碾压——"翻盘"叙事待器械数值上调后恢复
assert calc_army_attack(qixie, zhugeliang, "器械") > calc_army_attack(
    qibing, zhangfei, "骑兵"
)  # 攻击分劣势实证
upset_result = run_mc_sim(
    zhangfei_cavalry, zhuge_siege, n=1000, damage_jitter=0.2, seed=42
)
assert upset_result.win_rate_a > 0.9  # 克制方仍胜（攻击劣势被克制+脆皮抵消）

# 4. 碾压局：28% 战力差 → 接近全胜
crush_result = run_mc_sim(
    zhangfei_cavalry, yuanshao_siege, n=1000, damage_jitter=0.2, seed=42
)
assert crush_result.win_rate_a > 0.95

# 5. 可复现：同 seed 跑两次 → 结果完全一致（dataclass 的 __eq__ 直接比）
r1 = run_mc_sim(zhangfei_cavalry, zhuge_siege, n=500, damage_jitter=0.2, seed=7)
r2 = run_mc_sim(zhangfei_cavalry, zhuge_siege, n=500, damage_jitter=0.2, seed=7)
assert r1 == r2
