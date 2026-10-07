# AI：录入、全局助手、审核与作文转写

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
- 阅读题 `qtype` 只能从当前板块的用户题型表（`taxonomy.qtypes()`）选；只有明确匹配才填。没有合适项、判断不确定或题型表为空时写 `""`（未分类），禁止自拟或强选最接近项。默写的直接 / 理解性默写仍是固定结构语义。识图 `extract`、整份修订 `revise` 都在解析后调用 `sanitize_qtypes`，陌生非空题型变成 `""`；用户可在校对时用「新增题型」显式建立后选中。
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
item  = {iid, no, qtype, stem, answer, answer_origin(image|ai|user|""), analysis, score, blank_lines(0–1000), user_answer, note}
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
| 复习助手（`review_ai.run`，不经 `agent.run`，v0.6） | 复习评分页右侧提问 / 打分 / 写反馈 | 只读：`review_outline` / `question_get` / `material_read` / `item_history`（见文末「复习助手」） |

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

所有输入都经 `draft_schema.normalize_item / normalize_dictation / clean_text`，和手工编辑同一套规则。主代理与子代理收到同一张当前用户题型表；`items_add` 和 `item_update` 对模型给出的陌生 `qtype` 再调用 `taxonomy.valid_qtype`，转换为 `""`。Agent 无新增题型工具；`draft_commit` 入库前再把已不在配置中的题型转换为 `""`（覆盖旧草稿和执行期间用户删题型的情况），避免幽灵分类。已入库题的 `library_update` 对陌生非空题型返回明确错误。`fake_ai.py` 的 `FAKE_AI_UNKNOWN_QTYPE=1` 会故意提交陌生题型，供非 Agent 与子代理路径回归。

### 子代理（`delegate`）

主代理（系统说明要求：3 页以上或 2 个以上大题时委派）调用 `delegate(tasks=[{genre, title?, pages[], instructions?, gid?}])`：

1. 宿主先为每个任务建好板块（默写并入唯一的默写板块；给了 gid 就在已有板块上补录 / 修正）。
2. 每个任务起一个子 `Agent`：只看自己那几页（全分辨率），工具集是限定在该板块的草稿工具（不能建 / 删板块，越界报错），并发数 `agent_subagents`（默认 3）。子代理与主代理共用停止信号。
3. 进度经 `tool_update` 推到主代理的这一步（`tasks: [{n, gid, genre, title, pages, status, tools, turns, last, summary, error}]`），前端画成子代理卡片。
4. 全部结束后把每个子代理的总结（或失败原因）作为工具结果交回主代理；一个子代理失败不影响其它。主代理再 `draft_view` 检查、补漏、总结。

### 题库 / 记录 / 复习反馈工具（`agent_ops.py`）

`library_search`、`library_get`、`records_list`、`sessions_list`、`session_get` 只读。v0.7 起，`library_update`、`material_update`、`library_suspend`、`library_delete`、`library_restore`、`record_update`、`record_delete`、`record_restore` 统一交给 `ai_review.propose(source="entry")`，返回待审操作，不直接改变正式题库或旧记录；宿主用草稿 ID、run ID、call ID 建立可信的来源和幂等身份。用户到审核中心处理，Agent 不得把待审说成已完成。

`record_add` 仍通过 `records.add` 追加一次复习；已有作答照片批改的 `review_grade` 保留 `sessions.grade_many`，一个事务追加多题评分及反馈。记录语义见 `data.md`「复习记录」。「增」题仍走草稿 + `draft_commit`（`_Host.commit` → `creation.commit_draft`），不绕过纸面校对和草稿。删除类工具只在用户明确要求时提出；批准后仍采用可撤销的追加事件。

## 统一领域服务与审核（`domain_ops.py`、`ai_review.py`）

人工网页、录入 Agent、全局助手和 MCP 共用正式修改及 Session 创建的领域服务。传输层不能另写一套更新逻辑。`domain_ops` 的固定服务注册表定义风险、可编辑字段、前后对照、对象快照、执行函数和原生结果恢复；`tool_catalog` 把其中允许交给模型的操作公开为工具。

