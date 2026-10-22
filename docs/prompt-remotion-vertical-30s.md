# 30 秒竖屏宣传动画 · 生成提示词（Remotion 版）

> 用法：整段复制代码块给写代码的 AI（WorkBuddy / Cursor / DSH 都行）。  
> 它会产出一个 **独立的 Remotion 工程**，渲染出真正的 mp4，不是 HTML 播片。  
> 同目录下的 `prompt-promo-30s.md` 是旧的 HTML 播片版，两者留一个就行。
>
> 当前 solidified 的 12 项决策已写死在下文中，AI 不需要再问。

---

```text
你是 Remotion 动效工程师。请为一个叫「麦搭 MCD Fit Planner」的项目做一支 30 秒竖屏宣传动画。

## 交付物
一个独立的 Remotion 4.x + TypeScript 工程（目录名 mcd-fit-planner-promo），
能跑通 `npx remotion studio` 预览，也能跑通 `npx remotion render` 导出真正的 mp4。
不要产 HTML 播片，不要产 Lottie，不要产 canvas。

## 项目一句话
输入身体数据和每日运动量 → 算出今天能吃多少卡 → 从麦当劳官方营养数据里
为早/午/晚/加餐各配一套具体到单品的组合 → 和《中国居民膳食指南》逐项对照。
营养数据走麦当劳 MCP 实时查询。

## 工程初始化
npm create video@latest 生成骨架，template 选空白即可。
依赖锁定 npx create-video@latest 给的默认版本，不要手动降级 React 或 Remotion。
package.json 里加两个脚本：
    "bgm": "node scripts/make-bgm.mjs"
    "render": "remotion render PromoVertical out/promo-1080x1920.mp4 --codec=h264 --crf=18"
    "cover": "remotion still PromoVertical out/cover.png --frame=899"

## 目录结构（按这个来）
promo/
  package.json  remotion.config.ts
  scripts/make-bgm.mjs          # 离线合成 bgm
  public/bgm.wav
  src/
    index.ts                    # registerRoot(RemotionRoot)
    Root.tsx                    # 注册 Composition
    theme.ts                    # 色板 / 字号 / 缓动常量，唯一出处
    types.ts                    # plan.json 的类型
    data/plan.json              # ← 真实数据，见下方「数据来源」
    data/index.ts               # import plan from './plan.json'，导出类型化常量
    components/
      Layout.tsx                # StageShell：三段式骨架
      Arches.tsx                # 自绘金色拱门 SVG
      Marquee.tsx               # 底部技术跑马灯
      Disclaimer.tsx            # 右下角免责角标
      NumberFlow.tsx            # 帧驱动数字滚动
      MealCard.tsx  GuideRow.tsx
    scenes/
      Scene1Hook.tsx … Scene6Outro.tsx

## Composition 参数
id: "PromoVertical"
dimensions: 1080 × 1920（9:16 竖屏）
fps: 30
durationInFrames: 900        （恰好 30.0 秒）
不要注册第二个 Composition，只做竖屏。

## 三段式版面（贯穿全片，不要变）
┌────────────────────────────┐
│ 顶部品牌条  高 96px         │  左侧自绘金色拱门 SVG（44px）+ 「麦搭 MCD Fit Planner」
│                            │  右侧灰色小字「30s · MCP 实时数据」
├────────────────────────────┤
│                            │
│     中部主舞台  flex:1      │  每幕内容在这里演出
│                            │
├────────────────────────────┤
│ 底部跑马灯条  高 96px       │  技术参数横向循环滚动
└────────────────────────────┘
右下角免责角标为绝对定位浮层，全程可见（见下）。

## 视觉规范（写进 theme.ts，全片唯一出处）
- 主黄 #FFBC0D，主红 #DB0007，墨黑 #2D2D2D，次级灰 #4C4C4C，浅灰 #7F7F7F
- 主舞台背景 #F7F7F7；卡片纯白，圆角 22px，阴影 0 8px 24px rgba(0,0,0,.06)
- 字体栈：-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif
  ★ 不要用 @remotion/google-fonts，中文字体体积是灾难；用系统字体栈即可
- 竖屏字号：主标 92px / 次级 56px / 正文 34px / 单位与脚注 24px
  强调数字 800 字重 + 负字距 -0.03em；单位（kcal / g / mg）小一号 + #7F7F7F
- 缓动：spring({ damping: 200 }) 用于元素进场；interpolate + easeOutCubic 用于数值

## 金色拱门（Arches.tsx）
两段 path + 圆头描边自己画，主黄填充。禁止引用任何麦当劳官方 logo 位图。

## 帧教动
★ 最重要的一条：Remotion 渲染是逐帧截图，**禁止使用 CSS animation / transition /
requestAnimationFrame / setTimeout**。所有动效必须由 `useCurrentFrame()` 驱动，
配 `interpolate()` 和 `spring()`。任何 CSS 过渡在导出时都会错位或消失。
- 数值滚动用 NumberFlow：`spring()` 插值 × 目标值，整数显示、保留千分位
- 每幕写成独立组件 `Scene1` … `Scene6`，在 Root.tsx 里用 <Sequence from={} durationInFrames={}>
  挂载，时间偏移量集中写在一个 SCENES 常量数组里，不要散落魔法数字

## 分镜（30fps，共 900 帧）

第 1 幕 HOOK        帧 0–120    (0.0–4.0s)
  墨黑背景，中央浮出一行竖排大字：「在麦当劳减肥，／一天能吃什么？」
  字逐个跳入（每字错峰 4 帧，spring 回弹），下方掉一行灰色小字
  「28 岁 · 172cm · 78kg · 目标 70kg」；最后 12 帧整体提亮闪一下，切入白底。

第 2 幕 PROFILE     帧 120–300  (4.0–10.0s)
  中央落下白色圆角卡片「你的身体档案」，从下方 60px spring 弹入。
  六行字段依次点亮填入（每行错峰 8 帧）：
    性别 男 ／ 年龄 28 ／ 身高 172 cm ／ 体重 78 → 70 kg ／ 周期 12 周 ／ 轻度活动
  卡片页脚两行实时跳数：「今日目标 1,914 kcal」「预计 0.43 kg / 周」

第 3 幕 ENERGY      帧 300–480  (10.0–16.0s)
  卡片原地翻成「今日能量账本」，四行数字从上到下依次累加（用 NumberFlow）：
    基础代谢 BMR      1,720 kcal
    日常活动 PAL 1.30  2,236 kcal
    运动消耗（日均）       156 kcal
    ────────────────────────
    每日总消耗 TDEE   2,392 kcal
  随后右侧画一圈红色环形进度到 80%，环心数字停在「1,914」，下方标注「缺口 478 kcal」

第 4 幕 MEALS       帧 480–720  (16.0–24.0s)
  四张餐卡（早/午/晚/加餐）从底部依次上升入场，每张间隔 22 帧。
  每张卡：标题 = 餐次 + 预算 kcal；内部单品行逐条淡入（每行错峰 6 帧），
  显示「品名（份量）  kcal」；卡片底部合计数字滚动。
  四张全部到位后，画面底部浮出一条墨黑汇总条：
  「全天 1,800 kcal　蛋白 95g　脂肪 82g　碳水 164g」

第 5 幕 GUIDE       帧 720–840  (24.0–28.0s)
  一张 8 行营养对照表，逐行点亮（每行 6 帧）。
  达标行左侧打绿色对勾；不达标行整行淡红。最后 18 帧左侧浮出一行小字注解。
  8 行顺序：能量 / 蛋白质 / 脂肪 / 碳水化合物 / 糖 / 钠 / 膳食纤维 / 钙

第 6 幕 OUTRO       帧 840–900  (28.0–30.0s)
  主标逐字浮现：「用麦当劳，搭出你的一天。」
  副标两行淡入：「132 个 SKU · 麦当劳 MCP 实时数据」「开源 · 非麦当劳官方产品」
  最后 30 帧完全静止（留作封面帧）。

## 数据来源 —— 必须走 file，不许硬编码在组件里
src/data/plan.json 由配餐引擎产出（命令附在文末注释里），字段结构是：
  profile  { sex, age, height, weight, target, weeks, pal, met, days, minutes, prefs }
  energy   { bmr, activity, exercise_daily, tdee, target_kcal, deficit, bmi,
             protein, fat, carb }          ← 数值是浮点，显示时 Math.round
  meals[]  { meal, share, target_kcal,
             items[] { name, portion, kcal, protein, fat, carb, sodium },
             totals  { kcal, protein, fat, carb, sodium, sugar, fiber, calcium, sat_fat } }
  total    { kcal, protein, fat, carb, sodium, sugar, fiber, calcium, sat_fat }
  actual_share_pct { protein, fat, carb }   ← 整型百分数
组件里一律从 data/index.ts 读，不要在 JSX 里写死 1720 / 2392 这种数字。
如果只是参展演示、拿不到 plan.json，就按下面这组真实值先建一份占位 file，
并在 data/index.ts 顶部注明「占位数据，跑通气后替换」：

  档案  男 / 22 岁 / 170cm / 80kg → 65kg / 20 周 / PAL 1.20 / MET 4.3 / 每周 2 次 25 分钟 / BMI 27.7
  能量  BMR 1757.5 · 日常活动 2109.0 · 运动日均 40.95 · TDEE 2149.95 · 目标摄入 1933.25 · 缺口 216.70
  全天  1800 kcal / 蛋白 95g / 脂肪 82g / 碳水 164g / 钠 2555mg / 糖 36g / 纤维 17g / 钙 609mg
        供能比 蛋白 21% / 脂肪 41% / 碳水 36%
  早餐 483 kcal：原味板烧鸡腿炒双蛋堡（1个）419 + 热美式（中）13
  午餐 677 kcal：培根蔬萃双层牛堡（1个）442 + 薯条（小）210 + 冰美式（中）13
  晚餐 580 kcal：双层深海鳕鱼堡（1个）485 + 玉米杯（大）87 + 锡兰红茶（默认）2
  加餐 193 kcal：纯牛奶（盒装）（默认）129
  MCP 返回 158 条营养数据，覆盖 132 个 SKU

## 底部技术跑马灯（Marquee.tsx）
整条文案拼成一串，横向匀速滚动，一屏宽度约 10 秒走完一遍，无缝循环。
内容是这一句（不要增删）：
  「麦当劳 MCP 实时返回 158 条营养数据 → 名称归一化匹配 132 个 SKU · 全天束搜索 beam=160 ·
    四餐配比 25 / 35 / 30 / 10% · 对照《中国居民膳食指南 2022》 · 数据快照更新 2025-04」
字号 24px，#7F7F7F。

## 免责角标（Disclaimer.tsx）
右下角绝对定位，距边 32px，字号 22px，颜色 #7F7F7F，
文案「非麦当劳官方产品 · 营养数据来源麦当劳公开信息与 MCP」。
**全程可见（第 1 幕到第 6 幕都在），尾帧不额外放大、不额外居中加一版。**

## 背景音乐 scripts/make-bgm.mjs
用 Node 内置能力合成，不许引 npm 音频包、不许下载素材：
- 输出 public/bgm.wav：44100 Hz、16-bit、单声道、时长精确 30.000s（1323000 帧）
- 纯手写 WAV header（RIFF / fmt / data 三个 chunk），PCM 采样自己算浮点数写入
- 128 BPM，4/4 拍 = 每拍 0.46875s，共 16 小节：
    kick  ：每拍第 1、3 拍，60Hz 正弦 + 8ms 指数衰减包络
    hihat ：每半拍，白噪声 + 25ms 衰减，音量 0.18
    pad   ：Am → F → C → G 循环，每和弦 2 小节，正弦叠加 + 缓慢 attack
- 整体音量 0.55；开头 0.5s 淡入，结尾 1.0s 淡出
- 脚本幂等：重复运行结果逐字节一致（用固定 seed 的伪随机或直接数学序列）
在 Root.tsx 里用 <Audio src={staticFile('bgm.wav')} /> 挂载。

## 禁止事项
- 不用 CSS animation / transition / setTimeout / requestAnimationFrame（导出会错亂）
- 不出现麦当劳官方 logo 位图、官方字体、门店实拍
- 不出现「官方」「授权」「合作」「联合出品」这类暗示性表述
- 不用 emoji 当图标；不用花哨渐变；不做弹跳过头的廉价动效
- 不在画面上堆字：每幕只留一句主文案 + 一组数字

## 交付前自检（逐条确认后再交给我）
1. npx remotion studio 能开，六幕按时间点出现，无控制台报错
2. npx remotion render PromoVertical out/promo.mp4 --codec=h264 成功，**时长恰好 30.0 秒**
3. npx remotion still PromoVertical out/cover.png --frame=899 产出封面 PNG（1080×1920）
4. 断开网络重跑一次，渲染依然成功（零外部请求）
5. 抽帧核对：第 3 幕停在 1,758 / 2,109 / 41 / 2,150 / 1,933，与上表逐位一致
6. 右下角免责角标在第 1 幕截图里就能看到

先输出完整工程代码，再用 5 行说明每一幕的实现要点。
```

