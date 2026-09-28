# AI 录入：识图、对话修订、草稿结构

> 速查：默认是 **Agent 模式**（`config.ai_agent`，见下方「Agent harness」）：录入对话直连一个工具调用的 Agent，模型通过工具逐题读写草稿、查改题库、增删改查复习记录、记复习反馈；大试卷由主代理委派子代理按大题并行录入。关掉 Agent 模式时是下面的旧流程：两种调用都走 OpenAI 兼容的 `/chat/completions`，只发一条 user 消息（图片 + 文字，不用 system）。识图返回 `{groups, notes}`；修订每轮都把完整草稿发过去、要求返回完整草稿，服务端自己算 diff。模型输出一律经过 `draft_schema.normalize_groups()`。

## 调用（`clms/ai_assist.py`）

- 配置：`ai_base_url`（自动补 `/chat/completions`）、`ai_api_key`、`ai_model`、`ai_timeout`（默认 150 秒）、`ai_max_tokens`（默认 16000，可在设置页调整）。`temperature` 固定 0.1。模型回复 `finish_reason=length` 时报告输出上限和思考 token 用量（若接口提供），不把截断的 JSON 当成有效草稿。
- 图片：有 Pillow 时转成 JPEG、宽度缩到 1600；高 / 宽 > 3.2 的长截图切成若干段（段高约 2.2 倍宽，重叠 15%），按顺序作为多张图发送。没有 Pillow 就原图直发。
- 回复解析：去掉 Markdown 围栏，取第一个 `{` 到最后一个 `}` 之间的 JSON。解析失败、HTTP 错误、超时都会变成草稿上的 `error`，对话里显示原因和「重试」。原始模型文本不显示在错误消息中。
- 后台任务在草稿暂存文件的 `activity` 中记录实际经过的阶段与时间：排队 → 处理原图 / 整理修改要求 → 调用模型 → 解析回复 / 比对改动 → 保存草稿。阶段失败或服务重启时标记中断；这些记录不进入 Ledger。旧流程不展示思考；Agent 模式展示（见「对话时间线与实时流」）。

## 识图（EXTRACT_PROMPT）

要求模型把图片整理成：

```json
{"groups": [{"genre": "现代文阅读", "material": {"title": "", "author": "", "source": "", "text": ""},
             "items": [{"no": "7", "qtype": "意象作用题", "stem": "", "answer": "", "answer_origin": "image",
                        "analysis": "", "score": 6, "blank_lines": 7, "user_answer": ""}],
             "dictation": []}],
 "notes": "看不清或拿不准的地方"}
```

要点：

- 板块只有四个：现代文阅读、文言文阅读、古代诗歌阅读、名句默写。每篇独立的阅读材料单独成一个 group；名句默写整体一个 group。
- 原文逐字转录，段落换行，保留①②③序号；古诗按原排版换行；注释放在末尾、以「注：」开头。
- 题型从当前题型表里选（`taxonomy.qtypes()`，可在 `config.json` 的 `qtypes` 覆盖），实在没有才自拟。
- 选择题把选项放进题干，每项一行。
- 图里有答案就照录（`answer_origin: image`）；没有就按阅卷习惯分条补写（`ai`）。
- 留白 `blank_lines` 由模型判断，参考：选择 0、解释 / 断句 1–2、翻译每句 2–3、概括赏析 3–6、探究 6–10。模型没给时按分值兜底（`default_blank_lines`：分值 × 1.2，限 2–12；选择题 0；未知 4）。
- 默写：`template` 用 `{书写区域1}`、`{书写区域2}`… 标空，`blanks` 是编号到答案的表，`source`、`kind`（直接默写 / 理解性默写）。

用户上传时写的补充说明（`hint`）会作为「用户补充说明」一节拼进提示词。

## 对话修订（REVISE_PROMPT）

每轮发送：题型表、当前完整草稿 JSON（含 gid / iid）、最近 8 条对话（手改会被概括成「我手动改了：…」）、用户这次的话；用户勾了「附原图」时带上原图。要求：

- 只改用户要求改的地方，其余逐字保留；gid / iid 原样保留，新增的题不写 iid。
- 改答案按采分点分条，分值已知时条数与分值匹配，并把 `answer_origin` 设为 `ai`。
- 只是提问时草稿原样返回，在 `reply` 里回答。
- 输出 `{"reply": "…", "draft": {"groups": [ … ]}}`。

服务端用 `diff(旧, 新)` 算出改动：有改动才新增 revision，并在 AI 消息上记 `changes` 与 `base_revision`（「回到修改前」就是恢复到这一版）。

## 草稿结构（`clms/draft_schema.py`）