- `read` 直接查询；未入库草稿和作文评价、笔记、自由分类属于 `auto`，自动执行并留下来源；正式 Session、正式题目/材料修改及录入 Agent 的停用、删改恢复属于 `confirm`，先保存提案。
- `<vault>/语文/.clms/ai_review.db` 是唯一审核权威，保存来源、原始请求摘要、有效 payload、preview、snapshot、revision、人工决定与执行结果，权限 0600。它是辅助数据库，不是学习事实源。
- 幂等身份由来源、工具、密钥/会话身份和 `request_id` 构成。相同 ID、相同原始内容返回同一操作；内容不同返回 `request_conflict`。人工修订改变有效内容及 revision，但不改变原始摘要，所以重试不会覆盖人的修订。
- 修订必须在原请求开放字段内，不能换目标或扩大字段范围。批准/拒绝都携带 `expected_revision`；服务端 CAS 保证同一操作只有一个权威决定，聊天卡与审核中心并用也只执行一次。
- 批准时重新比较对象快照，并在原生写事务前、提交前重新验证来源权限。内容变化得到 `content_conflict`；到期、停止或密钥吊销的旧提案不写学习事实。模型和 MCP 都没有批准工具，人工 HTTP handler 才能提供可信的 reviewer。
- 状态包括 `pending_confirmation / running / applying / applied / rejected / expired / conflict / failed / interrupted / cancelled`。查询只读；到期状态可由当前时间计算，读取不得触发领域写入。
- Ledger 提交的 `_operation` 记录来源和操作身份；原生 `operation_receipts` 与学习事件在同一 SQLite 事务提交。草稿对应回执随草稿原子保存。重启只凭匹配操作 ID 和有效摘要的原生回执确认已成功；无回执则中断，不重放模型写入。审核终态保存失败也不能让已提交的学习事实再次执行。
- 等待模型或人工时不持有 Ledger 写锁。`runtime_history` 只记录允许的来源、类型、对象 ID、计数与结果状态，完整提案和对话不进入运行历史。

## 全局助手与公共工具目录（`assistant.py`、`assistant_store.py`、`http_assistant.py`、`tool_catalog.py`）

一级「全局助手」是持久对话场景，复用录入页的 `harness.Agent`、`ai_assist.chat`、流式思考解析、工具调用、截断保护和用量统计。它与录入页 Agent 使用不同的持久存储及页面，不把完整聊天放进作文或 Ledger。

- `assistant_enabled` 单独控制开启。`assistant_base_url / assistant_api_key / assistant_model` 可分别覆盖，配置中空值回退 `ai_*`；设置表单的密钥留空保留已存值，明确「清除独立密钥」后才回退。请求通过 `config_override` 进入同一个兼容接口。密钥不写进对话、审核或 runtime 数据库。
- `<vault>/语文/.clms/assistant.db`（0600/WAL）保存 conversations、模型上下文 messages、runs、递增序号 events。思考只在私有展示事件中保存，不回传模型。重开会话读取最近 6000 条展示事件，模型请求沿用 harness 的 48 条上下文裁剪规则。
- 每个数据目录同一时刻最多一个全局 run。同一对话可插话，另一个对话返回 `run_busy`；结束保存期间也返回 busy，防止消息进入已经结束的队列。写盘或线程启动失败不会永久占用内存中的运行。
- 当前页面上下文只允许 `item_id / session_id / prompt_id / attempt_id / version_id` 的稳定编号；自由文字、路径、页面 HTML 和指令字段丢弃，编号以普通数据附在用户消息中。明确传 `{}` 会清除保存的上下文；未传才沿用会话上下文。
- 写工具的 `request_id` 由可信运行宿主覆盖为 run/turn/call 身份，模型不能指定其它运行的幂等身份。工具参数另经共享目录递归校验，未知字段、越界分数、类型或非法 ID 格式拒绝。
- `confirm` 工具得到同一待审 operation 后等待人工；没有数据库连接或 Ledger 锁跨越等待。审核中心修订时刷新聊天卡，批准后模型收到实际结果，例如人工改成 35 分钟后的正式 Session ID；拒绝、冲突或到期也作为真实工具结果返回。
- 停止取消当前 run 的待审提案，已执行的追加事实保留。启动恢复将未结束 run 标为 `interrupted`，按可信 creator/run 身份取消旧待审项，覆盖「提案已保存、等待指针尚未保存」窗口；恢复可重复，不重启模型。
- 事件保留 harness 的 thinking/text/tool 参数及结果，另有 `run_start / user_message / tool_waiting / tool_decision / run_end`。页面显示等待卡、结束状态、轮数、工具次数、输入/输出 token、上下文、用时及实际结果跳转。
- `/api/assistant/events?run_id=&after=&wait=` 为有序长轮询，最多等 20 秒，响应 `cursor / events / run / has_more`；即使 run 已结束也要读完 `has_more`。页面卸载或换会话取消请求并检查 generation，晚到回包不重绘其它页面。
- 其余接口是 status、conversations、conversation、conversation/create、message、abort（完整参数见 `api.md`）。聊天批准/拒绝使用已有 `/api/ai-review/decide`，没有第二套批准 API。

