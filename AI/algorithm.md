# 算法：记忆状态、复习日、按时间预算排复习

> 速查：`scheduling.derive()` 重放一道题的事件得出 `sched`；题分「记忆型 / 理解型」两条曲线（`taxonomy.memory_kind`）；到期日对齐到复习日；`plan_session()` 按分钟预算推荐，自选题先占预算，同一篇材料只算一次阅读时间，薄弱题型优先。参数全在 `DEFAULT_TUNING`，可在 `config.json` 的 `tuning` 里逐项覆盖。

## 两种记忆类型（v0.5）

| 类型 | 哪些题 | 规则 | 为什么 |
| --- | --- | --- | --- |
| 记忆型 `recall` | 名句默写；文言文的实词解释题、虚词题、文化常识题（`taxonomy.RECALL_QTYPES`） | 下面的间隔重复原样：连续 `kill_streak`（2）次「完整」才算掌握，掌握后按衰减反解周期复燃 | 靠背，会遗忘，要反复考 |
| 理解型 `skill` | 其余所有题：阅读主观题、鉴赏、翻译、概括、选择…… | 一次「完整」（`skill_kill_streak` = 1）或连续两次「基本」及以上（`skill_basic_streak` = 2）即掌握；「基本」后至少隔 `skill_partial_interval`（7）天，一次「基本」掌握度至少 0.6（巩固中）；衰减用 `skill_decay_factor`（90，记忆型 30）；掌握后隔 `skill_revive_days`（120）天 × `revive_multiplier^(kills−1)` 才抽查（至少 14 天），设为 0 则不再安排（到期日写 `9999-12-31` = `scheduling.NEVER`） | 做对一次就很少再错；重做同一道阅读题测的多半是「记不记得答案」，反复排它价值很低。理解型的薄弱点落在「题型」上，排复习时补同题型的其它题（见「薄弱题型」） |

记忆状态现算不落表，所以改了分类规则或 tuning，已有的题立刻按新规则显示（例如已经「完整」过一次的阅读题直接变成已掌握）。

## 评分档

| 值 | 阅读题 | 默写 |
| --- | --- | --- |
| 0 | 不会（没思路 / 答偏） | 不会 |
| 1 | 部分（只答到少量要点） | 有错字 |
| 2 | 基本（主要要点都有） | — |
| 3 | 完整（要点齐全、表述到位） | 全对 |

「又录入一次」（reencounter）按一次 0 分处理。

## derive(created_at, events, weekdays, today, tuning, kind)

按时间顺序重放 `review` 与 `reencounter` 事件，状态变量：掌握度 m ∈ [0,1]、易错因子 ef ∈ [1.3, 3.0]（初值 2.5）、连续成功次数 reps、间隔 interval。`kind` 缺省为 `recall`；投影按 `memory_kind(genre, qtype)` 传入。下面先写记忆型，理解型的差异见上一节。

- **grade 3**：连续高分 +1；连续 `kill_streak`（2）次且 reps ≥ 1 时 m = 1（已掌握），否则 m += 0.35·ef/2.5（上限 0.95）。理解型一次即 m = 1。
- **grade 2**：m += 0.2·ef/2.5（上限 0.9），连续高分清零。理解型：连续「基本及以上」达到 `skill_basic_streak` 时 m = 1，否则 m 至少 0.6。
- **grade 0 / 1**：m 乘 0.3 / 0.6，连续错误 +1。
- **ef**：复习满 `ef_cold`（2）次后才调整；3 分 +0.15，≤1 分 −0.2。
- **间隔**：成功（≥2）时 reps+1，第一次 `interval_1`（4 天）、第二次 `interval_2`（9 天）、之后 interval·ef；2 分再乘 `partial_factor`（0.7）。失败时 reps 清零，间隔 = `first_interval`（2 天），1 分多 1 天。
- **已掌握**：间隔改为复燃周期 `revive_days(kills)`——按衰减到 `revive_threshold` 反解的天数，乘 `revive_multiplier^(kills−1)`，至少 7 天。理解型用 `skill_revive_days(kills)`。
- **到期日** = align(最后一次事件日 + interval)：顺延到下一个复习日（`config.review_weekdays`，0 = 周一）。新录入的题到期日 = align(录入日 + first_interval)。

读出的时候再算：