```
group = {gid, genre(modern|classical|poetry|dictation), material:{title,author,source,text}, items:[…], dictation:[…]}
item  = {iid, no, qtype, stem, answer, answer_origin(image|ai|user|""), analysis, score, blank_lines(0–24), user_answer, note}
dictation entry = {iid, template, blanks:{"1": "…"}, source, kind}
```

- `normalize_groups()`：板块名 / 别名归一到代码（`taxonomy.normalize_genre`）；补齐字段；文本统一换行、去行尾空白；gid / iid 缺失或重复时重新分配（g1、i1、d1…）；全角括号的占位符改成半角；默写 group 清空 material。
- `issues()`：入库前的阻断问题——没有题目、阅读材料缺原文、题干为空、没有答案、默写模板里没有占位符、某个空没有答案。答案表里多出的编号（模板里已删掉的空）不算问题，拆分时自然忽略。
- `diff()`：逐字段比较，`answer_origin` 不参与；输出带人话标签（「第 7 题 · 答案」「《老街的灯》 · 原文」「默写 李白《静夜思》 · 答案表」）。

## 默写拆分（`clms/dictation.py`）

`split_entry(entry)`：模板里每个出现过的 `{书写区域n}`（且答案非空）变成一道小题。它的题面把自己的空换成 `{书写区域}`，同一模板里其它空直接填入答案作为上下文。例：

```
template  杜甫《春望》中……两句是：“{书写区域1}，{书写区域2}。”
→ 题 1   ……两句是：“{书写区域}，恨别鸟惊心。”   答案 感时花溅泪
→ 题 2   ……两句是：“感时花溅泪，{书写区域}。”   答案 恨别鸟惊心
```

两个空同时出现在一次复习里时，打印卷合成一行、每个空标题号，屏幕评分时未对答案的另一空会被挖掉（`printing._dictation_line`、`review/view.js dictationStem`），不会互相泄露答案。去重键见 `data.md`。

## Agent harness（`harness.py`、`agent.py`、`agent_draft.py`、`agent_ops.py`）

对标 Pi（`@earendil-works/pi-agent-core` 的 agent-loop 与 coding-agent 的 subagent 扩展），只用标准库。

### 循环（`harness.Agent.run`）

一次 run = 若干轮；一轮 = 把上下文发给模型（`ai_assist.chat`，带 `tools`）→ 模型回复文字和 / 或工具调用 → 按顺序执行工具 → 结果作为 `tool` 消息回到上下文。模型不再调用工具就结束。

- 事件：`agent_start / turn_start / message_start / delta / toolcall_delta / message_end / tool_start / tool_update / tool_end / sub / turn_end / steer / agent_end`，由 `draft_runs.Host.event` 变成对话里的块（见下一节），经 SSE 实时推给前端。
- 参数校验：必填项与类型（字符串数字会按 schema 转成整数）；不合法、找不到工具、工具抛 `ToolError / ValueError / KeyError` 都变成一条错误结果回给模型，让它自己改。
- 截断：`finish_reason=length` 时这一轮的工具调用一律不执行，回一条「参数可能被截断，请拆小重发」。
- 插话（steering）：run 进行中用户再发话进 `agent.inbox`，每轮结束时读进上下文；模型本来要停也会再看一遍队列。run 刚结束时到的插话由宿主接着再跑一次。
- 停止（abort）：每次请求模型前、每个工具前检查；`/api/draft/abort` 同时作废这次 run 的令牌，之后它的写入全部丢弃（已做的改动保留，可「回到修改前」）。
- 上限：`agent_max_turns`（默认 30，子代理 `agent_sub_turns` 16）；到上限时在回复里说明。
- 系统说明不用 system 角色，并进第一条用户消息（与旧流程一样兼容不建议设 system 的视觉模型）。
- 图片：消息里只存引用（`{page}` / `{image}`），发送时才转 data URL 并按（图片, 宽度, 旋转）缓存；页序、旋转、每页说明来自准备阶段（`draft.pages`），说明会写进提示词；只发本次 run 的图，更早的换成一句占位，需要时模型调用 `view_pages`，图片作为下一条用户消息附上。页数 ≤ 2 时主代理看全分辨率（1600），否则看 1024 宽的全卷；子代理看自己页的全分辨率。
- 上下文超过 48 条时保留第一条 + 从某条 assistant 开始的最近若干条；持久化的 `agent.messages` 最多 160 条，从一条真实用户消息处截断，不拆开工具调用与结果。

### 对话时间线与实时流（`draft_runs.py`、`live.py`，v0.3）

目标是 Pi / Claude Code 那样的 Harness 交互：看得见模型在想什么、每次调了什么工具，而不是一个等半天的进度块。