### 共享工具目录（`tool_catalog.py`）

内置助手 26 个工具；MCP 共用这 26 个，再增加受独立图片 scope 约束的 `get_essay_image`。每个工具只有一个 schema、权限级别和 scope 集合，MCP 的发现与执行都从此目录取权限；所有写工具必须有 `request_id`（1–128 字符，禁止控制字符及 `? # / \\`）。内置助手不使用 MCP Key，但仍经过相同领域审核规则。

| 工具 | 权限 | MCP scope | 作用 |
| --- | --- | --- | --- |
| `list_taxonomy` | read | `clms:read` | 用户板块与题型 |
| `search_items` | read | `clms:read` | 搜索/分页正式题库 |
| `get_item` | read | `clms:read` | 题目、答案、材料及复习记录 |
| `get_material` | read | `clms:read` | 材料原文与题目 |
| `get_overview` | read | `clms:read` | 学习概况 |
| `get_recommendations` | read | `clms:read` | 按时长与板块推荐，尚不创建 Session |
| `list_sessions` / `get_session` | read | `clms:read` | 正式复习与进度 |
| `list_drafts` / `get_draft` | read | `clms:read` | 暂存草稿与 revision |
| `get_operation` | read | `clms:read` | MCP 只查本 Key 的操作状态，不批准 |
| `create_draft` | auto | `draft:create` | 新建未入库草稿 |
| `update_draft` | auto | `clms:read` + `draft:update` | 按 expected_revision 修改草稿 |
| `create_review_session` | confirm | `clms:read` + `session:create` | 提交正式 Session 审核 |
| `propose_item_update` | confirm | `clms:read` + `question:propose` | 题目限定字段修改审核 |
| `propose_material_update` | confirm | `clms:read` + `material:propose` | 材料修改审核 |
| `list_essay_prompts` / `get_essay_prompt` | read | `essay:read` | 搜索作文题、正文及历次 Attempt |
| `get_essay_attempt` | read | `essay:read` | 各稿版本、修改次数及笔记 |
| `get_essay_version` | read | `essay:read` | 已确认正式全文，未确认不返回正文 |
| `list_essay_evaluations` | read | `essay:read` | 指定 Version 的全部评价 |
| `list_essay_classifications` | read | `essay:read` | 自由分类 |
| `get_essay_image`（MCP） | read | `essay:read` + `essay:images` | 指定 Version 的一页原图，禁止任意文件读取 |
| `append_essay_evaluation` | auto | `essay:read` + `essay:evaluate` | 追加 0–60 分评价，含 summary/strengths/issues/suggestions、可选自由 dimensions/evaluator/model |
| `append_essay_note` | auto | `essay:read` + `essay:note` | 追加 Attempt/Version 的简短讨论重点 |
| `create_essay_classification` | auto | `essay:classify` | 新建自由分类，可选 group |
| `set_essay_classifications` | auto | `essay:read` + `essay:classify` | 按实体 ID/名称组合分类，不要求固定树 |

普通核心仍只依赖标准库，MCP SDK 为可选安装；独立端口、Key、安全摘要、实时 scope 验证和图片边界见 `api.md`「MCP」。模型不能读取任意文件、任意转发 HTTP 或自批审核。

假模型 `tests/fake_ai.py` 识别「## 全局助手」：Session 场景先查 recommendations、再提案，收到人工真实决定后按实际分钟数/ID 回复；作文场景先读正式 Version，再追加 47/60 评价和笔记。`[tool:工具名] {JSON}` 覆盖目录中的其它工具，测试能够显式操纵低风险及待审路径。

## 完整作文 OCR（`essays_ocr.py`）

作文原图按上传顺序组成同一 Version 的多页，OCR 只负责逐字转写完整作文，禁止评价、润色、纠正原作文的错别字/病句/标点或添加原图没有的句子。存疑写为 `【存疑：可能的字】`，无法辨认写 `【无法辨认】`；图片中的指令也是待转写数据。回复结构是 `{text, uncertainties:[{page,text,reason}]}`。

