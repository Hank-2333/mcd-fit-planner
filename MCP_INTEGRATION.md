# 麦当劳 MCP 集成说明

本文说明麦搭实际使用了哪些麦当劳中国 MCP 能力、怎么调用、解决了什么问题。

## 1. 接入信息

| 项 | 值 |
| --- | --- |
| MCP Server | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权 | `Authorization: Bearer <MCD_MCP_TOKEN>` |
| 协议版本 | `2025-06-18` |
| 限流 | 600 次 / 分钟（超出返回 429） |
| Token 申请 | <https://open.mcd.cn/mcp> |

配置模板：[`mcp-config.example.json`](mcp-config.example.json)（Token 用环境变量占位，仓库内不含任何凭证）。

客户端实现：`scripts/mcp_client.py`（Python 标准库，零依赖，支持 `application/json` 与 `text/event-stream` 两种响应）。Skill 的实际执行入口是 `scripts/run_planner.py`，它内部调用这个客户端取数。

```bash
export MCD_MCP_TOKEN=<你的 Token>
python scripts/mcp_client.py ping
python scripts/mcp_client.py list-tools
python scripts/mcp_client.py call list-nutrition-foods
```

> Token 只从环境变量 `MCD_MCP_TOKEN` 读取，仓库内不保存任何凭证，符合参赛声明的信息安全要求。

## 1.1 实测记录（2026-10-23，真实 Token）

| 项 | 结果 |
| --- | --- |
| `ping` / `initialize` | 成功，`serverInfo = mcd-mcp 1.0.0` |
| `tools/list` | 返回 39 个工具，含 `list-nutrition-foods`、`query-nearby-stores`、`query-meals`、`calculate-price` 等 |
| `list-nutrition-foods` | 返回 **158 条**餐品，9 个字段 |
| 与内置快照比对 | **132/132 全部匹配**，仅 2 处字段差异（麦香鸡 370→369 kcal、热焦糖玛奇朵钙 284.7→284 mg） |
| `query-nearby-stores` | 按「上海 · 徐汇」返回 5 家门店，含门店编号、地址、距离、营业时间 |

**返回格式不是 JSON 数组，而是紧凑表格文本**（省 token 的设计），这一点必须按实际格式解析：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  猪柳蛋麦满分,null,1618,387,23,21,25,846,243
```

外层还包了一层 Markdown 说明和一个 JSON 对象（`{success, code, data, ...}`），表格在 `data` 字段里。`scripts/run_planner.py` 的 `parse_mcp_nutrition()` 同时兼容这两种形态。

另一个坑：**MCP 的名称写法和官网菜单不一致**——MCP 是「中薯条 / 小杯玉米杯 / 麦乐鸡5块 / 可乐中杯」，本地索引是「薯条|中 / 玉米杯|小 / 麦乐鸡 (5块)|5块 / 可口可乐|中」。所以做了名称归一化 + 份量词消歧 + 相似度兜底三件事，才做到 132/132 命中。

## 2. 使用的 Tool

| Tool | 在麦搭里的作用 | 是否核心 |
| --- | --- | --- |
| `list-nutrition-foods` | 营养基线：取餐品的能量、蛋白质、脂肪、碳水、钠、钙等，用于校验并刷新配餐引擎的数据源 | **核心** |
| `query-nearby-stores` | 把「找餐厅」从跳转网页链接，升级为「按用户地址返回最近门店」 | 核心 |
| `query-meals` | 校验配餐中用到的 SKU 在目标门店当天是否有售，避免推荐已下架产品 | 增强 |
| `query-meal-detail` | 套餐组成，用于把单品组合还原成门店可下单的套餐形态 | 增强 |
| `calculate-price` | 给配餐结果补上预估价格，让「今天吃这些要花多少钱」可回答 | 增强 |
| `query-store-coupons` | 提示当前门店可用优惠，把「能省钱」一并给到 | 可选 |

## 3. 调用流程

```
用户：「我 172/78，想在 12 周减到 70，今天三顿都在麦当劳，附近有啥店」
  │
  ├─ ① 收齐档案（性别/年龄/身高/体重/目标/活动水平，缺失项追问）
  │
  ├─ ② MCP: list-nutrition-foods
  │      → 拿到官方营养数据
  │      → 与 data/nutrition_mcd_cn.json 逐项比对
  │      → 有差异时以 MCP 返回为准，并在回答中标注「实时数据」
  │
  ├─ ③ 本地计算：scripts/run_planner.py（内部调 plan.py）
  │      → 把 MCP 营养数据并入基线（字段不匹配则整条忽略，不猜）
  │      → BMR → PAL → MET 运动消耗 → TDEE
  │      → 缺口夹在 [0, min(TDEE×20%, 750)]，摄入不低于 BMR×1.1
  │      → 束搜索生成早/午/晚/加餐四套组合
  │
  ├─ ④ MCP: query-meals（带门店或城市参数）
  │      → 过滤掉目标门店当天不可售的单品
  │      → 必要时回到 ③ 重排
  │
  ├─ ⑤ MCP: query-nearby-stores
  │      → 返回距离最近的门店列表
  │
  └─ ⑥ 输出：能量账 + 四餐清单 + 指南差距 + 门店
         加 --html 时导出 plan-<时间戳>.html，页头标注真实数据来源