- 衰减掌握度 `decayed = m · exp(−天数 / (m·decay_factor + decay_base))`；理解型用 `skill_decay_factor`。
- 逾期天数 = max(0, 今天 − 到期日)。因为到期日已经对齐，不会出现「周三到期、周五才复习」的假逾期。
- 顽固题（leech）：连续错误 ≥ `leech_threshold`（3）且未掌握。
- 优先级 = (1 − decayed) · 难度/10 + 逾期/14 · 0.3，顽固题 +0.4；没复习过的 + `new_bonus`（0.15）+ min(1, 录入天数 / `new_age_days`（14）) · `new_age_weight`（0.25）——新题放得越久越往前排。难度由 ef 线性映射到 1–10。
- 另外输出 `kind`、`age_days`（录入至今天数）、`last_grade`（最近一次评分，没评过为 null），供推荐理由、题库筛选使用。
- 状态：已掌握（m = 1）/ 新录入（没复习过）/ 待攻克（m < 0.4）/ 巩固中。

## 复习日

默认 `[1, 4, 6]`（周二、周五、周日，间隔 3/2/2 天）。`next_review_day(today)` = align(today)：今天就是复习日时返回今天。概览页的「到期」指到期日 ≤ 下一个复习日。

## 排复习：plan_session(items, budget, today, horizon, genres, fill, qtypes, pinned, exclude, busy, tuning)

`sessions.plan()` 调用它：`busy` = 还在未完成复习里、没评分的题（`sessions.open_item_ids`），`pinned` / `exclude` 由复习页传来。

1. **自选题**（`pinned`，题库「加入复习」或复习页「从题库挑题」）：先放进来、先占预算，不受板块 / 题型 / 预算限制，理由「自选」。
2. 候选池：未停用、在所选板块内、在所选题型内（`qtypes`，只影响推荐）、不在 `exclude`（用户移掉的）、不在 `busy`（`busy_skipped` 统计到期却因此跳过的数目）。
3. **薄弱题型**：理解型里复习过的题按（板块，题型）求平均衰减掌握度，至少 `weak_qtype_min`（2）道且平均 < `weak_qtype_threshold`（0.5）的算薄弱；这些题型里未掌握的题排序时 + `weak_qtype_bonus`（0.15）。
4. 到期题 = 到期日 ≤ horizon（下一个复习日），未掌握的在前，按（优先级 + 薄弱加分）降序；已掌握的复燃 / 抽查题按到期日排在后面。
5. 逐题放入，直到超出预算（没有自选时至少放一题）。估时：`item_minutes(genre, qtype)`，另外每篇材料第一次出现时加一次阅读时间。放入一道阅读题时，同一篇里其它到期的小题只要放得下就一起放入，原文只读一遍。
6. `fill` 为真、且用时不到预算的 80% 时，从未到期、未掌握的题里补足：跳过 `recent_days`（2）天内刚做过的；薄弱题型的在前，再按衰减掌握度升序。
7. 输出按试卷顺序排：现代文 → 文言文 → 古诗 → 默写，同一材料内按录入顺序。

每题附 `tag` 与 `reason`（`scheduling.explain`）：

| tag | reason 例 | 含义 |
| --- | --- | --- |
| `manual` | 自选 | 用户挑的 |
| `leech` | 顽固 · 连错 3 次 | 连错 ≥ `leech_threshold` 且未掌握 |
| `new` | 新录入 · 5 天未练 | 没复习过（≥ 3 天才写天数） |
| `revive` | 掌握后抽查 | 已掌握、到了复燃 / 抽查日 |
| `overdue` | 逾期 3 天 · 上次「部分」 | 对齐后的到期日已过；上次不是满分时附上次评分 |
| `due` | 到期 · 上次「基本」 | 到期日 ≤ 下一个复习日 |
| `weak` | 薄弱题型 · 意象作用题 | 提前补的薄弱题型 |
| `early` | 提前复习 | 其余提前补的 |

返回 `{items:[{id, tag, reason, minutes}], minutes, budget, due_total, due_left, busy_skipped, pinned, weak:[{genre, qtype}]}`。

### 估时表（分钟，`taxonomy.py`）

| 板块 | 每题 | 每篇材料阅读 |
| --- | --- | --- |
| 现代文 | 5 | 5 |
| 文言文 | 2.5 | 3 |
| 古诗 | 4 | 1.5 |
| 默写 | 0.5 | 0 |

按题型覆盖：选择题 1.5、翻译题 3、断句题 1.5、实词 / 虚词 / 文化常识 1、词语理解 2。

## 概览统计（`sessions.summary`）

板块：题数、到期数、已掌握数、顽固数、平均衰减掌握度。「下一批」只看有到期日的题（不再安排的理解型掌握题不算）。题型薄弱榜：非默写题按（板块，题型）聚合平均衰减掌握度升序，附累计出错次数（重复录入 + ≤1 分的评分）。另有本周复习次数、未完成的复习。
