/* ============================================================
   麦搭 · MCD Fit Planner — 计算引擎 + 配餐算法
   数据：麦当劳中国官方营养计算器（2025-04 更新）
   参考：中国居民膳食指南（2022）/ 中国居民膳食营养素参考摄入量（2023）
   ============================================================ */
(function () {
  'use strict';

  var DATA = window.MCD_NUTRITION || [];
  var $ = function (id) { return document.getElementById(id); };
  var num = function (v, d) {
    var n = parseFloat(v);
    return isFinite(n) ? n : d;
  };
  var clamp = function (v, lo, hi) { return Math.max(lo, Math.min(hi, v)); };
  var round = function (v) { return Math.round(v); };
  var pad = function (v, n) { return v.toFixed(n); };

  /* ---------- 常量：指南推荐值 ---------- */
  var GUIDE = {
    proteinPerKg: [1.2, 1.6],   // 减脂期每公斤体重蛋白质（g/kg）
    fatRatio: [0.20, 0.30],     // 脂肪供能比
    carbRatio: [0.50, 0.65],    // 碳水供能比
    sugarMax: 25,               // 添加糖（g/d，指南建议控制在 25g 以下）
    sodiumMax: 2000,            // 钠（mg/d，约食盐 5g）
    fiber: [25, 30],            // 膳食纤维（g/d）
    calcium: 800,               // 钙（mg/d）
    bmiNormal: [18.5, 23.9]
  };

  /* ---------- 餐次分配 ---------- */
  var MEALS = [
    { key: 'breakfast', name: '早餐', badge: '早', share: 0.25, slots: ['bmain', 'blight'] },
    { key: 'lunch',     name: '午餐', badge: '午', share: 0.35, slots: ['burger', 'side', 'drink'] },
    { key: 'dinner',    name: '晚餐', badge: '晚', share: 0.30, slots: ['burger', 'side', 'drink'] },
    { key: 'snack',     name: '加餐', badge: '加', share: 0.10, slots: ['snack'] }
  ];

  /* ---------- 候选池 ---------- */
  var POOLS = {
    bmain: [
      ['猪柳麦满分', '1个'], ['猪柳蛋麦满分', '1个'], ['双层猪柳蛋麦满分', '1个'],
      ['火腿扒麦满分', '1个'], ['大脆鸡扒麦满分', '1个'], ['原味板烧鸡腿麦满分', '默认'],
      ['双层原味板烧鸡腿麦满分', '1个'], ['原味板烧鸡腿炒双蛋堡', '1个'], ['猪柳炒双蛋堡', '1个'],
      ['火腿扒早安营养卷', '1个'], ['图林根香肠早安营养卷', '1个'],
      ['皮蛋鸡肉粥', '1份'], ['雪菜脆笋鸡肉粥', '1份']
    ],
    blight: [
      ['优品豆浆', '小'], ['纯牛奶（盒装）', '默认'], ['热美式', '中'],
      ['冰美式', '小'], ['锡兰红茶', '默认'], ['纯悦', '默认']
    ],
    burger: [
      ['巨无霸', '1个'], ['汉堡包', '1个'], ['麦辣鸡腿汉堡', '1个'], ['板烧鸡腿堡', '1个'],
      ['麦香鸡', '1个'], ['麦香鱼', '1个'], ['吉士汉堡包', '1个'], ['双层吉士汉堡', '1个'],
      ['不素之霸双层牛堡', '1个'], ['双层深海鳕鱼堡', '1个'], ['培根安格斯厚牛堡', '1个'],
      ['芝士安格斯厚牛堡', '1个'], ['培根蔬萃双层牛堡', '1个']
    ],
    side: [
      ['玉米杯', '小'], ['玉米杯', '大'], ['苹果片', '默认'], ['薯条', '迷你'],
      ['薯条', '小'], ['麦乐鸡 (5块)', '5块'], ['麦辣鸡翅', '2块'],
      ['薄皮焦香V翅', '2块'], ['脆脆薯条', '中']
    ],
    drink: [
      ['无糖可口可乐', '中'], ['纯悦', '默认'], ['冰美式', '中'], ['锡兰红茶', '默认'],
      ['可口可乐', '小'], ['100%苹果汁', '1盒'], ['纯牛奶（盒装）', '默认']
    ],
    snack: [
      ['苹果片', '默认'], ['玉米杯', '小'], ['玉米杯', '大'], ['圆筒冰淇淋', '1个'],
      ['迷你朱古力新地', '1份'], ['迷你草莓新地', '1份'], ['冰美式', '中'],
      ['纯牛奶（盒装）', '默认'], ['麦乐鸡 (5块)', '5块'], ['薯条', '小']
    ]
  };

  var INDEX = {};
  function reindex() {
    INDEX = {};
    DATA.forEach(function (d) { INDEX[d.name + '|' + d.portion] = d; });
  }
  reindex();

  function item(name, portion) {
    var d = INDEX[name + '|' + portion];
    return d ? Object.assign({}, d) : null;
  }

  /* ---------- 偏好过滤 ---------- */
  var PREF_RULES = {
    no_beef: function (d) { return !/牛/.test(d.name); },
    no_spicy: function (d) { return !/辣/.test(d.name); },
    no_fish: function (d) { return !/鱼|鳕|虾/.test(d.name); }
  };

  function buildPool(slot, prefs) {
    var list = (POOLS[slot] || []).map(function (p) { return item(p[0], p[1]); })
      .filter(function (d) {
        if (!d) return false;
        return !Object.keys(PREF_RULES).some(function (k) {
          return prefs.has(k) && !PREF_RULES[k](d);
        });
      });
    return list.length ? list : (POOLS[slot] || []).map(function (p) { return item(p[0], p[1]); }).filter(Boolean);
  }

  /* ---------- 能量计算 ---------- */
  function calcEnergy(p) {
    // Mifflin-St Jeor
    var bmr = 10 * p.weight + 6.25 * p.height - 5 * p.age + (p.sex === 'male' ? 5 : -161);
    var palKcal = bmr * p.pal;
    var exPerSession = p.met * p.weight * (p.exMin / 60);          // 单次运动 kcal
    var exDaily = exPerSession * p.exDays / 7;                     // 日均摊分
    var tdee = bmr * p.pal + exDaily;

    var bmi = p.weight / Math.pow(p.height / 100, 2);

    // 缺口：按目标体重与周期反算，再受安全上限约束
    var need = 0;
    var direction = 'lose';
    if (p.target < p.weight - 0.2) {
      need = ((p.weight - p.target) * 7700) / (p.weeks * 7);
    } else if (p.target > p.weight + 0.2) {
      direction = 'gain';
      need = -(((p.target - p.weight) * 7700) / (p.weeks * 7));
    } else {
      direction = 'keep';
    }

    var floor = Math.max(bmr * 1.1, p.sex === 'male' ? 1500 : 1200);
    var maxDeficit = Math.min(tdee * 0.20, 750);
    var deficit = clamp(need, -400, maxDeficit);

    var targetKcal = tdee - deficit;
    var limited = false;
    if (targetKcal < floor) { targetKcal = floor; deficit = tdee - targetKcal; limited = true; }
    if (targetKcal > tdee + 400) { targetKcal = tdee + 400; deficit = tdee - targetKcal; }

    // 宏量分配
    var pTargetKg = direction === 'lose' ? p.target : p.weight;
    var protein = clamp(1.25 * pTargetKg, 1.2 * pTargetKg, 1.6 * pTargetKg);
    protein = Math.min(protein, 0.25 * targetKcal / 4);

    var fat = clamp(0.25 * targetKcal / 9, 0.6 * p.weight, 0.30 * targetKcal / 9);
    var carb = (targetKcal - protein * 4 - fat * 9) / 4;

    // 碳水低于指南下限时，压脂肪、压蛋白补回来
    if (carb * 4 / targetKcal < GUIDE.carbRatio[0]) {
      fat = 0.20 * targetKcal / 9;
      protein = Math.max(1.2 * pTargetKg, Math.min(protein, 0.22 * targetKcal / 4));
      carb = (targetKcal - protein * 4 - fat * 9) / 4;
    }

    return {
      bmr: bmr, palKcal: palKcal, exDaily: exDaily, exPerSession: exPerSession,
      tdee: tdee, targetKcal: targetKcal, deficit: deficit, direction: direction,
      limited: limited, bmi: bmi, protein: protein, fat: fat, carb: carb,
      proteinPct: protein * 4 / targetKcal, fatPct: fat * 9 / targetKcal, carbPct: carb * 4 / targetKcal
    };
  }

  /* ---------- 汇总与代价函数 ---------- */
  var ZERO = { kcal: 0, protein: 0, fat: 0, carb: 0, sodium: 0, sugar: 0, fiber: 0, calcium: 0, sat_fat: 0 };

  function sumItems(list) {
    return list.reduce(function (a, d) {
      return {
        kcal: a.kcal + d.kcal, protein: a.protein + d.protein, fat: a.fat + d.fat,
        carb: a.carb + d.carb, sodium: a.sodium + d.sodium, sugar: a.sugar + d.sugar,
        fiber: a.fiber + d.fiber, calcium: a.calcium + d.calcium, sat_fat: a.sat_fat + d.sat_fat
      };
    }, Object.assign({}, ZERO));
  }

  function addSum(a, b) {
    return {
      kcal: a.kcal + b.kcal, protein: a.protein + b.protein, fat: a.fat + b.fat,
      carb: a.carb + b.carb, sodium: a.sodium + b.sodium, sugar: a.sugar + b.sugar,
      fiber: a.fiber + b.fiber, calcium: a.calcium + b.calcium, sat_fat: a.sat_fat + b.sat_fat
    };
  }

  /* 全天代价：热量贴合 > 蛋白质达标 > 脂肪/钠/糖不超标 > 纤维/钙 */
  function dayCost(s, e) {
    var t = e.targetKcal;
    var fatCeil = 0.30 * t / 9;                 // 指南脂肪供给上限
    var carbFloor = 0.50 * t / 4;               // 指南碳水供给下限
    var c = Math.abs(s.kcal - t) / t * 900;
    c += Math.max(0, e.protein - s.protein) / Math.max(e.protein, 1) * 430;
    c += Math.max(0, s.fat - fatCeil) / fatCeil * 650;
    c += Math.max(0, carbFloor - s.carb) / carbFloor * 620;
    c += Math.max(0, s.sodium - GUIDE.sodiumMax) / GUIDE.sodiumMax * 220;
    c += Math.max(0, s.sugar - 30) / 30 * 140;
    c += Math.max(0, GUIDE.fiber[0] - s.fiber) / GUIDE.fiber[0] * 70;
    c += Math.max(0, GUIDE.calcium - s.calcium) / GUIDE.calcium * 40;
    return c;
  }

  function combos(slotList) {
    var out = [[]];
    slotList.forEach(function (pool) {
      var next = [];
      out.forEach(function (prefix) {
        pool.forEach(function (d) { next.push(prefix.concat([d])); });
      });
      out = next;
    });
    return out;
  }

  /* ---------- 伪随机（保证「换一套」有变化但可复现） ---------- */
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  /* ---------- 单餐候选 ---------- */
  function mealCandidates(meal, target, prefs) {
    var pools = meal.slots.map(function (s) { return buildPool(s, prefs); });
    var all = combos(pools);
    var out = [];
    var naCap = GUIDE.sodiumMax * meal.share;

    all.forEach(function (list) {
      var s = sumItems(list);
      if (s.kcal < target.kcal * 0.5 || s.kcal > target.kcal * 1.7) return;
      var c = Math.abs(s.kcal - target.kcal) / Math.max(target.kcal, 1) * 320;
      c += Math.max(0, target.protein - s.protein) / Math.max(target.protein, 1) * 170;
      c += Math.max(0, s.fat - target.fat * 1.2) / Math.max(target.fat, 1) * 130;
      c += Math.max(0, s.sodium - naCap) / Math.max(naCap, 1) * 110;
      c += Math.max(0, s.sugar - 8) / 8 * 70;
      if (prefs.has('low_sodium')) c += s.sodium / 1000 * 25;
      if (prefs.has('high_protein')) c += Math.max(0, target.protein * 1.25 - s.protein) / Math.max(target.protein, 1) * 90;
      out.push({
        items: list, sum: s, cost: c, target: target,
        sig: list.map(function (d) { return d.name + d.portion; }).join('|')
      });
    });

    out.sort(function (a, b) { return a.cost - b.cost; });
    return out;
  }

  var BEAM = 160;
  var TOPK = { breakfast: 18, lunch: 42, dinner: 42, snack: 10 };

  /* ---------- 生成一天：逐餐束搜索 ---------- */
  function planDay(profile, seed) {
    var e = calcEnergy(profile);
    var rnd = mulberry32(seed || 1);

    var cum = 0;
    var shareCum = MEALS.map(function (m) { cum += m.share; return cum; });

    var beam = [{ sums: Object.assign({}, ZERO), cost: 0, meals: [] }];

    MEALS.forEach(function (m, mi) {
      var target = {
        kcal: e.targetKcal * m.share,
        protein: e.protein * m.share,
        fat: e.fat * m.share
      };
      var cands = mealCandidates(m, target, profile.prefs).slice(0, TOPK[m.key] || 12);
      if (!cands.length) return;

      var next = [];
      beam.forEach(function (b) {
        var used = {};
        b.meals.forEach(function (mm) {
          mm.items.forEach(function (d) { used[d.name] = true; });
        });
        cands.forEach(function (c) {
          var pen = 0;
          c.items.forEach(function (d) {
            if (used[d.name]) pen += (d.category === '饮品' || d.category === 'McCafé 饮品及其他') ? 30 : 95;
          });
          next.push({
            sums: addSum(b.sums, c.sum),
            cost: b.cost + c.cost + pen,
            meals: b.meals.concat([c]),
            target: target
          });
        });
      });

      // 逐餐向「已完成餐次的累计目标」收敛，避免全天系统性偏低
      var partial = e.targetKcal * shareCum[mi];
      next.forEach(function (n) {
        n.cost += Math.abs(n.sums.kcal - partial) / partial * 300;
      });
      next.sort(function (a, b) { return a.cost - b.cost; });
      beam = next.slice(0, BEAM);
    });

    var ranked = beam.map(function (b) {
      return { b: b, total: b.cost + dayCost(b.sums, e) };
    }).sort(function (a, b) { return a.total - b.total; });

    // 前几名里按权重随机，保证「换一整套」会有变化
    var top = ranked.slice(0, 5);
    var pick = top[Math.min(top.length - 1, Math.floor(rnd() * rnd() * top.length))] || ranked[0];

    var plan = pick.b.meals.map(function (c, i) {
      return {
        meal: MEALS[i], target: c.target,
        items: c.items, sum: c.sum, sig: c.sig
      };
    });

    return {
      energy: e, meals: plan, total: pick.b.sums, profile: profile, seed: seed
    };
  }

  /* ---------- 状态 ---------- */
  var state = { sex: 'male', prefs: new Set(), plan: null, seed: 7 };

  function readProfile() {
    return {
      sex: state.sex,
      age: clamp(num($('age').value, 28), 14, 90),
      height: clamp(num($('height').value, 172), 130, 220),
      weight: clamp(num($('weight').value, 78), 35, 200),
      target: clamp(num($('target').value, 70), 35, 200),
      weeks: clamp(num($('weeks').value, 12), 2, 52),
      pal: clamp(num($('pal').value, 1.3), 1.2, 1.65),
      met: clamp(num($('exType').value, 0), 0, 12),
      exDays: clamp(num($('exDays').value, 0), 0, 7),
      exMin: clamp(num($('exMin').value, 0), 0, 240),
      prefs: state.prefs
    };
  }

  /* ---------- 档案摘要 / 弹框 ---------- */
  var PREF_LABEL = {
    no_beef: '不吃牛肉', no_spicy: '不吃辣', no_fish: '不吃鱼',
    low_sodium: '低钠', high_protein: '高蛋白'
  };

  function optionText(id) {
    var el = $(id);
    if (!el || !el.options || el.selectedIndex < 0) return '';
    return (el.options[el.selectedIndex].text || '').replace(/（[^）]*）/g, '').trim();
  }

  function renderSummary() {
    var box = $('summaryChips');
    if (!box) return;
    var p = readProfile();
    var chips = [
      (p.sex === 'male' ? '男' : '女') + ' · <b>' + p.age + '</b> 岁',
      '<b>' + p.height + '</b> cm',
      '<b>' + p.weight + '</b> kg → <b>' + p.target + '</b> kg',
      '<b>' + p.weeks + '</b> 周',
      optionText('pal')
    ];
    if (p.met > 0 && p.exDays > 0 && p.exMin > 0) {
      chips.push(optionText('exType') + ' <b>' + p.exDays + '</b>×<b>' + p.exMin + '</b> 分/周');
    } else {
      chips.push('无额外运动');
    }

    var html = chips.map(function (c) {
      return '<span class="pchip">' + c + '</span>';
    }).join('');

    state.prefs.forEach(function (k) {
      html += '<span class="pchip accent">' + (PREF_LABEL[k] || k) + '</span>';
    });

    box.innerHTML = html;
  }

  function updatePreview() {
    if (!$('previewKcal')) return;
    var e = calcEnergy(readProfile());
    $('previewKcal').textContent = fmt(e.targetKcal);
    var perWeek = e.deficit * 7 / 7700;
    var pace = e.direction === 'keep'
      ? '维持体重'
      : (e.deficit > 0
        ? '约 ' + Math.abs(perWeek).toFixed(2) + ' kg/周'
        : '约增 ' + Math.abs(perWeek).toFixed(2) + ' kg/周');
    $('previewPace').textContent = '总消耗 ' + fmt(e.tdee) + ' · ' + pace;
  }

  function openProfile() {
    var m = $('profileModal');
    if (!m) return;
    m.hidden = false;
    document.body.classList.add('modal-open');
    updatePreview();
    setTimeout(function () { if ($('age')) $('age').focus(); }, 80);
  }

  function closeProfile() {
    var m = $('profileModal');
    if (!m) return;
    m.hidden = true;
    document.body.classList.remove('modal-open');
  }

  /* ---------- 渲染 ---------- */
  function fmt(n) { return round(n).toLocaleString('en-US'); }

  function renderEnergy(plan) {
    var e = plan.energy;
    $('bmrVal').textContent = fmt(e.bmr);
    $('palVal').textContent = fmt(e.palKcal);
    $('exVal').textContent = fmt(e.exDaily);
    $('tdeeVal').textContent = fmt(e.tdee);
    $('targetVal').textContent = fmt(e.targetKcal);
    $('heroKcal').textContent = fmt(e.targetKcal);

    $('bmrFoot').textContent = 'Mifflin-St Jeor';
    $('palFoot').textContent = 'PAL ' + plan.profile.pal.toFixed(2) + ' × BMR';
    $('exFoot').textContent = plan.profile.met > 0
      ? plan.profile.exDays + ' 天 × ' + plan.profile.exMin + ' 分钟'
      : '未开启运动';
    $('bmiFoot').textContent = 'BMI ' + e.bmi.toFixed(1) + ' · ' + bmiLabel(e.bmi);

    var ratio = clamp(e.targetKcal / e.tdee, 0, 1);
    var C = 2 * Math.PI * 66;
    $('ringFg').style.strokeDasharray = C.toFixed(1);
    $('ringFg').style.strokeDashoffset = (C * (1 - ratio)).toFixed(1);

    $('deficitVal').textContent = e.deficit >= 0
      ? '−' + round(e.deficit) + ' kcal'
      : '+' + round(-e.deficit) + ' kcal';

    var perWeek = e.deficit * 7 / 7700;
    if (e.direction === 'keep') {
      $('paceVal').textContent = '维持体重';
    } else if (e.deficit > 0) {
      $('paceVal').textContent = '约 ' + Math.abs(perWeek).toFixed(2) + ' kg / 周';
    } else {
      $('paceVal').textContent = '约增 ' + Math.abs(perWeek).toFixed(2) + ' kg / 周';
    }

    $('proteinTargetVal').textContent = round(e.protein) + ' g';
    $('proteinTargetVal').textContent += ' / ' + Math.round(e.proteinPct * 100) + '%E';

    var notes = [];
    if (e.bmi < GUIDE.bmiNormal[0]) {
      notes.push('BMI 低于 18.5，属于体重偏低，不建议继续减脂，可以把目标改成维持或增重。');
    } else if (e.bmi >= 28) {
      notes.push('BMI 达到肥胖区间，减重建议在医生或营养师指导下进行。');
    }
    if (e.limited) {
      notes.push('按你填的周期，所需缺口超过了安全上限，已按「不低于基础代谢 1.1 倍」的热量下限兜底，实际达成会比你设定的慢一些。');
    }
    if (plan.profile.met > 0) {
      notes.push('单次运动约消耗 ' + fmt(e.exPerSession) + ' kcal，已按每周 ' + plan.profile.exDays + ' 天摊到每天。');
    }
    if (!notes.length) {
      notes.push('热量缺口控制在总消耗的 20% 以内，蛋白质按每公斤目标体重 1.2–1.6 g 配，减脂期尽量不掉肌肉。');
    }
    var noteEl = $('energyNote');
    noteEl.textContent = notes.join(' ');
    noteEl.className = 'energy-note' + (e.bmi < 18.5 || e.bmi >= 28 || e.limited ? ' alert' : '');
  }

  function bmiLabel(bmi) {
    if (bmi < 18.5) return '偏低';
    if (bmi < 24) return '正常';
    if (bmi < 28) return '超重';
    return '肥胖';
  }

  function renderMeals(plan) {
    var grid = $('mealGrid');
    grid.innerHTML = plan.meals.map(function (p, i) {
      var over = p.sum.kcal > p.target.kcal * 1.1;
      return '' +
        '<article class="meal">' +
          '<div class="meal-head">' +
            '<div class="meal-name"><span class="meal-badge">' + p.meal.badge + '</span>' + p.meal.name + '</div>' +
            '<div class="meal-target">预算 ' + round(p.target.kcal) + ' kcal</div>' +
          '</div>' +
          '<ul class="meal-items">' +
            p.items.map(function (d) {
              return '<li><span class="item-name">' + d.name +
                '<span class="item-portion">' + d.portion + '</span></span>' +
                '<span class="item-kcal">' + d.kcal + ' kcal</span></li>';
            }).join('') +
          '</ul>' +
          '<div class="meal-foot">' +
            '<div class="meal-macros">' +
              '<span>蛋白 <b>' + round(p.sum.protein) + 'g</b></span>' +
              '<span>脂肪 <b>' + round(p.sum.fat) + 'g</b></span>' +
              '<span>碳水 <b>' + round(p.sum.carb) + 'g</b></span>' +
              '<span>钠 <b>' + round(p.sum.sodium) + 'mg</b></span>' +
            '</div>' +
            '<button class="meal-swap" data-meal="' + i + '">换一换</button>' +
          '</div>' +
        '</article>';
    }).join('');

    Array.prototype.forEach.call(grid.querySelectorAll('.meal-swap'), function (btn) {
      btn.addEventListener('click', function () {
        swapMeal(parseInt(btn.getAttribute('data-meal'), 10));
      });
    });

    // 全天合计
    var t = plan.total, e = plan.energy;
    $('dayKcal').textContent = fmt(t.kcal);
    var diff = t.kcal - e.targetKcal;
    $('dayDiff').textContent = (diff >= 0 ? '超出目标 ' : '低于目标 ') + Math.abs(round(diff)) + ' kcal';
    $('dayBars').innerHTML = [
      { label: '蛋白质', v: t.protein, max: e.protein, unit: 'g' },
      { label: '脂肪', v: t.fat, max: e.fat, unit: 'g' },
      { label: '碳水', v: t.carb, max: e.carb, unit: 'g' }
    ].map(function (b) {
      var pct = clamp(b.v / b.max * 100, 0, 100);
      var over = b.v > b.max * 1.1;
      return '<div class="day-bar">' +
        '<div class="day-bar-top"><span>' + b.label + '</span><span>' +
        round(b.v) + ' / ' + round(b.max) + ' ' + b.unit + '</span></div>' +
        '<div class="day-bar-track"><div class="day-bar-fill' + (over ? ' over' : '') +
        '" style="width:' + pct.toFixed(1) + '%"></div></div></div>';
    }).join('');

    renderGuide(plan);
  }

  function renderGuide(plan) {
    var t = plan.total, e = plan.energy;
    var rows = [
      {
        name: '能量', val: round(t.kcal) + ' kcal',
        range: round(e.targetKcal) + ' kcal',
        state: Math.abs(t.kcal - e.targetKcal) / e.targetKcal <= 0.06 ? 'ok' : (t.kcal > e.targetKcal ? 'high' : 'low')
      },
      {
        name: '蛋白质', val: round(t.protein) + ' g（' + Math.round(t.protein * 4 / e.targetKcal * 100) + '%E）',
        range: round(e.protein) + ' g（15–20%E）',
        state: t.protein >= e.protein * 0.85 ? 'ok' : 'low'
      },
      {
        name: '脂肪', val: round(t.fat) + ' g（' + Math.round(t.fat * 9 / t.kcal * 100) + '%E）',
        range: '20–30%E（≤ ' + round(0.30 * e.targetKcal / 9) + ' g）',
        state: judge(t.fat * 9 / t.kcal, GUIDE.fatRatio[0], GUIDE.fatRatio[1])
      },
      {
        name: '碳水化合物', val: round(t.carb) + ' g（' + Math.round(t.carb * 4 / t.kcal * 100) + '%E）',
        range: '50–65%E（≥ ' + round(0.50 * e.targetKcal / 4) + ' g）',
        state: judge(t.carb * 4 / t.kcal, GUIDE.carbRatio[0], GUIDE.carbRatio[1])
      },
      {
        name: '糖（含天然乳糖）', val: round(t.sugar) + ' g',
        range: '< ' + GUIDE.sugarMax + ' g（添加糖建议值）',
        state: judge(t.sugar, 0, GUIDE.sugarMax)
      },
      {
        name: '钠', val: round(t.sodium) + ' mg',
        range: '< ' + GUIDE.sodiumMax + ' mg',
        state: judge(t.sodium, 0, GUIDE.sodiumMax)
      },
      {
        name: '膳食纤维', val: round(t.fiber) + ' g',
        range: GUIDE.fiber[0] + '–' + GUIDE.fiber[1] + ' g',
        state: judge(t.fiber, GUIDE.fiber[0], GUIDE.fiber[1])
      },
      {
        name: '钙', val: round(t.calcium) + ' mg',
        range: '800 mg',
        state: judge(t.calcium, GUIDE.calcium, null)
      }
    ];

    var map = { ok: ['达标', 'ok'], high: ['偏高', 'high'], low: ['偏低', 'low'] };
    $('guideBody').innerHTML = rows.map(function (r) {
      var m = map[r.state];
      return '<tr><td>' + r.name + '</td><td>' + r.val + '</td><td>' + r.range + '</td>' +
        '<td><span class="tag ' + m[1] + '">' + m[0] + '</span></td></tr>';
    }).join('');

    // 动态建议
    var tips = [];
    if (t.fiber < GUIDE.fiber[0]) {
      tips.push('全天膳食纤维只有 ' + round(t.fiber) + ' g，距指南的 25 g 还差 ' +
        round(GUIDE.fiber[0] - t.fiber) + ' g。麦当劳菜单里纤维最高的选择是玉米杯和苹果片，但仅靠它们仍不够，建议在麦当劳之外补 300–500 g 蔬菜和一份水果。');
    }
    if (t.fat * 9 / t.kcal > GUIDE.fatRatio[1]) {
      tips.push('脂肪供能比 ' + Math.round(t.fat * 9 / t.kcal * 100) + '%，高于指南的 20–30%（其中饱和脂肪约 ' +
        round(t.sat_fat) + ' g，指南建议低于 ' + round(e.targetKcal * 0.10 / 9) + ' g）。这是套餐结构问题：主餐和油炸小食贡献了绝大部分脂肪。' +
        '把一份油炸小食换成玉米杯或苹果片、主餐优先板烧鸡腿堡 / 麦香鱼 / 吉士汉堡包，可以把比例拉回来。');
    }
    if (t.carb * 4 / t.kcal < GUIDE.carbRatio[0]) {
      tips.push('碳水供能比 ' + Math.round(t.carb * 4 / t.kcal * 100) + '%，低于指南的 50–65%。麦当劳的碳水几乎全部来自汉堡面包，缺少米饭、面条和全谷物——' +
        '不用为了凑比例去多喝含糖饮料，更好的做法是在麦当劳之外补一份杂粮主食。');
    }
    if (t.sodium > GUIDE.sodiumMax) {
      tips.push('钠摄入 ' + round(t.sodium) + ' mg，已超过指南 2000 mg 的上限（约合食盐 5 g）。把一份带酱汉堡换成板烧鸡腿堡、薯条换成玉米杯，通常能省下 500 mg 以上的钠。');
    }
    if (t.sugar > GUIDE.sugarMax) {
      tips.push('糖合计 ' + round(t.sugar) + ' g，高于 25 g 的添加糖建议值（这一行是总糖，包含牛奶里的天然乳糖约 9 g）。' +
        '真正要盯的是含糖饮料：中杯可乐约 35 g 糖，换成无糖可乐或纯悦即可清零。');
    }
    if (e.proteinPct < 0.15) {
      tips.push('蛋白质供能比只有 ' + Math.round(e.proteinPct * 100) + '%，建议再加一个高蛋白单品（如麦乐鸡、板烧鸡腿堡）或一杯牛奶。');
    } else if (t.protein >= e.protein * 0.9) {
      tips.push('蛋白质 ' + round(t.protein) + ' g，基本达到减脂期目标，有助于在热量缺口下保住肌肉。');
    }
    tips.push('这份配餐只覆盖能量与主要营养素。麦当劳菜单缺少蔬菜和豆类，建议每天保留一餐（或加餐）吃麦当劳之外的食物，把蔬菜、全谷物和奶类补齐。');

    $('guideTips').innerHTML = tips.map(function (x) {
      return '<div class="guide-tip"><i>!</i><span>' + x + '</span></div>';
    }).join('');
  }

  function judge(v, lo, hi) {
    if (v < lo) return 'low';
    if (hi !== null && hi !== undefined && v > hi) return 'high';
    return 'ok';
  }

  /* ---------- 交互 ---------- */
  function build() {
    var profile = readProfile();
    var note = $('formNote');
    if (profile.target >= profile.weight) {
      note.textContent = profile.target > profile.weight + 0.2
        ? '目标体重高于当前体重，已切换为增重方案。'
        : '目标体重与当前体重一致，按维持体重计算。';
      note.className = 'form-note';
    } else if (profile.target < profile.weight * 0.85) {
      note.textContent = '目标体重低于当前的 85%，建议把周期拉长，避免过快减重。';
      note.className = 'form-note warn';
    } else {
      note.textContent = '';
      note.className = 'form-note';
    }
    state.plan = planDay(profile, state.seed);
    renderEnergy(state.plan);
    renderMeals(state.plan);
    window.MCDFit = { state: state, plan: state.plan, calcEnergy: calcEnergy, planDay: planDay };
    renderSummary();
  }

  function swapMeal(idx) {
    var plan = state.plan;
    if (!plan) return;
    var e = plan.energy;
    var p = plan.meals[idx];

    var others = plan.meals.reduce(function (a, m, i) {
      return i === idx ? a : addSum(a, m.sum);
    }, Object.assign({}, ZERO));

    var cands = mealCandidates(p.meal, p.target, plan.profile.prefs)
      .filter(function (c) { return c.sig !== p.sig; })
      .slice(0, 30);
    if (!cands.length) return;

    var scored = cands.map(function (c) {
      return { c: c, cost: dayCost(addSum(others, c.sum), e) + c.cost * 0.25 };
    }).sort(function (a, b) { return a.cost - b.cost; });

    var top = scored.slice(0, 3);
    var pick = top[Math.floor(Math.random() * top.length)];

    plan.meals[idx] = {
      meal: p.meal, target: p.target,
      items: pick.c.items, sum: pick.c.sum, sig: pick.c.sig
    };
    plan.total = plan.meals.reduce(function (a, m) { return addSum(a, m.sum); }, Object.assign({}, ZERO));
    renderMeals(plan);
  }

  /* ---------- 注入式预置（由 scripts/run_planner.py 导出个性化页面时使用） ---------- */
  function applyPreset(preset) {
    if (preset.nutrition && preset.nutrition.length) {
      DATA = preset.nutrition;
      reindex();
      $('skuCount').textContent = String(DATA.length);
    }

    var p = preset.profile || {};
    if (p.sex) {
      state.sex = p.sex;
      Array.prototype.forEach.call(document.querySelectorAll('#sexPills .pill'), function (x) {
        x.classList.toggle('is-on', x.getAttribute('data-sex') === p.sex);
      });
    }
    if (p.prefs && p.prefs.length) {
      p.prefs.forEach(function (k) { state.prefs.add(k); });
      Array.prototype.forEach.call(document.querySelectorAll('#prefChips .chip'), function (x) {
        if (state.prefs.has(x.getAttribute('data-pref'))) x.classList.add('is-on');
      });
    }

    var map = {
      age: p.age, height: p.height, weight: p.weight, target: p.target,
      weeks: p.weeks, pal: p.pal, exDays: p.days, exMin: p.minutes, exType: p.met
    };
    Object.keys(map).forEach(function (id) {
      if (map[id] !== undefined && map[id] !== null) $(id).value = map[id];
    });

    var src = $('dataSource');
    if (src && preset.data_source) src.textContent = preset.data_source;
    if (preset.generated_at && src) src.textContent += ' · ' + preset.generated_at;

    var sl = $('storeList');
    if (sl && preset.stores && preset.stores.length) {
      sl.innerHTML = preset.stores.slice(0, 5).map(function (s) {
        var dist = typeof s.distance === 'number' ? s.distance + ' m' : '';
        return '<li><div class="store-name">' + s.name + '</div>' +
          '<div class="store-meta">' + (s.address || '') + (dist ? ' · ' + dist : '') + '</div>' +
          '<div class="store-meta">营业 ' + (s.start || '') + '–' + (s.end || '') +
          (s.code ? '　编号 ' + s.code : '') + '</div></li>';
      }).join('');
      sl.hidden = false;
    }

    if (preset.plan) {
      state.plan = planFromPreset(preset.plan);
      renderEnergy(state.plan);
      renderMeals(state.plan);
      renderSummary();
      window.MCDFit = { state: state, plan: state.plan, calcEnergy: calcEnergy, planDay: planDay };
      return true;
    }
    return false;
  }

  /* 把 plan.py 输出的 JSON 还原成渲染层需要的数据结构 */
  function planFromPreset(pl) {
    var e = pl.energy || {};
    var prof = pl.profile || {};
    return {
      energy: {
        bmr: e.bmr, palKcal: e.activity, exDaily: e.exercise_daily,
        exPerSession: e.exercise_session, tdee: e.tdee, targetKcal: e.target_kcal,
        deficit: e.deficit, direction: e.direction, limited: e.limited, bmi: e.bmi,
        protein: e.protein, fat: e.fat, carb: e.carb,
        proteinPct: e.protein_pct, fatPct: e.fat_pct, carbPct: e.carb_pct
      },
      profile: {
        sex: prof.sex, age: prof.age, height: prof.height, weight: prof.weight,
        target: prof.target, weeks: prof.weeks, pal: prof.pal, met: prof.met,
        exDays: prof.days, exMin: prof.minutes, prefs: new Set(prof.prefs || [])
      },
      meals: (pl.meals || []).map(function (m, i) {
        return {
          meal: MEALS[i], target: { kcal: m.target_kcal },
          items: m.items, sum: m.totals, sig: ''
        };
      }),
      total: pl.total
    };
  }

  /* ---------- 初始化 ---------- */
  function init() {
    if (DATA.length) $('skuCount').textContent = String(DATA.length);

    Array.prototype.forEach.call(document.querySelectorAll('#sexPills .pill'), function (b) {
      b.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('#sexPills .pill'), function (x) {
          x.classList.remove('is-on');
        });
        b.classList.add('is-on');
        state.sex = b.getAttribute('data-sex');
        build();
      });
    });

    Array.prototype.forEach.call(document.querySelectorAll('#prefChips .chip'), function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-pref');
        if (state.prefs.has(k)) { state.prefs.delete(k); b.classList.remove('is-on'); }
        else { state.prefs.add(k); b.classList.add('is-on'); }
        build();
      });
    });

    ['age', 'height', 'weight', 'target', 'weeks', 'pal', 'exType', 'exDays', 'exMin']
      .forEach(function (id) {
        $(id).addEventListener('change', function () { updatePreview(); build(); });
        $(id).addEventListener('input', function () {
          clearTimeout($(id)._t);
          updatePreview();
          $(id)._t = setTimeout(build, 260);
        });
      });

    $('genBtn').addEventListener('click', function () {
      state.seed = Math.floor(Math.random() * 100000);
      build();
      closeProfile();
      setTimeout(function () {
        document.getElementById('meals').scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 60);
    });

    // 弹框开合
    if ($('editProfile')) $('editProfile').addEventListener('click', openProfile);
    if ($('modalClose')) $('modalClose').addEventListener('click', closeProfile);
    Array.prototype.forEach.call(document.querySelectorAll('[data-close]'), function (el) {
      el.addEventListener('click', closeProfile);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && $('profileModal') && !$('profileModal').hidden) closeProfile();
    });

    $('shuffleAll').addEventListener('click', function () {
      state.seed = Math.floor(Math.random() * 100000);
      build();
    });

    $('resetBtn').addEventListener('click', function () {
      $('age').value = 28; $('height').value = 172; $('weight').value = 78;
      $('target').value = 70; $('weeks').value = 12; $('pal').value = '1.3';
      $('exType').value = '7'; $('exDays').value = 3; $('exMin').value = 40;
      state.sex = 'male'; state.prefs.clear();
      Array.prototype.forEach.call(document.querySelectorAll('#sexPills .pill'), function (x, i) {
        x.classList.toggle('is-on', i === 0);
      });
      Array.prototype.forEach.call(document.querySelectorAll('#prefChips .chip'), function (x) {
        x.classList.remove('is-on');
      });
      updatePreview();
      build();
    });

    var preset = window.MCD_PRESET;
    if (preset) {
      var presetIsFull = applyPreset(preset);
      if (presetIsFull) return;   // 预置了完整方案就直接渲染，不再重算
    }

    build();

    // 首次进入弹一次档案面板；导出页（已有预置方案）不再打扰
    if (!preset) setTimeout(openProfile, 420);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