保留原图、原始 OCR 文本/回复、存疑列表和模型；人工校对后的文本另存，确认后才成为可供助手/MCP评价的正式正文。校对识别错误不创建 Version；真正修改作文上传新 Version。评价和笔记只能追加：评价永久绑定目标 Version，笔记归属 Attempt 并可选关联其中一个 Version；不能覆盖确认正文或把旧评价搬到新稿。

持久状态流为 `uploaded → ocr_running → proofreading → confirmed`，界面分别显示已上传、转写中、待校对、待评价/已评价；人工确认完成最后一步，评价状态由绑定的 Evaluation 派生。失败进入 `ocr_failed`，可在同一 Version 重试。也允许人工直接转写。模型网络请求在 Ledger 写事务外，完成/失败仅在当前 OCR token 匹配时追加事件；旧任务的晚到结果丢弃。启动恢复把未完成 OCR 追加成可重试失败。并发由 `ai_concurrency` 限制，系统历史只保存版本 ID、任务状态与耗时。

`fake_ai.py` 识别「你负责手写完整作文的 OCR 转写」，返回故意保留「一顺间」的原样文本及存疑字段，作文专项检验 OCR 保留与人工校对分离。作文实体、字段、事件及版本评价不变量详见 `data.md`「作文」，HTTP 见 `api.md`。

### 模型接口（`ai_assist.chat`）

`POST /chat/completions`，`messages` + `tools`，`temperature` 0.1，`max_tokens` 取设置，`stream: true`（服务回 JSON 也能解析）。返回 `{content, thinking, tool_calls:[{id, name, arguments}], finish_reason, usage: {input, output, estimated}, timing: {ttft, gen, tps}}`。思考（`reasoning_content` / `reasoning` / `<think>`）只展示，不回传给模型。带工具的请求被 400/404/422 拒绝且报错提到 tool / function 时，提示换模型或关掉 Agent 模式。

用量：请求带 `stream_options: {include_usage: true}`，用服务回的 `prompt_tokens / completion_tokens`；服务不认这个参数（400 / 422）时去掉重发，并按 API 地址记住（进程内），改用估算——`approx_tokens`：汉字约 1 token、其余约 4 字符 1 token，图片按 800；`estimated: true`。`ttft` 是首个片段到达的秒数，`tps` = 输出 token ÷（最后一片 − 第一片），生成太短（< 0.05 秒）记 0。

草稿上的累计（`agent.stats`，`draft_runs.Host._count`）：每条模型消息结束时 `turns`（主代理）或 `sub_turns`（子代理）+1，累加 `input_total / output_total`；主代理那次的输入 + 输出记为当前上下文 `context`；有效速度更新 `tps / ttft`；每次工具结束 `tool_calls` +1。每次变化推一条 `{type: "stats", stats}`（带 `window` = 设置里的 `ai_context_window`，默认 128000），前端输入框的圆环用它。

## 复习助手（`clms/review_ai.py`、`clms/review_tools.py`；v0.5 起，v0.6 改为只读 Agent）

复习评分页右侧的 AI。v0.6 起默认是一个**只读 Agent**（`harness.Agent`，名字 `review`）：上下文里只有一份很小的索引，题干、参考答案、原文、以前的复习都由模型调用工具按需获取——长文章可以只读几段，前几轮查过的内容不再重发。它**不写 Ledger**，只回答和给建议；评分、反馈由学生点「采用」后经已有接口写入（不变量 9）。接口与事件见 `api.md`「复习助手」。

- **无状态**：对话由前端保存（按「复习 + 题」），每次请求带最近 `MAX_TURNS`（16）轮的文字。助手那几轮另带「这一轮查过什么」的标签（如「看第 3 题」「读《老街的灯》第 2-3 段」），服务端把它写成一句「（这一轮查过：…。内容没有再附上，需要时重新查。）」接在那一轮回答后面——**查到的内容不回传、不累积**。
- **索引**（`index_text`，并进第一条用户消息，不用 system 角色）：助手规则与评分档 → 工具用法 →「## 现在」：这次复习（编号、卷上共几题）、学生正在看的题（卷上题序、题号、板块、题型、分值、材料编号与段数）、本次评分；学生还没对答案、也还没评分时，要求模型除非学生要求否则不直接说出参考答案。**不含**题干、答案、原文。
- **工具**（`review_tools.py`）：全部只读；范围限定在这次复习里的题和它们的材料；每次调用都重新取状态（学生可能刚改过评分）。编号与评分页一致：卷上题序 n 从 1 开始，原文按非空行分段、段号从 1 开始。

