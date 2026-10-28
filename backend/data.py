"""
静态数据：兵种表 + 武将表（后续将由 Excel 解析器替代）。
"""

from generals import General
from models import UnitStats

UNITS = {
    "骑兵": UnitStats(
        unit_id="cavalry",
        unit_name="骑兵",
        level=1,
        attack=60,
        defense=50,
        hp=100,
        speed=30,
        cost=150,
        train_time=20.0,
    ),
    "盾兵": UnitStats(
        unit_id="shield",
        unit_name="盾兵",
        level=1,
        attack=30,
        defense=90,
        hp=165,
        speed=20,
        cost=120,
        train_time=15.0,
    ),
    "弓兵": UnitStats(
        unit_id="archer",
        unit_name="弓兵",
        level=1,
        attack=90,
        defense=30,
        hp=80,
        speed=40,
        cost=180,
        train_time=25.0,
    ),
    "枪兵": UnitStats(
        unit_id="spear",
        unit_name="枪兵",
        level=1,
        attack=70,
        defense=45,
        hp=90,
        speed=25,
        cost=140,
        train_time=18.0,
    ),
    "器械": UnitStats(
        unit_id="engine",
        unit_name="器械",
        level=1,
        attack=150,
        defense=10,
        hp=60,
        speed=15,
        cost=250,
        train_time=30.0,
    ),
}

GENERALS = {
    "张飞": General(
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
    ),
    "诸葛亮": General(
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
    ),
    "袁绍": General(
        general_id="003",
        name="袁绍",
        faction="袁氏",
        rarity=5,
        force=62,
        intellect=71,
        leadership=80,
        speed=58,
        politics=88,
        charm=90,
        aptitude={"骑兵": "A", "盾兵": "A", "弓兵": "S", "枪兵": "B", "器械": "B"},
    ),
    # ===== 第二批：三个战力基数几乎相等的武将（≈88），用于制造「均势对局」 =====
    # 计算依据：基数 = force*0.4 + intellect*0.3 + leadership*0.3
    #   关羽 38.8+21.3+28.5 = 88.6
    #   赵云 38.4+22.8+27.3 = 88.5
    #   张辽 36.8+23.4+27.9 = 88.1
    # 三者互打理论上接近五五开 —— 这是评测区分度的来源。
    # 之前只有张飞(74.3)/诸葛亮(63.1)/袁绍(70.1)，差距太大，组合必然一边倒。
    "关羽": General(
        general_id="004",
        name="关羽",
        faction="蜀汉",
        rarity=5,
        force=97,
        intellect=71,
        leadership=95,
        speed=68,
        politics=62,
        charm=93,
        aptitude={"骑兵": "S", "盾兵": "A", "弓兵": "C", "枪兵": "S", "器械": "B"},
    ),
    "赵云": General(
        general_id="005",
        name="赵云",
        faction="蜀汉",
        rarity=5,
        force=96,
        intellect=76,
        leadership=91,
        speed=91,  # 速度给高：机动型，与关羽的「重装」形成差异
        politics=65,
        charm=92,
        aptitude={"骑兵": "S", "盾兵": "A", "弓兵": "A", "枪兵": "B", "器械": "C"},
    ),
    "张辽": General(
        general_id="006",
        name="张辽",
        faction="曹魏",
        rarity=5,
        force=92,
        intellect=78,
        leadership=93,
        speed=82,
        politics=58,
        charm=70,
        aptitude={"骑兵": "S", "盾兵": "A", "弓兵": "B", "枪兵": "A", "器械": "B"},
    ),
    # 智力型对照：与诸葛亮同为智将，但武力更高（63 vs 25），所以基数高一档，
    # 用来测「阵容强度差一档时模型还能不能说准」。
    "司马懿": General(
        general_id="007",
        name="司马懿",
        faction="曹魏",
        rarity=5,
        force=63,
        intellect=96,
        leadership=88,
        speed=62,
        politics=93,
        charm=85,
        aptitude={"骑兵": "B", "盾兵": "A", "弓兵": "S", "枪兵": "C", "器械": "S"},
    ),
}
