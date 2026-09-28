# 前端：架构、设计语言、录入页

> 速查：`clms.html` 加载 `assets/app/main.js`（ES 模块，无构建）。`shell.js` 建 bus / store / router 并挂载页面；页面在 `features/<x>/`，渲染用 `html```+`morph`，事件用 data-action 委托。纪律由 `tests/check_ui.py` 强制（规则见 `AGENTS.md`）。

## 分层

```
core/     markdown.js（模型回复的轻量 Markdown，先转义再排版）  sse.js（subscribe：EventSource 封装）  stream.js（postStream：带请求体的 SSE，fetch + ReadableStream，复习助手用）
          files.js（readImages：本地图片 → dataURL）  html.js（转义模板、each、cls） dom.js（render / morph，唯一写 innerHTML 处）
          events.js（data-action / data-change / data-input / data-submit 委托） router.js（#/页面）
          store.js  bus.js  api.js（request/get/post，永不抛出，返回 {ok,status,data,error}）  format.js
ui/       icons.js（内联线性图标）  feedback.js（toast 顶部居中、confirmDialog）
domain/   genres.js（板块、评分档、题型表缓存）  paper.js + paper.css（原文、答题横线、默写下划线、红笔 / 蓝笔）
features/ dashboard  entry  library  review  settings
styles/   tokens.css（唯一允许颜色字面量）  base / ui / shell.css  index.css（@layer 顺序与 @import）
```

依赖方向：core → core；ui → ui、core；domain → domain、ui、core；features/x → x、domain、ui、core。页面之间不 import。

`morph()` 按 `data-key` 对齐列表、保留聚焦输入框的值与选区，所以页面可以放心「状态一变就整页重画」。

### bus 事件

| 事件 | 载荷 | 发出方 → 监听方 |
| --- | --- | --- |
| `page:change` | `{id, prev}` | shell |
| `badge` | `{id, text}` | 录入页（待校对草稿数）、main.js（到期题数）→ shell 导航角标 |
| `library:changed` | — | 录入页入库、复习页评分 → 需要刷新的页面 |

## 设计语言：「答题卡」

- 纸面 `--paper`、原文和题干用衬线 `--font-read`（首行缩进 `--indent`、行距 1.9）。
- 字体不随项目附带（中文字体体积太大），`tokens.css` 按平台挑系统里最好的：界面 `--font-sans` 西文 / 数字用 Segoe UI（Windows）/ SF（Mac），汉字用苹方、鸿蒙黑体、微软雅黑 UI、思源黑体；代码 `--font-mono` 优先 JetBrains Mono / Cascadia / SF Mono / Consolas，不会落到 Courier。装了 Inter 或 JetBrains Mono 的机器会自动用上。
- **红笔 `--mark` 只用于参考答案**（老师的批改红），错误提示用 `--danger`；学生作答用蓝笔 `--pen`。
- 答题横线 `--rule`（稿纸绿），行距 `--rule-gap` ≈ 答题卡 9mm；默写空是下划线。
- AI 刚改过的字段带 `data-flash`，`--flash` 底色淡出（`--dur-flash`）。
- 四个板块各有识别色 `--genre-*`，只用于小圆点和细边。
- 浅色是纸白 + 墨蓝 `--accent`；深色沿用 OMRS 的暖石墨。主题存在 `localStorage['clms-theme']`。
- 断点：≤ 1500 录入记录变抽屉；≤ 1160 录入页改为单栏，用「对话 / 草稿」分段按钮切换；≤ 760 侧栏变顶栏、控件加高到 40px 便于触屏。
- 主导航可收成只有图标的窄栏（`--rail-width`，`html[data-nav="mini"]`，存在 `localStorage['clms-nav']`）。
- 滚动条全局细条、跟随主题（`--scroll-thumb`）。
- 动效只用 `--dur-*` / `--ease-*`（系统「减少动态效果」时全部为 0）：新块入场、展开箭头旋转、展开内容淡入、进行中文字流光（`.shimmer`）；大界面切换用 View Transition（`base.css` 里 `::view-transition-*`）。

## 录入页（`features/entry/`）

流程：**居中输入框**（新录入；上传后在这里确认页序 / 方向 / 每页说明，写的话就是补充说明）→ 开始 → **Agent 实时执行**（对话里的时间线）→ 纸面校对 → 入库 →「录下一份」回到居中输入框；左侧是**录入记录**（宽屏可收起）。

