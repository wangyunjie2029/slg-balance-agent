from generals import General, calc_general_combat_power

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