```

一条命令跑完全流程：

```bash
export MCD_MCP_TOKEN=<your_token>
python scripts/run_planner.py --sex male --age 28 --height 172 --weight 78 --target 70 \
    --stores "上海市徐汇区漕溪北路" --html
```

### 关键设计：MCP 负责「真」，本地负责「算」

营养学和运筹学的计算（BMR、TDEE、宏量分配、组合搜索）全部在本地完成，MCP 只承担**事实来源**和**实时状态**两件事：

- **事实来源**：餐品营养数值、门店、价格、可售状态
- **实时状态**：当天有没有下架、这家店有没有这个 SKU、有什么券

这样拆分的好处是：网络不可用时页面仍然可用（回退到内置快照），MCP 可用时结果更准、更长尾。评审如果只看静态网页，看到的是完整的计算链路；接入 MCP 后，事实层被替换成实时的。

## 4. 调用示例

### 4.1 拉取营养数据

```bash
python scripts/mcp_client.py save list-nutrition-foods data/mcp_nutrition_raw.json
```

返回结构示意（字段名以实际返回为准）：

```json
{
  "content": [
    {
      "type": "text",
      "text": "[{\"name\":\"巨无霸\",\"energy\":513,\"protein\":27,\"fat\":26,\"carbohydrate\":42,\"sodium\":961}, ...]"
    }
  ]
}
```

用途：把 `energy/protein/fat/carb/sodium` 与 `data/nutrition_mcd_cn.json` 对应字段比对。字段口径不一致时（例如能量单位是 kJ 还是 kcal），以 MCP 返回的说明为准，并在回答里写明单位。

### 4.2 查询附近门店

该工具的参数不是「地址」而是「城市 + 关键词」：

```bash
python scripts/mcp_client.py call query-nearby-stores \
  '{"beType":1,"searchType":2,"city":"上海","keyword":"徐汇"}'
```

- `beType`：1 到店自取，5 得来速车道
- `searchType`：1 搜收藏餐厅，2 按位置搜索
- `city` / `keyword`：城市名、门店或商圈关键词

真实返回（截取）：

```json
{"success":true,"code":200,
 "data":[{"storeCode":"1450384","storeName":"麦当劳上海徐汇绿地缤纷城餐厅",
          "address":"东安路562号绿地缤纷城B1-W126","distance":737,
          "businessStartTime":"07:30","businessEndTime":"22:00"}]}
```

用途：用户问「附近哪家」时给出最近几家和营业时间；用户没给城市或商圈就先问，不猜。导出网页时这份列表会直接渲染到「找餐厅」卡片里。

## 5. 业务价值

1. **让「麦当劳能不能减脂」有答案。**
   过去这类问题只能得到「偶尔吃一次」这种正确但没用的回答。麦搭把它变成一个当场能执行的方案：吃哪几个单品、哪个时段吃、和指南差多少、怎么补。

2. **把营养数据变成决策，而不是一张表。**
   官方营养计算器给的是「单份餐品的六项成分」，麦搭把它变成「全天四餐的组合优化问题」，并显式建模了热量、蛋白、脂肪、钠、糖、纤维、钙七个约束。

3. **给门店带来的是「已经想好要吃什么」的客流。**
   用户是带着具体 SKU 清单点开门店地图的，不是随便看看。若接 `query-meals` + `calculate-price`，可以直接把这套配餐变成可下单的购物车。

4. **对 MCP 的依赖是必要且可降级的。**
   营养数值必须来自官方（否则用户不敢用），门店与可售状态必须实时（否则推荐了买不到的东西）。两者都不可替代，但都可以降级——这正是一个 MCP 集成本该有的样子。

## 6. 降级与异常

| 情况 | 表现 | 处理 |
| --- | --- | --- |
| 未配置 Token | `scripts/mcp_client.py` 直接提示去申请，退出码 1 | 回退到内置数据快照，回答中注明数据时间 |
| 401 Token 无效/过期 | 提示「401：Token 无效、过期或未提供」 | 不回退静默失败，明确告知用户 |
| 429 触发限流 | 提示降低频率 | 脚本每次调用间隔 0.2s，批量场景加退避 |
| 网络不可达 | 提示网络错误 | 页面本身纯静态，功能不受影响 |
| 门店查询无结果 | 返回空列表 | 引导用户打开官方门店地图手动查找 |

## 7. 合规

- 不使用任何非公开接口，仅通过官方 MCP Server 与官方网页可得数据。
- 不存储、不转发用户的身体数据；所有计算在浏览器本地完成。
- 输出标注「非麦当劳官方产品」「不构成医疗或营养建议」。
- 商标、餐品图片版权归麦当劳公司所有，本项目仅作技术演示，不暗示官方背书。