| 文件 | 职责 |
| --- | --- |
| `index.js` | 控制器：状态、录入记录刷新、SSE 订阅与事件应用、View Transition（`transition()`）、打开 / 回到开始（`open()` / `fresh()`）、自动保存、编辑 / 发送 / 停止 / 入库等动作、每秒计时 |
| `listeners.js` | 文档级监听：粘贴截图、拖放（外部文件 / 页面排序）、Enter 发送 |
| `manage.js` | 「管理」动作：录入记录（分组、搜索、加载更多、重命名、回收站、恢复、彻底删除）、准备阶段（页序、旋转、删页、加页、说明、补充说明、开始）、时间线块展开 |
| `layout.js` | 整体布局：录入记录 \| 主区（开始界面，或对话 + 草稿或原图 + 底栏；入库后底栏有「录下一份」） |
| `launch.js` + `launch.css` | 开始界面：标题、居中大输入框（`#composer`）、页面条（缩略图悬浮出现 ← / 旋转 / 删除 / → 按钮，可拖动，每页一句说明）、「合成一份 / 每页一份」、快捷问题；没草稿时发送 = 建一段对话并发第一句 |
| `history.js` + `history.css` | 录入记录：按日期分段，缩略图、标题、状态点、时间、页数 / 题数、最近一句话；行内重命名、丢弃 / 恢复 / 彻底删除；宽 > 1500 可收起（`data-collapsed`，内容定宽、收起时 `inert`，状态存在 `localStorage['clms-hist']`），否则是抽屉 |
| `chat.js` | 对话栏：状态条（标题、状态、执行计时、停止、记录开关）、时间线、等待模型时的尾行（流光字）、输入框（快捷指令、附原图、附图、插话、用量圆环）；旧流程的 activity 步骤卡 |
| `gauge.js` | 用量圆环：上下文占用（`stats.context / stats.window`，≥ 70% 黄、≥ 90% 红）；悬浮或聚焦弹出速度（执行中是前端按逐字事件算的实时值）、首字延迟、主 / 子代理轮数、工具次数、累计 token，估算时注明 |
| `timeline.js` + `timeline.css` | 时间线：思考块（进行中展开、逐字；结束收成一行预览）、正文（Markdown，逐字 + 光标）、工具调用行（点开看参数与结果；生成参数时实时显示）、delegate 的子代理卡片（点开是子代理自己的时间线）、执行收尾、手改记录与入库提示；打开后新到的块带 `is-enter` 入场 |
| `canvas.js` / `canvas-items.js` / `edit.js` | 草稿画布与纯数据编辑；原图视图按准备阶段的页序与旋转显示。材料的标题 / 作者 / 出处是会自动换行的单行文本框（`data-oneline`：回车不换行、粘贴的换行变空格），标题独占一行，作者和出处另起一行；支持 `field-sizing` 的浏览器按内容定宽 |

状态要点（`index.js` 的 `s`）：

- `drafts / counts / total / view / q / limit` 录入记录；`activeId / draft / working / dirty / saving`；`open`（块 id → 是否展开）；`known`（打开时已有的块 id，不播入场动效；从开始界面过来时为空）；`liveSeq`；`liveTps`；`histOpen`（抽屉）/ `histCollapsed`（宽屏收起）；`heroText`（开始界面输入框）；`split`；`starting`；`renaming`；`dragPage`。
- 过渡：开始界面 ↔ 对话用 `document.startViewTransition`，两边的输入框框体同名 `view-transition-name: composer`，所以输入框从中间平滑落到底部（反之亦然），其余交叉淡入；不支持或「减少动态效果」时直接切换。
- 实时：打开草稿即 `subscribe('/api/draft/events?id=&since=live_seq')`（`core/sse.js`）。`delta` 追加到对应块的字段（同时计入实时速度），`block` 整块替换 / 追加，`stats` 更新圆环，都用 requestAnimationFrame 合批重画；`status` / `reload` 250ms 后重新拉草稿和录入记录。`seq ≤ liveSeq` 的事件忽略。
- 滚动跟随：重画前若时间线停在底部（80px 内），重画后滚到底；用户往上翻时不动。
- 补充说明在输入框失焦时保存；「开始」先等这次保存落地再发，避免两者赛跑。
- 请求顺序：`open()` 用 `openSeq`，最后一次打开为准；后台 `loadActive()` 用 `loadSeq`，回来时若 `activeId` 变了、有更晚的刷新、或期间开始过一次打开，就丢弃。`transition()` 先同步改状态，只把重画交给 View Transition，所以过渡期间到达的旧回复同样会被丢弃。
- 录入记录每 4 秒（有执行中的）或 15 秒刷新；执行中每秒重画一次计时和速度。
- 窄屏（≤ 1160）打开草稿默认在「对话」分段。
- 手改、入库、`flash` 等其余行为同前；发送后手动清空 textarea（morph 会保留聚焦输入框的值）。
- 命名注意：`.hero` 是概览页的、`.meter` 是全局进度条，录入页分别用 `.launch`、`.gauge`。

