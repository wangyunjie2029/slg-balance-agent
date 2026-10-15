"""
数据模型：一个兵种的基础属性。
Step 1 第 1 小步：先定义清楚"一个兵种"长什么样。
"""

from dataclasses import dataclass

# @dataclass 是一个装饰器：它会自动帮我们生成 __init__、__repr__ 等方法。
# 我们只需要把字段名和类型列出来，就能直接 UnitStats(...) 创建对象，
# 不用手写又长又重复的构造函数——很适合"专门用来装数据"的类。


@dataclass
class UnitStats:
    # ===== 标识 =====
    unit_id: str  # 兵种唯一 id，如 "cavalry"
    unit_name: str  # 中文名，如 "骑兵"
    level: int  # 等级，从 1 开始

    # ===== 战斗属性 =====
    attack: int  # 攻击
    defense: int  # 防御
    hp: int  # 血量
    speed: int  # 速度（出手顺序 / 机动）

    # ===== 经济属性 =====
    cost: int  # 造价（消耗的资源）
    train_time: float  # 训练时间（秒）
