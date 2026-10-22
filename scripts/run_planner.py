#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦搭 · Skill 执行入口

一条命令完成：取数（麦当劳 MCP，可选）→ 算能量 → 配餐 → 输出 Markdown / 个性化网页。

典型用法：
    # 1) 只用内置快照，直接出配餐清单
    python scripts/run_planner.py --sex male --age 28 --height 172 --weight 78 --target 70

    # 2) 走 MCP 实时营养数据 + 查询附近门店 + 导出可交互网页
    export MCD_MCP_TOKEN=xxxx
    python scripts/run_planner.py --sex male --age 28 --height 172 --weight 78 --target 70 \
        --stores "上海市徐汇区漕溪北路" --html

设计的取舍：
    MCP 负责「真」（营养数值、门店），本地负责「算」（BMR/TDEE/组合搜索）。
    MCP 不可用时自动降级到官方快照，并在输出里注明数据来源。
"""

import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import plan as engine  # noqa: E402

try:
    from mcp_client import McpClient, McpError, flatten, load_token
except ImportError:  # pragma: no cover
    McpClient = None
    load_token = None


# ---------- MCP 返回值解析 ----------
# list-nutrition-foods 实际返回的是一段 Markdown 说明 + 一个 JSON 对象，
# 其中的 data 字段是紧凑表格文本：
#     [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
#       猪柳麦满分,null,1288,308,16,16,24,781,213
# 同时保留对标准 JSON 数组返回的兼容。

NAME_KEYS = ("name", "title", "product_name", "productName", "餐品名称", "名称", "餐品")
PORTION_KEYS = ("portion", "size", "spec", "规格", "份量", "分量")
NUM_KEYS = {
    "kcal": ("kcal", "energyKcal", "calories", "energy_kcal", "热量", "大卡"),
    "kj": ("kj", "energyKj", "energy_kj", "千焦"),
    "energy": ("energy", "能量"),
    "protein": ("protein", "蛋白质"),
    "fat": ("fat", "脂肪"),
    "carb": ("carb", "carbohydrate", "carbohydrates", "碳水化合物", "碳水"),
    "sodium": ("sodium", "na", "钠"),
    "sugar": ("sugar", "sugars", "糖"),
    "fiber": ("fiber", "dietary_fiber", "膳食纤维", "纤维"),
    "calcium": ("calcium", "ca", "钙"),
    "sat_fat": ("sat_fat", "saturated_fat", "饱和脂肪"),
}
FIELDS_KEEP = ("kcal", "protein", "fat", "carb", "sodium", "sugar", "fiber", "calcium", "sat_fat")


def _pick(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, "", "null"):
            return d[k]
    return None


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else None


def _find_json_object(text):
    for m in re.finditer(r"\{", text):
        depth = 0
        for i in range(m.start(), len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[m.start():i + 1])
                    except Exception:
                        break
    return None


def parse_compact_table(block):
    """解析 [N]{字段,...}: 换行后逗号分隔行的紧凑表格。"""
    lines = block.split("\n")
    m = re.match(r"\s*\[(\d+)\]\{([^}]*)\}", lines[0])
    if not m:
        return []
    fields = [f.strip() for f in m.group(2).split(",")]
    rows, seen = [], set()
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        cells = [c.strip() for c in line.split(",")]
        if len(cells) != len(fields):
            continue
        rec = dict(zip(fields, cells))
        name = rec.get("productName") or rec.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(rec)
    return rows


def _normalize(rows):
    """统一成 name + 数值字段；MCP 没给的字段留空，不覆盖本地已有值。"""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _pick(row, NAME_KEYS)
        if not name:
            continue
        rec = {"name": str(name).strip()}
        portion = _pick(row, PORTION_KEYS)
        if portion:
            rec["portion"] = str(portion).strip()

        kcal = _num(_pick(row, NUM_KEYS["kcal"]))
        if kcal is None:
            kj = _num(_pick(row, NUM_KEYS["kj"])) or _num(_pick(row, NUM_KEYS["energy"]))
            if kj is not None:
                kcal = kj / 4.184 if kj > 800 else kj
        if kcal is not None:
            rec["kcal"] = round(kcal)

        for field in ("protein", "fat", "carb", "sodium", "sugar", "fiber", "calcium", "sat_fat"):
            val = _num(_pick(row, NUM_KEYS[field]))
            if val is not None:
                rec[field] = val

        if "kcal" in rec:
            out.append(rec)
    return out


def parse_mcp_nutrition(text):
    """返回 (记录列表, 格式名)。"""
    obj = _find_json_object(text)
    if isinstance(obj, dict):
        data = obj.get("data")
        if isinstance(data, str) and "]" in data and "{" in data:
            rows = parse_compact_table(data)
            if rows:
                return _normalize(rows), "compact-table"
        if isinstance(data, list):
            return _normalize(data), "json-data"
        for key in ("list", "items", "foods", "products", "result"):
            if isinstance(data if False else obj.get(key), list):
                return _normalize(obj[key]), "json-" + key

    m = re.search(r"\[\d+\]\{[^}]*\}:", text)
    if m:
        rows = parse_compact_table(text[m.start():])
        if rows:
            return _normalize(rows), "compact-table"

    try:
        arr = json.loads(text)
        if isinstance(arr, list):
            return _normalize(arr), "json-array"
    except Exception:
        pass
    return [], "unknown"


# ---------- 名称匹配（MCP 用「中薯条」，本地用「薯条|中」） ----------
SIZE_TOKENS = ["迷你", "小杯", "中杯", "大杯", "1个", "2块", "4块", "5块", "1份", "1盒", "默认"]
ALIAS = {
    "那么大鸡排椒盐风味": "那么大鸡排",
    "阳光橙麦炫酷": "麦旋酷阳光橙",
    "美汁源100%苹果汁": "100%苹果汁",
}


def _squash(s):
    return re.sub(r"[\s\-—()（）·、,，.。+＋'\"]", "", str(s)).lower()


def _core(s):
    s = _squash(s)
    for t in sorted(SIZE_TOKENS, key=len, reverse=True):
        s = s.replace(_squash(t), "")
    return s.replace("可口可乐", "可乐")


def _variants(s):
    out = [_core(s)]
    for base in list(out):
        for t in ("小杯", "中杯", "大杯", "迷你", "小", "中", "大"):
            if base.endswith(t) and len(base) > len(t) + 1:
                out.append(base[:-len(t)])
            if base.startswith(t) and len(base) > len(t) + 1:
                out.append(base[len(t):])
    return list(dict.fromkeys(out))


def _portion_token(p):
    p = _squash(p)
    return "" if p in ("1个", "1份", "默认", "1盒") else p


def match_record(local, by_core):
    """名称核心匹配 → 份量词过滤 → 相似度兜底。"""
    import difflib

    cands = []
    for v in _variants(local["name"]):
        v = _core(ALIAS.get(v, v))
        if v in by_core:
            cands = by_core[v]
            break
    if not cands:
        for v in _variants(local["name"]):
            close = [x for x in difflib.get_close_matches(v, list(by_core), n=3, cutoff=0.86)
                     if len(by_core[x]) == 1]
            if close:
                return by_core[close[0]][0]
        return None

    if len(cands) == 1:
        return cands[0]

    # 份量词（小/中/大/2块/5块…）常常写在 MCP 名称里：「薯条|小」→「小薯条」
    tok = _portion_token(local.get("portion", ""))
    if tok:
        hit = [c for c in cands if tok in _squash(c["name"])]
        if len(hit) == 1:
            return hit[0]
        if hit:
            cands = hit

    # 剩下的用「名称+份量」与候选原始名称的相似度挑最像的
    probe = _squash(local["name"]) + _squash(local.get("portion", ""))
    scored = sorted(
        ((difflib.SequenceMatcher(None, probe, _squash(c["name"])).ratio(), c) for c in cands),
        key=lambda x: -x[0],
    )
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best[0] >= 0.5 and (len(scored) == 1 or best[0] - second >= 0.02):
        return best[1]
    return None


def parse_stores(text):
    """query-nearby-stores 返回的 data 数组 → 精简门店列表。"""
    obj = _find_json_object(text)
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        return []
    out = []
    for s in obj["data"]:
        if not isinstance(s, dict) or not s.get("storeName"):
            continue
        out.append({
            "name": s.get("storeName"),
            "address": s.get("address") or "",
            "distance": s.get("distance"),
            "start": s.get("businessStartTime") or "",
            "end": s.get("businessEndTime") or "",
            "code": s.get("storeCode") or "",
        })
    return out


def merge_mcp_nutrition(index, records):
    """把 MCP 记录并入本地索引，只覆盖 MCP 提供的字段。返回统计信息。"""
    by_core = {}
    for rec in records:
        for key in _variants(rec["name"]):          # 「中薯条」同时登记在「中薯条」和「薯条」下
            bucket = by_core.setdefault(key, [])
            if rec not in bucket:
                bucket.append(rec)

    matched, changed = 0, 0
    for key, local in index.items():
        hit = match_record(local, by_core)
        if not hit:
            continue
        matched += 1
        for field in FIELDS_KEEP:
            if field in hit and hit[field] != local.get(field):
                changed += 1
                local[field] = hit[field]
    return {"mcp_records": len(records), "matched": matched, "local_total": len(index), "changed": changed}


# ---------- 网页导出 ----------
def export_html(result, out_path, data_source, nutrition=None, stores=None):
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fh:
        html = fh.read()

    preset = {
        "plan": result,
        "data_source": data_source,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if nutrition:
        preset["nutrition"] = nutrition
    if stores:
        preset["stores"] = stores

    payload = json.dumps(preset, ensure_ascii=False)
    tag = '<script src="assets/app.js"></script>'
    html = html.replace(
        tag,
        '<script>window.MCD_PRESET = ' + payload + ';</script>\n  ' + tag,
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="麦搭 · 麦当劳减脂配餐 Skill")
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
    ap.add_argument("--offline", action="store_true", help="跳过 MCP，只用内置快照")
    ap.add_argument("--stores", help="查询门店的关键词，如「徐汇」「漕溪北路」（需要 MCP Token）")
    ap.add_argument("--city", default="上海", help="城市名，配合 --stores 使用")
    ap.add_argument("--html", action="store_true", help="额外导出可交互网页")
    ap.add_argument("--json", action="store_true", help="额外输出 JSON")
    ap.add_argument("--dump-raw", help="把 MCP 原始返回存到该路径，便于核对字段")
    args = ap.parse_args()

    if args.profile:
        with open(args.profile, encoding="utf-8") as fh:
            profile = json.load(fh)
    else:
        profile = {
            "sex": args.sex, "age": args.age, "height": args.height,
            "weight": args.weight, "target": args.target, "weeks": args.weeks,
            "pal": args.pal, "met": args.met, "days": args.days, "minutes": args.minutes,
            "prefs": [x.strip() for x in args.prefs.split(",") if x.strip()],
        }

    # ---- 1. 取数 ----
    records = []
    data_source = "官网快照 · 数据更新 2025-04"
    client = None

    if not args.offline:
        if McpClient is None:
            print("! 未找到 mcp_client.py，跳过 MCP，使用内置快照", file=sys.stderr)
        elif not load_token():
            print("! 未找到 MCP Token，跳过 MCP，使用内置快照（申请：https://open.mcd.cn/mcp）", file=sys.stderr)
        else:
            try:
                client = McpClient()
                client.initialize()
                res = client.call_tool("list-nutrition-foods", {})
                text = flatten(res)
                if args.dump_raw:
                    with open(args.dump_raw, "w", encoding="utf-8") as fh:
                        fh.write(text)
                    print("· MCP 原始返回已存至 %s" % args.dump_raw, file=sys.stderr)
                records, fmt = parse_mcp_nutrition(text)
                if records:
                    data_source = "麦当劳 MCP 实时查询"
                    print("· MCP 返回 %d 条餐品营养数据（%s）" % (len(records), fmt), file=sys.stderr)
                else:
                    print("! MCP 返回无法解析成餐品数组，回退快照（可用 --dump-raw 查看原始结构）", file=sys.stderr)
            except McpError as exc:
                print("! MCP 调用失败：%s —— 回退内置快照" % exc, file=sys.stderr)
                client = None

    # ---- 2. 计算 + 配餐 ----
    data = engine.load_data()
    merged = None
    if records:
        stats = merge_mcp_nutrition(data, records)
        print("· 匹配到本地 %d/%d 个 SKU，字段更新 %d 处"
              % (stats["matched"], stats["local_total"], stats["changed"]), file=sys.stderr)
        keep = ("name", "category", "portion", "kcal", "protein", "fat", "carb",
                "sodium", "sugar", "fiber", "calcium", "sat_fat")
        merged = [{k: r.get(k, 0) for k in keep} for r in data.values()]
    result = engine.plan_day(profile, seed=args.seed, data=data)

    # ---- 3. 输出 ----
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(engine.to_markdown(result))
        print("\n> 数据来源：%s" % data_source)

    # ---- 4. 门店 ----
    stores = None
    if args.stores:
        if client is None:
            print("\n! 查询门店需要 MCP Token，已跳过。门店地图：https://www.mcdonalds.com.cn/top/map", file=sys.stderr)
        else:
            try:
                raw = flatten(client.call_tool("query-nearby-stores", {
                    "beType": 1, "searchType": 2, "city": args.city, "keyword": args.stores,
                }))
                stores = parse_stores(raw)
                if stores:
                    print("\n## 附近门店（%s · %s）\n" % (args.city, args.stores))
                    print("| 门店 | 距离 | 营业时间 | 门店编号 |")
                    print("| --- | --- | --- | --- |")
                    for st in stores[:5]:
                        dist = ("%d m" % st["distance"]) if isinstance(st["distance"], (int, float)) else "—"
                        print("| %s | %s | %s–%s | %s |" % (
                            st["name"], dist, st["start"], st["end"], st["code"]))
                else:
                    print("\n! 没有查到门店，可换关键词或城市", file=sys.stderr)
            except McpError as exc:
                print("\n! 门店查询失败：%s" % exc, file=sys.stderr)

    # ---- 5. 网页 ----
    if args.html:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out = os.path.join(ROOT, "plan-%s.html" % stamp)
        export_html(
            result, out, data_source,
            nutrition=merged,
            stores=stores,
        )
        print("\n· 已导出网页：%s" % out)


if __name__ == "__main__":
    main()
