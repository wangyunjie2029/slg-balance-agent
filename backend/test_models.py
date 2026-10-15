from models import UnitStats

# 创建一个 1 级骑兵
cavalry = UnitStats(
    unit_id="cavalry",
    unit_name="骑兵",
    level=1,
    attack=20,
    defense=10,
    hp=100,
    speed=30,
    cost=150,
    train_time=20,
)

print(cavalry)  # 应打印 UnitStats(unit_id='cavalry', unit_name='骑兵', ...)
print("骑兵造价:", cavalry.cost)