---

## plan.json 怎么来

配餐引擎在 `mcd-fit-planner/` 主仓库里。生成占位数据的命令：

```bash
cd mcd-fit-planner
python scripts/run_planner.py \
  --sex male --age 22 --height 170 --weight 80 --target 65 --weeks 20 \
  --pal 1.2 --met 4.3 --days 2 --minutes 25 --offline --json \
  > promo/src/data/plan.json
```

去掉 `--offline` 就会走麦当劳 MCP 拉实时营养数据（需要 Token）。

---

## 想微调的话

| 需求              | 改哪里                                                         |
| --------------- | ----------------------------------------------------------- |
| 换成别人（比如 35 岁女生） | 重跑一次上面的命令覆盖 plan.json，动画自动跟着变                               |
| 想要横版 1920×1080  | Composition 改尺寸，Scene4 的卡片改成 2×2，其余不用动                      |
| 拉长到 60 秒        | 给 Scene3 / Scene4 各加 15 秒（180 / 450 帧），同步改 durationInFrames |
| 去掉背景音乐          | 删掉 Root.tsx 里的 `<Audio>`，scripts/make-bgm.mjs 保留不用跑         |
| 换个配色            | 只改 theme.ts，全片跟随                                            |
| 想要泥某个具体 SKU     | 改 plan.json 里的 meals[].items，别改组件                           |