## 其它页面

- **概览 `dashboard/`**（`dash.*`）：今天是否复习日、下一批的日期与题数、两周日历（复习日画圈）、四个板块卡片、题型薄弱榜、未完成的复习与最近动态。「排这次复习」经 `store.reviewIntent` 带意图跳到复习页（`{plan}` / `{session}`；题库还会带 `{pinned}`）。
- **题库 `library/`**（`lib.*`）：两个分页。
  - 「题目」：左侧分面筛选（`view.js facets`：状态含顽固 / 已停用 / 已删除、记忆类型、添加时间、最近练习、上次评分、题型；每项显示按其它筛选算出的题数，再点一次取消；≤ 1500 收进工具条的「筛选」按钮）；工具条（板块分段、搜索、按题 / 按篇、排序、批量选择）；列表每页 50 题 / 20 篇，「加载更多」。按题的行显示板块 · 题号 · 题型 · 篇名 · 出处（会换行，不截断）、两行题干、上次评分 / 录入时间 / 出错次数，右侧状态、掌握度条、到期（理解型掌握后不再安排时显示「不再安排」）。按篇时每篇（默写按出处）一张卡片：篇名、作者、题数、已掌握 / 新 / 顽固、平均掌握度，下面是其中的题。批量模式：点行勾选、「选这一篇」「全选已加载的」，底部批量条「加入复习 / 停用 / 恢复复习 / 删除」（`/api/items/batch`）。
  - 「复习记录」（`history.js`）：全库复习历史，按板块 / 评分 / 时间 / 只看写了反馈的 / 显示已撤销的筛选，分页；点一条在右侧打开这道题。
  - 右侧详情（`detail.js`）：状态卡（状态、记忆类型、掌握度、下次、上次评分、出错）、纸面题目与红笔答案（篇名 / 作者 / 出处换行显示）、同一篇的其它题（点击切换）、复习记录（补记、改评、反馈、撤销、恢复）、「加入复习」「编辑」「停用」「删除」；已删除的题可「恢复到题库」。
  - 「加入复习」（单题或批量）经 `store.reviewIntent = {pinned: [题号]}` 跳到复习页，成为自选题。筛选、分页方式、列表方式存在模块级 `saved`，切页面回来不丢。
- **复习 `review/`**（`rv.*`）：
  - 安排（`planner.js` 渲染、`plan.js` 数据与动作）：进页面自动推荐；时间预算、板块芯片、题型下拉、提前复习开关，任一变化即重新推荐（`seq` 丢弃过期回复）。推荐清单按材料分组，每题一个理由芯片（配色按 `tag`），可移除单题（放进 `exclude`，别的题自动补位）、「全部放回」「换一批」（把当前推荐都移掉）；自选题带「自选」芯片，移除即取消自选。下面是「从题库挑题」（`/api/items` 分页，按板块 / 状态 / 添加时间 / 最近练习 / 上次评分 / 关键词 / 排序），「加入」即自选。
  - 复习列表（打印、打印含答案、评分、删除）。
  - 评分视图（`view.js`）：左边纸面（按材料分组，篇名 / 作者 / 出处换行显示、原文可折叠，逐题「对答案」后给出评分按钮，可撤销、写反馈），右边复习助手（`assistant.js`）；≤ 1160 助手变成右下角浮动面板，由头部「复习助手」或题目上的「问 AI」打开。点题目任意空白处即把助手切到这道题（`rv.focus`，题目左侧出现墨蓝页边线）；默认是第一道没评分的题。
  - 复习助手：对话存在模块级 Map（按「复习 + 题」），切页面不丢、刷新清空；「打分」「写反馈」「怎么答」「差在哪」快捷按钮，输入框回车发送、可附 / 粘贴作答照片，流式显示（思考时显示流光「正在思考…」，「【建议】」之后的内容流式期间隐藏），可停止、出错可重试。建议卡片：「采用评分和反馈」（`/api/session/grade`，带反馈）、「只填反馈」（已评分 → `/api/record/update`；未评分 → 暂存在 `s.pendingNotes`，题下显示「反馈（评分时一起写入）」，评分时随评分写入）。
  - 旧的「拍照交给 AI 批改」入口 0.5 起移除（后端 review 会话保留，见 `ai.md`）。
- **设置 `settings/`**（`set.*`）：AI 模型、超时、输出 token 上限、并发数、Agent 模式开关、子代理并发、每次最多轮数、复习日（七个按钮）与默认时长、校验提交链、导出脱敏源代码（链接下载 `/api/source/export`）。
