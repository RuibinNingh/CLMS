# 前端：架构、设计语言、录入页

> 速查：`clms.html` 加载 `assets/app/main.js`（ES 模块，无构建）。`shell.js` 建 bus / store / router 并挂载页面；页面在 `features/<x>/`，渲染用 `html```+`morph`，事件用 data-action 委托。纪律由 `tests/check_ui.py` 强制（规则见 `AGENTS.md`）。

## 分层

```
core/     files.js（readImages：本地图片 → dataURL）  html.js（转义模板、each、cls） dom.js（render / morph，唯一写 innerHTML 处）
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

- 纸面 `--paper`、原文和题干用衬线 `--font-read`（首行缩进 `--indent`、行距 1.9）；界面文字用 Noto Sans SC（本地字体，在 `assets/vendor/fonts`）。
- **红笔 `--mark` 只用于参考答案**（老师的批改红），错误提示用 `--danger`；学生作答用蓝笔 `--pen`。
- 答题横线 `--rule`（稿纸绿），行距 `--rule-gap` ≈ 答题卡 9mm；默写空是下划线。
- AI 刚改过的字段带 `data-flash`，`--flash` 底色淡出（`--dur-flash`）。
- 四个板块各有识别色 `--genre-*`，只用于小圆点和细边。
- 浅色是纸白 + 墨蓝 `--accent`；深色沿用 OMRS 的暖石墨。主题存在 `localStorage['clms-theme']`。
- 断点：≤ 1160 录入页改为单栏，用「对话 / 草稿」分段按钮切换；≤ 760 侧栏变顶栏、控件加高到 40px 便于触屏。

## 录入页（`features/entry/`）

| 文件 | 职责 |
| --- | --- |
| `index.js` | 控制器：状态、轮询、自动保存、全部 `entry.*` 动作、粘贴 / 拖放 / Enter 发送监听 |
| `layout.js` | 整体布局：队列 + 工作区（对话 \| 草稿或原图）+ 底栏（待补问题、去重结果、入库） |
| `queue.js` | 顶部草稿队列（缩略图 + 标题 + 状态点）、上传 / 手动录入、多图时的「每张一份 / 合成一份」+ 补充说明、空状态 |
| `chat.js` | 对话：用户消息与原图缩略图（插话排队 / 没送达标记）、AI 回复、手改记录（撤销）、处理中指示、输入框（快捷指令、附原图、附图、停止、插话） |
| `run.js` + `run.css` | Agent 执行记录：每次工具调用一行（进行中 / 完成 / 出错 / 已停止）、模型中途说的话、`delegate` 的子代理卡片（板块、页码、状态、工具次数、正在做什么）、最终回复与改动芯片；进行中默认展开，用户点过按用户的（`s.runLog`） |
| `canvas.js` | 草稿画布：板块头（板块选择、题数、「这篇已在题库」）、材料（标题 / 作者 / 出处、原文折叠与编辑）、添加小题、添加板块；原图视图 |
| `canvas-items.js` | 阅读小题卡（题号、题型下拉、分值、题干、留白横线 −/+、红笔答案 + 来源标、我的作答 / 解析 / 错因）与默写卡（红笔预览、模板、插入空、逐空答案 + 去重标记、出处、类型） |
| `edit.js` | 工作副本上的纯函数：`setField`（路径 `gid\|iid\|field`，默写答案为 `blank:n`）、`stepLines`、`addItem`、`addGroup`、`removeEntry`、`insertBlank`、`blankNumbers`、`countUnits` |

状态要点（`index.js` 的 `s`）：

- `drafts` 队列、`activeId` / `draft`（服务端视图）、`working`（本地工作副本）、`dirty` / `saving`。
- 轮询：有草稿在排队 / 识别 / 修改时每 1.2 秒刷新队列和当前草稿，否则每 8 秒。
- 手改：先改 `working`，停手 0.7 秒整份 POST `/api/draft/edit`（带 revision）；保存途中又改了就保留本地副本、稍后再存。结构性变化（选择框、默写模板 / 答案、增删）立即重画，普通文字输入不重画。
- AI 新消息到达：把 `changes` 放进 `flash`（2.2 秒后清掉），并把画布滚到第一处改动；「回到修改前」和手改「撤销」都是 `/api/draft/restore`。
- 原图视图：识别中或还没有草稿时默认显示原图；点对话里的缩略图也切到原图。
- 识别中 / 修改中根据草稿 `activity` 显示真实执行步骤、当前步骤动效和总用时；排队、原图处理、模型请求、解析、保存由后台逐项写入，轮询刷新。模型接口一次性返回结果，因此“思考中”只是模型请求状态，不显示内部推理文本；完成后保留本次执行记录。动效尊重系统的减少动态效果设置。
- 发送、入库、切换草稿前先 `flush()` 未保存的手改。
- Agent 模式：执行中输入框仍可用（「插话」，下一轮读到），旁边有「停止」；已入库的草稿也能继续聊；「附图」或在输入框里粘贴截图作为本条消息的图片；队列栏「新对话」开一段空白对话（`{chat: true}`）；复习页经 `store.entryIntent = {open: id}` 打开批改会话。发送后手动清空 textarea（morph 会保留聚焦输入框的值）。

## 其它页面

- **概览 `dashboard/`**（`dash.*`）：今天是否复习日、下一批的日期与题数、两周日历（复习日画圈）、四个板块卡片、题型薄弱榜、未完成的复习与最近动态。「排这次复习」经 `store.reviewIntent` 带意图跳到复习页。
- **题库 `library/`**（`lib.*`）：板块分段 + 状态（含「已删除」）/ 排序 / 搜索；列表行显示板块、题型、出处、状态、掌握度条、到期；右侧详情显示状态卡、纸面题目与红笔答案、复习记录，可编辑、停用、删除；已删除的题可「恢复到题库」。复习记录可增删改查：「补记一次」（评分 + 日期 + 反馈）、下拉改评分、「反馈」改反馈、「撤销」、显示已撤销后「恢复」。
- **复习 `review/`**（`rv.*`）：时间预算分段、板块芯片、提前复习开关 → 预览清单（每题理由）→ 确认生成；复习列表（打印、打印含答案、评分、删除）；评分视图按材料分组，原文可折叠，逐题「对答案」后给出评分按钮，可撤销、写反馈（回车保存，经 `/api/record/update`）；「拍照交给 AI 批改」上传作答照片建 review 会话并跳到录入页看执行。
- **设置 `settings/`**（`set.*`）：AI 模型、超时、输出 token 上限、并发数、Agent 模式开关、子代理并发、每次最多轮数、复习日（七个按钮）与默认时长、校验提交链、导出脱敏源代码（链接下载 `/api/source/export`）。