- **流式**：`ai_assist.chat` 带 `stream: true`，逐片解析 SSE：`delta.reasoning_content`（或 `reasoning`、正文里的 `<think>…</think>`，由 `ThinkSplitter` 拆开）→ 思考；`delta.content` → 正文；`delta.tool_calls[i].function.arguments` → 工具参数。服务端不支持流式、直接回 JSON 时照常解析。思考只展示，不回传给模型。
- **harness 事件** → `draft_runs.Host.event` → **块**：`message_start` 开一条新消息；`delta(thinking)` 开 / 续思考块；`delta(text)` 收掉思考块、开 / 续正文块；`toolcall_delta` 收掉前两者、按下标开工具块（状态 preparing，参数逐字）；`message_end` 定稿（非流式时补建块），工具块状态 pending；`tool_start / tool_update / tool_end` 更新同一个工具块（running → done / error，结果前 6000 字）。`sub` 事件（子代理）递归处理，块带 `parent`（delegate 工具块 id）和 `task`。run 结束追加一个 `run` 块（状态、轮数、工具次数、用时、改动芯片、base_revision）。
- **写盘与推送**：块的开始 / 状态变化 / 结束在锁内写进草稿文件，并推 `{type: "block", block}`；逐字内容只进 `live.py` 内存并推 `{type: "delta", id, field, text}`；改动草稿（`flush`）和状态变化推 `{type: "status"}`；插话挪位、停止推 `{type: "reload"}`。读草稿时 `live.overlay` 把进行中的逐字内容盖上去，`live_seq` 告诉前端从哪条事件接着订阅。
- **用量**：每条模型消息结束和每次工具结束推 `{type: "stats", stats}`（见「模型接口」）。
- **SSE**：`GET /api/draft/events?id=&since=`（`Last-Event-ID` 优先），每 15 秒心跳，5 分钟后让浏览器自动重连；缓冲区（每份草稿 4000 条）不够时推 reload。
- **系统说明**要求模型每次调用工具前先用一句话说明要做什么（没有思考输出的模型也有「边想边做」的可见过程）。
- 停止：`draft_runs.abort` 作废令牌、设停止信号；流式读取中的 `on_delta` 检查到停止会立刻抛出，连接随之关闭；进行中的块写回已收到的内容，标为已停止，追加 `run` 块（带这次已做的改动，可回到修改前）。

### 任务与工具集（`agent.run`）

| 任务 | 触发 | 工具 |
| --- | --- | --- |
| `extract` | 上传后在准备阶段确认页面、点「开始识别」 | 草稿工具 + `delegate` |
| `revise`（对话） | 在对话里发话 | 草稿工具 + `delegate` + `draft_commit` + 题库 + 记录 + 复习反馈；已入库的草稿只剩 `draft_view` / `view_pages` + 后三类 |
| `review` | `POST /api/drafts {images, review_session}` → 准备阶段确认 → 「开始批改」。0.5 起复习页不再有入口（改为右侧的「复习助手」，见文末），接口与已有的批改会话保留 | 复习反馈 + 记录 + `library_search` / `library_get` + `view_pages` |

草稿工具（`agent_draft.py`，一次 run 共用一个 `Workspace`，每次改动在锁内取快照并写进本次 run 的那一版 revision）：

| 工具 | 作用 |
| --- | --- |
| `draft_view(gid?)` | 大纲 + 待补问题 + 去重（入库后新增几题、哪篇已在题库）；给 gid 返回该板块全文 |
| `group_add(genre, title…)` / `group_delete(gid)` | 建 / 删板块；名句默写只允许一个板块 |
| `material_set(gid, title?, author?, source?, text?, append?)` | 改材料；长原文可分几次追加 |
| `items_add(gid, items[])` | 按顺序加小题；有答案未写来源时记为图中答案 |
| `item_update(ref, …字段)` / `item_delete(ref)` | 逐题改任意字段 / 删；`ref` 可以是 iid 或题号；改答案未写来源时记为 AI 改写 |
| `dictation_add(entries[])` / `dictation_update(ref, …)` | 默写模板 + 答案表 |
| `view_pages(pages[])` | 重新看原图 |

所有输入都经 `draft_schema.normalize_item / normalize_dictation / clean_text`，和手工编辑同一套规则。

### 子代理（`delegate`）

主代理（系统说明要求：3 页以上或 2 个以上大题时委派）调用 `delegate(tasks=[{genre, title?, pages[], instructions?, gid?}])`：

1. 宿主先为每个任务建好板块（默写并入唯一的默写板块；给了 gid 就在已有板块上补录 / 修正）。
2. 每个任务起一个子 `Agent`：只看自己那几页（全分辨率），工具集是限定在该板块的草稿工具（不能建 / 删板块，越界报错），并发数 `agent_subagents`（默认 3）。子代理与主代理共用停止信号。
3. 进度经 `tool_update` 推到主代理的这一步（`tasks: [{n, gid, genre, title, pages, status, tools, turns, last, summary, error}]`），前端画成子代理卡片。
4. 全部结束后把每个子代理的总结（或失败原因）作为工具结果交回主代理；一个子代理失败不影响其它。主代理再 `draft_view` 检查、补漏、总结。

