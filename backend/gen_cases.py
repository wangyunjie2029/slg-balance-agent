"""案例生成器：模板 × 组合 × 引擎取证 → G 系列案例。幂等（重跑重新取证覆盖）。"""

import json

from data import GENERALS, UNITS
from graph import calc_army_power, get_counter_relation, simulate_matchup
from troops import TROOP_TYPES

GENERALS_LIST = ["张飞", "诸葛亮", "袁绍"]
BATCH_N = 300  # 取证模拟场数（生成期用小 n 提速；真值容差 ±0.05）


def gen_battle_cases() -> list:
    cases = []
    for ga in GENERALS_LIST:
        for ta in TROOP_TYPES:
            for gb in GENERALS_LIST:
                for tb in TROOP_TYPES:
                    if (ga, ta) >= (gb, tb):  # 去镜像：只保留字典序一半
                        continue
                    r = simulate_matchup.invoke(
                        {
                            "unit_a": ta,
                            "general_a": ga,
                            "troop_a": ta,
                            "unit_b": tb,
                            "general_b": gb,
                            "troop_b": tb,
                        }
                    )
                    cases.append(
                        {
                            "category": "numeric",
                            "question": f"{ga}带{ta}打{gb}带{tb}谁赢，胜率多少",
                            "expected_tools": [
                                [
                                    "simulate_matchup",
                                    {
                                        "general_a": ga,
                                        "troop_a": ta,
                                        "general_b": gb,
                                        "troop_b": tb,
                                    },
                                ]
                            ],
                            "expected_facts": {"win_rate": r["win_rate_a"]},
                            "notes": f"组合生成：{ga}({ta}) vs {gb}({tb})，取证 n={BATCH_N}",
                        }
                    )
    return cases


def gen_compare_cases() -> list:
    cases = []
    for ga in GENERALS_LIST:
        for ta in TROOP_TYPES:
            for gb in GENERALS_LIST:
                for tb in TROOP_TYPES:
                    if (ga, ta) >= (gb, tb):
                        continue
                    # ↓ 取证换函数：战力是两次 calc，不是一次 simulate
                    pa = calc_army_power.invoke({"general_name": ga, "troop_type": ta})
                    pb = calc_army_power.invoke({"general_name": gb, "troop_type": tb})
                    cases.append(
                        {
                            "category": "numeric",
                            "question": f"{ga}带{ta}和{gb}带{tb}，谁的阵容战力更高",  # ← 模板 B
                            "expected_tools": [  # ← 期望两次 calc
                                [
                                    "calc_army_power",
                                    {"general_name": ga, "troop_type": ta},
                                ],
                                [
                                    "calc_army_power",
                                    {"general_name": gb, "troop_type": tb},
                                ],
                            ],
                            "expected_facts": {
                                "power_a": pa["power"],
                                "power_b": pb["power"],
                            },
                        }
                    )
    return cases


def gen_counter_cases() -> list:
    cases = []
    for t in TROOP_TYPES:  # ← 只遍历兵种（武将无关）
        r = get_counter_relation.invoke({"troop_type": t})
        cases.append(
            {
                "category": "routing",
                "question": f"{t}的克制关系是什么",
                "expected_tools": [["get_counter_relation", {"troop_type": t}]],
                # 克制查询没有数字真值 → expected_facts 留空（路由判定足够）
            }
        )
    return cases


def main():
    g_cases = gen_battle_cases() + gen_compare_cases() + gen_counter_cases()
    for i, c in enumerate(g_cases, 1):  # ← 缺的就是这两行
        c["case_id"] = f"G{i:03d}"  #    合并后统一编号
    base = json.load(open("eval_cases.json", encoding="utf-8"))
    base = [c for c in base if not c["case_id"].startswith("G")]  # 移除旧 G 系列
    merged = base + g_cases
    json.dump(
        merged,
        open("eval_cases.json", "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print(f"生成 {len(g_cases)} 条 G 案例，总计 {len(merged)} 条")


if __name__ == "__main__":
    main()
