"""
Step 1 第 2 小步的验收测试：兵种克制与适性。
运行方式：在 backend 目录下执行  python test_troops.py
"""

from troops import (
    APTITUDE_RATE,
    COUNTER_DAMAGE_BONUS,
    get_aptitude_rate,
    get_counter_bonus,
)

# ===== 1. 四组循环克制：都应返回 0.15 =====
assert get_counter_bonus("骑兵", "盾兵") == COUNTER_DAMAGE_BONUS
assert get_counter_bonus("盾兵", "弓兵") == COUNTER_DAMAGE_BONUS
assert get_counter_bonus("弓兵", "枪兵") == COUNTER_DAMAGE_BONUS
assert get_counter_bonus("枪兵", "骑兵") == COUNTER_DAMAGE_BONUS

# ===== 2. 被反克：盾兵打骑兵应返回 0.0 =====
assert get_counter_bonus("盾兵", "骑兵") == 0.0

# ===== 3. 同兵种互打：不克制，返回 0.0 =====
assert get_counter_bonus("骑兵", "骑兵") == 0.0

# ===== 4. 器械被四兵种全部克制 =====
for attacker in ("骑兵", "盾兵", "弓兵", "枪兵"):
    assert get_counter_bonus(attacker, "器械") == COUNTER_DAMAGE_BONUS

# ===== 5. 器械打别人：不克制任何兵种 =====
assert get_counter_bonus("器械", "骑兵") == 0.0

# ===== 6. 适性系数 =====
assert APTITUDE_RATE["S"] == 1.20
assert get_aptitude_rate("s") == 1.20  # 小写也能查（防御性设计）
assert get_aptitude_rate("C") == 0.70
assert get_aptitude_rate("X") == 1.00  # 未知等级兜底为 100%

print("test_troops.py 全部通过 ✓")

# 直观打印一遍，方便肉眼确认
print("骑兵 打 盾兵:", get_counter_bonus("骑兵", "盾兵"))
print("盾兵 打 骑兵:", get_counter_bonus("盾兵", "骑兵"))
print("枪兵 打 器械:", get_counter_bonus("枪兵", "器械"))
print("S 级适性系数:", get_aptitude_rate("S"))