### 题库 / 记录 / 复习反馈工具（`agent_ops.py`）

`library_search`、`library_get`、`library_update`、`material_update`、`library_suspend`、`library_delete`、`library_restore`；`records_list`、`record_add`、`record_update`、`record_delete`、`record_restore`（语义见 `data.md`「复习记录」）；`sessions_list`、`session_get`、`review_grade`（`sessions.grade_many`，一个事务写多题评分 + 反馈）。「增」题走草稿 + `draft_commit`（`_Host.commit` → `creation.commit_draft`），不绕过草稿。删除类工具的说明要求只在用户明确要求时使用；它们都可撤销。

### 模型接口（`ai_assist.chat`）

`POST /chat/completions`，`messages` + `tools`，`temperature` 0.1，`max_tokens` 取设置，`stream: true`（服务回 JSON 也能解析）。返回 `{content, thinking, tool_calls:[{id, name, arguments}], finish_reason, usage: {input, output, estimated}, timing: {ttft, gen, tps}}`。思考（`reasoning_content` / `reasoning` / `<think>`）只展示，不回传给模型。带工具的请求被 400/404/422 拒绝且报错提到 tool / function 时，提示换模型或关掉 Agent 模式。

用量：请求带 `stream_options: {include_usage: true}`，用服务回的 `prompt_tokens / completion_tokens`；服务不认这个参数（400 / 422）时去掉重发，并按 API 地址记住（进程内），改用估算——`approx_tokens`：汉字约 1 token、其余约 4 字符 1 token，图片按 800；`estimated: true`。`ttft` 是首个片段到达的秒数，`tps` = 输出 token ÷（最后一片 − 第一片），生成太短（< 0.05 秒）记 0。

草稿上的累计（`agent.stats`，`draft_runs.Host._count`）：每条模型消息结束时 `turns`（主代理）或 `sub_turns`（子代理）+1，累加 `input_total / output_total`；主代理那次的输入 + 输出记为当前上下文 `context`；有效速度更新 `tps / ttft`；每次工具结束 `tool_calls` +1。每次变化推一条 `{type: "stats", stats}`（带 `window` = 设置里的 `ai_context_window`，默认 128000），前端输入框的圆环用它。

## 复习助手（`clms/review_ai.py`，v0.5）

复习评分页右侧的 AI。它**不是 Agent**：不调用工具、不写 Ledger，只回答和给建议；评分、反馈由学生点「采用」后经已有接口写入。接口与事件见 `api.md`「复习助手」。

- **无状态**：对话由前端保存（按「复习 + 题」），每次请求带最近 `MAX_TURNS`（16）轮；照片只传编号，最近 `MAX_IMAGES`（4）张发原图（1280 宽），更早的在文字里写一句「已省略」。
- **上下文**（并进第一条用户消息，不用 system 角色，和录入对话一致）：助手规则与评分档 → 这道题（板块、卷上题号 / 原卷题号、题型、分值）→ 材料原文（最多 6000 字）→ 题干（默写把 `{书写区域}` 换成横线）→ 参考答案（阅卷标准）→ 解析 / 录入时的作答 / 错因 → 以前的复习（最近 6 条：日期、评分、反馈）→ 本次复习的评分。学生还没对答案、也还没评分时，要求模型除非学生要求否则不直接说出参考答案。
- **三种模式**（任务说明拼在这一轮用户消息的末尾）：
  - `ask`：直接回答。
  - `grade`：逐个采分点判断，最后一行 `【建议】{"grade": n, "note": "…"}`；grade 按板块校验（阅读 0–3，默写 0 / 1 / 3），不合法就丢掉只留 note；对话里找不到作答时要求模型请学生发作答，不编分、不写建议。
  - `feedback`：按当前评分写一条 40 字以内的反馈，最后一行 `【建议】{"note": "…"}`。
  - 文字为空时用默认话（「请对照参考答案给我的作答打分。」等）。
- **解析**：取最后一个「【建议】」之后的 JSON（`ai_assist.extract_json`），正文去掉这一行作为 `reply`；流式期间前端也把「【建议】」之后的内容藏起来。
- **流式**：`ai_assist.chat(stream)` 在后台线程里跑，思考 / 正文逐字经队列变成 SSE；客户端断开时设停止信号，下一片到达时抛出，连接随之关闭。
- 假模型（`tests/fake_ai.py`）：第一条消息含「## 复习助手」时按任务说明给确定性回答——打分时对话里有「作答：」或照片才给 `【建议】{"grade": 2, …}`。
