from battle import Army
from generals import General
from mc_sim import run_mc_sim
from models import UnitStats

qibing = UnitStats(
    unit_id="cavalry",
    unit_name="骑兵",
    level=1,
    attack=80,
    defense=50,
    hp=100,
    speed=30,
    cost=150,
    train_time=20.0,
)
dunbing = UnitStats(
    unit_id="shield",
    unit_name="盾兵",
    level=1,
    attack=30,
    defense=120,
    hp=200,
    speed=20,
    cost=120,
    train_time=15.0,
)
gongbing = UnitStats(
    unit_id="archer",
    unit_name="弓兵",
    level=1,
    attack=100,
    defense=30,
    hp=80,
    speed=40,
    cost=180,
    train_time=25.0,
)
qiangbing = UnitStats(
    unit_id="spear",
    unit_name="枪兵",
    level=1,
    attack=70,
    defense=60,
    hp=90,
    speed=25,
    cost=140,
    train_time=18.0,
)
qixie = UnitStats(
    unit_id="siege",
    unit_name="器械",
    level=1,
    attack=150,
    defense=10,
    hp=60,
    speed=10,
    cost=200,
    train_time=30.0,
)

zhangfei = General(
    general_id="001",
    name="张飞",
    faction="蜀汉",
    rarity=5,
    force=98,
    intellect=32,
    leadership=85,
    speed=71,
    politics=15,
    charm=45,
    aptitude={"骑兵": "S", "盾兵": "A", "弓兵": "B", "枪兵": "S", "器械": "C"},
)

zhugeliang = General(
    general_id="002",
    name="诸葛亮",
    faction="蜀汉",
    rarity=5,
    force=25,
    intellect=99,
    leadership=78,
    speed=65,
    politics=96,
    charm=92,
    aptitude={"骑兵": "C", "盾兵": "B", "弓兵": "A", "枪兵": "B", "器械": "S"},
)

yuanshao = General(
    general_id="003",
    name="袁绍",
    faction="群雄",
    rarity=5,
    force=62,
    intellect=71,
    leadership=80,
    speed=58,
    politics=88,
    charm=90,
    aptitude={"骑兵": "A", "盾兵": "A", "弓兵": "S", "枪兵": "B", "器械": "B"},
)

zhangfei_cavalry = Army(unit=qibing, general=zhangfei, troop_type="骑兵")
yuanshao_shield = Army(unit=dunbing, general=yuanshao, troop_type="盾兵")
zhuge_siege = Army(unit=qixie, general=zhugeliang, troop_type="器械")
yuanshao_siege = Army(unit=qixie, general=yuanshao, troop_type="器械")
mirror = Army(unit=qibing, general=zhangfei, troop_type="骑兵")


assert (
    run_mc_sim(
        Army(unit=qibing, general=zhangfei, troop_type="骑兵"),
        Army(unit=dunbing, general=yuanshao, troop_type="盾兵"),
        n=1000,
        damage_jitter=0.2,
        seed=42,
    ).wins_a
    > 500
)


# 1. 确定性回归：随机幅度归零 → 强方必胜
result0 = run_mc_sim(zhangfei_cavalry, yuanshao_shield, n=100, damage_jitter=0.0)
assert result0.win_rate_a == 1.0

# 2. 五五开：镜像对决 + 随机 → 先手方占优但不碾压（实测 seed=42 时 0.612）
mirror_result = run_mc_sim(mirror, mirror, n=1000, damage_jitter=0.2, seed=42)
assert 0.5 < mirror_result.win_rate_a < 0.75

# 3. 克制胜率区间：战力略弱(257 vs 275)但有克制 → 胜率过半但非必胜
upset_result = run_mc_sim(
    zhangfei_cavalry, zhuge_siege, n=1000, damage_jitter=0.2, seed=42
)
assert 0.45 < upset_result.win_rate_a < 0.70

# 4. 碾压局：28% 战力差 → 接近全胜
crush_result = run_mc_sim(
    zhangfei_cavalry, yuanshao_siege, n=1000, damage_jitter=0.2, seed=42
)
assert crush_result.win_rate_a > 0.95

# 5. 可复现：同 seed 跑两次 → 结果完全一致（dataclass 的 __eq__ 直接比）
r1 = run_mc_sim(zhangfei_cavalry, zhuge_siege, n=500, damage_jitter=0.2, seed=7)
r2 = run_mc_sim(zhangfei_cavalry, zhuge_siege, n=500, damage_jitter=0.2, seed=7)
assert r1 == r2
