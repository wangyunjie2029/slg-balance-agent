from battle import Army, calc_counter_multiplier, simulate_battle
from generals import General
from models import UnitStats
from troops import COUNTER_DAMAGE_BONUS

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