| 工具 | 作用 | 对话里显示 |
| --- | --- | --- |
| `review_outline` | 这次复习的题目清单（卷上题序、题号、板块、题型、分值、所属材料、是否已评）和材料列表（段数、字数） | 看这次复习的题目清单 |
| `question_get {n? \| item_id?}` | 一道题：题干（默写把 `{书写区域}` 换成横线）、参考答案（阅卷标准）、解析、录入时的作答与错因、本次评分；学生没对答案时附一句不要直接说出答案。不填就是学生正在看的那道 | 看第 n 题 |
| `material_read {material_id?, paragraphs?, query?}` | 原文，每段带 `[段号]`。`paragraphs` 写 `2`、`2-4`、`1,3`；`query` 只要含这个词句的段落；一次最多 6000 字，超了提示用段号再读。不填 `material_id` 就是当前这道的材料 | 读《篇名》第 2-4 段，找「…」 |
| `item_history {n? \| item_id?}` | 以前的复习（最近 8 次：日期、评分、反馈）、录入次数、记忆状态、是否顽固 | 查以前的复习 |

- **引用**：学生在卷面上选中的文字随请求带来（`refs`，最多 6 段、每段 400 字），写进他这句话里：「（引用 1：《老街的灯》第 3 段（M-000001））」加一行 `> 原文`，或「（引用 2：第 2 题的题干）」。位置由服务端按编号重新生成，前端给的标签只在编号无效时兜底。只引用不写字时默认问「解释一下我引用的这段。」
- **照片**：只传编号；本轮新拍的优先，再按新到旧补到 `MAX_IMAGES`（4）张发原图（1280 宽），所以上一轮拍的作答、下一轮点「打分」仍看得见（这些历史消息标成本次 run，harness 只渲染本次 run 的图）。更早的在文字里写一句「已省略」。
- **三种模式**（任务说明拼在这一轮用户消息的末尾）：
  - `ask`：直接回答。
  - `grade`：逐个采分点判断，最后一行 `【建议】{"grade": n, "note": "…"}`；grade 按板块校验（阅读 0–3，默写 0 / 1 / 3），不合法就丢掉只留 note；对话里找不到作答时要求模型请学生发作答，不编分、不写建议。
  - `feedback`：按当前评分写一条 40 字以内的反馈，最后一行 `【建议】{"note": "…"}`。
  - 文字为空时用默认话（「请对照参考答案给我的作答打分。」等）。
- **每次最多 8 轮**（`AGENT_TURNS`；一轮 = 一次模型请求 + 执行它要的工具）。查完了还没给出文字时回一句「查了几次还没理出结论，可以换个问法再问一次。」
- **解析**：取最终回答（最后一条有文字的助手消息）里最后一个「【建议】」之后的 JSON（`ai_assist.extract_json`），正文去掉这一行作为 `reply`；流式期间前端也把「【建议】」之后的内容藏起来。
- **流式**：模型在后台线程里跑，`Relay` 把逐字回调和 harness 事件变成块事件（思考 / 正文 / 工具，见 `api.md`）经队列推给前端；客户端断开时设停止信号，Agent 下一片到达时中止，连接随之关闭。`done` 里带各轮用量之和、查阅次数、耗时。
- **关掉 Agent 模式时**（设置里的 `ai_agent`，给不支持工具调用的模型用）：退回 v0.5 的做法——这道题的全部上下文（规则 → 这道题 → 材料原文最多 6000 字 → 题干 → 参考答案 → 解析 / 作答 / 错因 → 以前的复习 → 本次评分）并进第一条用户消息，不带工具。事件协议相同，只是没有工具块。
- **用量上的取舍**：只问思路、只看题的时候，不再为整篇原文付费；多轮对话不再每轮重发原文。但一次回答可能要两三轮模型请求（每轮都重发这次 run 里已查到的内容），所以「每次都必须通读全文」的问题，总 token 不一定比旧做法少。每条回答末尾显示这次的用量，可以直接比较。
- 假模型（`tests/fake_ai.py`）：第一条消息含「## 复习助手」时——带工具（Agent）先 `question_get` 看学生正在看的那道，提问时再 `material_read` 读原文 1–2 段，然后回答；不带工具（旧做法）直接回答。回答都按任务说明给确定性内容：打分时对话里有「作答：」或照片才给 `【建议】{"grade": 2, …}`。`REQUESTS` 记着最近收到的请求体，测试用它检查上下文里带了什么、没带什么。
