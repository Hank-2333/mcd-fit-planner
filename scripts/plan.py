#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦搭 · 配餐引擎（命令行版）

与网页 assets/app.js 使用同一套规则，供 WorkBuddy Skill 在无浏览器环境下调用。

用法：
    python scripts/plan.py --sex male --age 28 --height 172 --weight 78 \
        --target 70 --weeks 12 --pal 1.3 --met 7 --days 3 --minutes 40

    python scripts/plan.py --profile profile.json --json
"""

import argparse
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_PATH = os.path.join(ROOT, "data", "nutrition_mcd_cn.json")

# ---------------- 指南参考值 ----------------
GUIDE = {
    "fat_ratio": (0.20, 0.30),
    "carb_ratio": (0.50, 0.65),
    "sugar_max": 25,
    "sodium_max": 2000,
    "fiber": (25, 30),
    "calcium": 800,
}

MEALS = [
    {"key": "breakfast", "name": "早餐", "share": 0.25, "slots": ["bmain", "blight"]},
    {"key": "lunch", "name": "午餐", "share": 0.35, "slots": ["burger", "side", "drink"]},
    {"key": "dinner", "name": "晚餐", "share": 0.30, "slots": ["burger", "side", "drink"]},
    {"key": "snack", "name": "加餐", "share": 0.10, "slots": ["snack"]},
]

POOLS = {
    "bmain": [
        ("猪柳麦满分", "1个"), ("猪柳蛋麦满分", "1个"), ("双层猪柳蛋麦满分", "1个"),
        ("火腿扒麦满分", "1个"), ("大脆鸡扒麦满分", "1个"), ("原味板烧鸡腿麦满分", "默认"),
        ("双层原味板烧鸡腿麦满分", "1个"), ("原味板烧鸡腿炒双蛋堡", "1个"), ("猪柳炒双蛋堡", "1个"),
        ("火腿扒早安营养卷", "1个"), ("图林根香肠早安营养卷", "1个"),
        ("皮蛋鸡肉粥", "1份"), ("雪菜脆笋鸡肉粥", "1份"),
    ],
    "blight": [
        ("优品豆浆", "小"), ("纯牛奶（盒装）", "默认"), ("热美式", "中"),
        ("冰美式", "小"), ("锡兰红茶", "默认"), ("纯悦", "默认"),
    ],
    "burger": [
        ("巨无霸", "1个"), ("汉堡包", "1个"), ("麦辣鸡腿汉堡", "1个"), ("板烧鸡腿堡", "1个"),
        ("麦香鸡", "1个"), ("麦香鱼", "1个"), ("吉士汉堡包", "1个"), ("双层吉士汉堡", "1个"),
        ("不素之霸双层牛堡", "1个"), ("双层深海鳕鱼堡", "1个"), ("培根安格斯厚牛堡", "1个"),
        ("芝士安格斯厚牛堡", "1个"), ("培根蔬萃双层牛堡", "1个"),
    ],
    "side": [
        ("玉米杯", "小"), ("玉米杯", "大"), ("苹果片", "默认"), ("薯条", "迷你"),
        ("薯条", "小"), ("麦乐鸡 (5块)", "5块"), ("麦辣鸡翅", "2块"),
        ("薄皮焦香V翅", "2块"), ("脆脆薯条", "中"),
    ],
    "drink": [
        ("无糖可口可乐", "中"), ("纯悦", "默认"), ("冰美式", "中"), ("锡兰红茶", "默认"),
        ("可口可乐", "小"), ("100%苹果汁", "1盒"), ("纯牛奶（盒装）", "默认"),
    ],
    "snack": [
        ("苹果片", "默认"), ("玉米杯", "小"), ("玉米杯", "大"), ("圆筒冰淇淋", "1个"),
        ("迷你朱古力新地", "1份"), ("迷你草莓新地", "1份"), ("冰美式", "中"),
        ("纯牛奶（盒装）", "默认"), ("麦乐鸡 (5块)", "5块"), ("薯条", "小"),
    ],
}

PREF_RULES = {
    "no_beef": lambda n: "牛" not in n,
    "no_spicy": lambda n: "辣" not in n,
    "no_fish": lambda n: not any(k in n for k in ("鱼", "鳕", "虾")),
}

FIELDS = ["kcal", "protein", "fat", "carb", "sodium", "sugar", "fiber", "calcium", "sat_fat"]
ZERO = {f: 0.0 for f in FIELDS}


def load_data(overrides=None):
    """返回 (名称, 份量) -> 营养记录 的索引；overrides 用于并入 MCP 拉到的实时数据。"""
    with open(DATA_PATH, encoding="utf-8") as fh:
        rows = json.load(fh)
    index = {(r["name"], r["portion"]): dict(r) for r in rows}
    if overrides:
        for row in overrides:
            key = (row.get("name"), row.get("portion") or "默认")
            if key in index:
                index[key].update({k: v for k, v in row.items() if v is not None})
    return index


def add(a, b):
    return {f: a[f] + b[f] for f in FIELDS}


def sum_items(items):
    out = dict(ZERO)
    for it in items:
        for f in FIELDS:
            out[f] += it[f]
    return out


def build_pool(slot, prefs, index):
    items = [index.get(k) for k in POOLS[slot]]
    items = [i for i in items if i]
    kept = []
    for it in items:
        ok = True
        for p in prefs:
            rule = PREF_RULES.get(p)
            if rule and not rule(it["name"]):
                ok = False
                break
        if ok:
            kept.append(it)
    return kept or items


def calc_energy(p):
    bmr = 10 * p["weight"] + 6.25 * p["height"] - 5 * p["age"] + (5 if p["sex"] == "male" else -161)
    ex_session = p["met"] * p["weight"] * (p["minutes"] / 60.0)
    ex_daily = ex_session * p["days"] / 7.0
    tdee = bmr * p["pal"] + ex_daily
    bmi = p["weight"] / ((p["height"] / 100.0) ** 2)

    need, direction = 0.0, "keep"
    if p["target"] < p["weight"] - 0.2:
        direction = "lose"
        need = (p["weight"] - p["target"]) * 7700 / (p["weeks"] * 7)
    elif p["target"] > p["weight"] + 0.2:
        direction = "gain"
        need = -((p["target"] - p["weight"]) * 7700 / (p["weeks"] * 7))

    floor = max(bmr * 1.1, 1500 if p["sex"] == "male" else 1200)
    max_deficit = min(tdee * 0.20, 750)
    deficit = max(-400.0, min(need, max_deficit))

    kcal = tdee - deficit
    limited = False
    if kcal < floor:
        kcal, deficit, limited = floor, tdee - floor, True
    if kcal > tdee + 400:
        kcal, deficit = tdee + 400, -400.0

    p_kg = p["target"] if direction == "lose" else p["weight"]
    protein = min(max(1.25 * p_kg, 1.2 * p_kg), 1.6 * p_kg)
    protein = min(protein, 0.25 * kcal / 4)
    fat = max(0.25 * kcal / 9, min(0.6 * p["weight"], 0.30 * kcal / 9))
    carb = (kcal - protein * 4 - fat * 9) / 4
    if carb * 4 / kcal < GUIDE["carb_ratio"][0]:
        fat = 0.20 * kcal / 9
        protein = max(1.2 * p_kg, min(protein, 0.22 * kcal / 4))
        carb = (kcal - protein * 4 - fat * 9) / 4

    return {
        "bmr": bmr, "activity": bmr * p["pal"], "exercise_daily": ex_daily,
        "exercise_session": ex_session, "tdee": tdee, "target_kcal": kcal,
        "deficit": deficit, "direction": direction, "limited": limited, "bmi": bmi,
        "protein": protein, "fat": fat, "carb": carb,
        "protein_pct": protein * 4 / kcal, "fat_pct": fat * 9 / kcal, "carb_pct": carb * 4 / kcal,
    }


def day_cost(s, e):
    t = e["target_kcal"]
    fat_ceil = 0.30 * t / 9
    carb_floor = 0.50 * t / 4
    c = abs(s["kcal"] - t) / t * 900
    c += max(0, e["protein"] - s["protein"]) / max(e["protein"], 1) * 430
    c += max(0, s["fat"] - fat_ceil) / fat_ceil * 650
    c += max(0, carb_floor - s["carb"]) / carb_floor * 620
    c += max(0, s["sodium"] - GUIDE["sodium_max"]) / GUIDE["sodium_max"] * 220
    c += max(0, s["sugar"] - 30) / 30 * 140
    c += max(0, GUIDE["fiber"][0] - s["fiber"]) / GUIDE["fiber"][0] * 70
    c += max(0, GUIDE["calcium"] - s["calcium"]) / GUIDE["calcium"] * 40
    return c


def combos(slot_lists):
    out = [[]]
    for pool in slot_lists:
        out = [pre + [d] for pre in out for d in pool]
    return out


def meal_candidates(meal, target, prefs, index):
    pools = [build_pool(s, prefs, index) for s in meal["slots"]]
    na_cap = GUIDE["sodium_max"] * meal["share"]
    out = []
    for lst in combos(pools):
        s = sum_items(lst)
        if s["kcal"] < target["kcal"] * 0.5 or s["kcal"] > target["kcal"] * 1.7:
            continue
        c = abs(s["kcal"] - target["kcal"]) / max(target["kcal"], 1) * 320
        c += max(0, target["protein"] - s["protein"]) / max(target["protein"], 1) * 170
        c += max(0, s["fat"] - target["fat"] * 1.2) / max(target["fat"], 1) * 130
        c += max(0, s["sodium"] - na_cap) / max(na_cap, 1) * 110
        c += max(0, s["sugar"] - 8) / 8 * 70
        if "low_sodium" in prefs:
            c += s["sodium"] / 1000 * 25
        if "high_protein" in prefs:
            c += max(0, target["protein"] * 1.25 - s["protein"]) / max(target["protein"], 1) * 90
        out.append({"items": lst, "sum": s, "cost": c, "target": target})
    out.sort(key=lambda x: x["cost"])
    return out


TOPK = {"breakfast": 18, "lunch": 42, "dinner": 42, "snack": 10}
BEAM = 160


def plan_day(p, seed=7, data=None):
    index = data if data is not None else load_data()
    e = calc_energy(p)
    rnd = random.Random(seed)
    prefs = set(p.get("prefs") or [])

    cum, share_cum = 0.0, []
    for m in MEALS:
        cum += m["share"]
        share_cum.append(cum)

    beam = [{"sums": dict(ZERO), "cost": 0.0, "meals": []}]

    for mi, meal in enumerate(MEALS):
        target = {
            "kcal": e["target_kcal"] * meal["share"],
            "protein": e["protein"] * meal["share"],
            "fat": e["fat"] * meal["share"],
        }
        cands = meal_candidates(meal, target, prefs, index)[: TOPK.get(meal["key"], 12)]
        if not cands:
            continue

        nxt = []
        for b in beam:
            used = {i["name"] for m in b["meals"] for i in m["items"]}
            for c in cands:
                pen = 0
                for d in c["items"]:
                    if d["name"] in used:
                        pen += 30 if d["category"] in ("饮品", "McCafé 饮品及其他") else 95
                nxt.append({
                    "sums": add(b["sums"], c["sum"]),
                    "cost": b["cost"] + c["cost"] + pen,
                    "meals": b["meals"] + [c],
                })

        partial = e["target_kcal"] * share_cum[mi]
        for n in nxt:
            n["cost"] += abs(n["sums"]["kcal"] - partial) / partial * 300
        nxt.sort(key=lambda x: x["cost"])
        beam = nxt[:BEAM]

    ranked = sorted(beam, key=lambda b: b["cost"] + day_cost(b["sums"], e))
    top = ranked[:5] or ranked
    pick = top[min(len(top) - 1, int(rnd.random() * rnd.random() * len(top)))]

    meals_out = []
    for i, c in enumerate(pick["meals"]):
        meals_out.append({
            "meal": MEALS[i]["name"],
            "share": MEALS[i]["share"],
            "target_kcal": round(c["target"]["kcal"]),
            "items": [
                {"name": d["name"], "portion": d["portion"], "kcal": d["kcal"],
                 "protein": d["protein"], "fat": d["fat"], "carb": d["carb"], "sodium": d["sodium"]}
                for d in c["items"]
            ],
            "totals": {k: round(v, 1) for k, v in c["sum"].items() if k in FIELDS},
        })

    total = pick["sums"]
    return {
        "profile": p,
        "energy": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in e.items()},
        "meals": meals_out,
        "total": {k: round(v, 1) for k, v in total.items()},
        # 实际达成 vs 指南区间（整数百分比，和 energy 里的 0–1 比例区分开）
        "actual_share_pct": {
            "protein": round(total["protein"] * 4 / total["kcal"] * 100),
            "fat": round(total["fat"] * 9 / total["kcal"] * 100),
            "carb": round(total["carb"] * 4 / total["kcal"] * 100),
        },
    }


def to_markdown(res):
    e, t = res["energy"], res["total"]
    lines = [
        "## 今日能量预算",
        "| 项目 | 数值 |",
        "| --- | --- |",
        f"| 基础代谢 BMR | {e['bmr']:.0f} kcal |",
        f"| 日常活动（PAL {res['profile']['pal']:.2f}） | {e['activity']:.0f} kcal |",
        f"| 运动消耗（日均） | {e['exercise_daily']:.0f} kcal |",
        f"| 每日总消耗 TDEE | {e['tdee']:.0f} kcal |",
        f"| 建议摄入 | **{e['target_kcal']:.0f} kcal**（缺口 {e['deficit']:.0f}） |",
        f"| BMI | {e['bmi']:.1f} |",
        "",
        "## 今日配餐",
    ]
    for m in res["meals"]:
        items = "、".join(f"{i['name']}（{i['portion']}）{i['kcal']} kcal" for i in m["items"])
        lines.append(f"- **{m['meal']}**（预算 {m['target_kcal']} kcal）：{items}")
    lines += [
        "",
        f"**全天合计 {t['kcal']:.0f} kcal**　蛋白 {t['protein']:.0f} g / 脂肪 {t['fat']:.0f} g / "
        f"碳水 {t['carb']:.0f} g　钠 {t['sodium']:.0f} mg　糖 {t['sugar']:.0f} g　纤维 {t['fiber']:.0f} g",
        "",
        "供能比：蛋白 {}% / 脂肪 {}% / 碳水 {}%（指南 15–20% / 20–30% / 50–65%）".format(
            res["actual_share_pct"]["protein"],
            res["actual_share_pct"]["fat"],
            res["actual_share_pct"]["carb"],
        ),
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="麦搭 · 麦当劳减脂配餐引擎")
    ap.add_argument("--profile", help="JSON 档案文件路径")
    ap.add_argument("--sex", default="male", choices=["male", "female"])
    ap.add_argument("--age", type=int, default=28)
    ap.add_argument("--height", type=float, default=172)
    ap.add_argument("--weight", type=float, default=78)
    ap.add_argument("--target", type=float, default=70)
    ap.add_argument("--weeks", type=float, default=12)
    ap.add_argument("--pal", type=float, default=1.3)
    ap.add_argument("--met", type=float, default=7.0)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--minutes", type=int, default=40)
    ap.add_argument("--prefs", default="", help="逗号分隔：no_beef,no_spicy,no_fish,low_sodium,high_protein")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.profile:
        with open(args.profile, encoding="utf-8") as fh:
            p = json.load(fh)
    else:
        p = {
            "sex": args.sex, "age": args.age, "height": args.height,
            "weight": args.weight, "target": args.target, "weeks": args.weeks,
            "pal": args.pal, "met": args.met, "days": args.days, "minutes": args.minutes,
            "prefs": [x.strip() for x in args.prefs.split(",") if x.strip()],
        }

    res = plan_day(p, seed=args.seed)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(res))


if __name__ == "__main__":
    main()
