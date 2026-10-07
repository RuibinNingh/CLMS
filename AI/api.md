# HTTP 接口与命令行

> 速查：`clms/server.py` 是传输外壳，`http_registry.py` 用 `@route(method, path)` / `register_routes()` 唯一登记领域适配；`ThreadingHTTPServer`，默认 `127.0.0.1:8472`。请求 / 响应都是 JSON（打印页和图片除外）。POST 校验 `Origin` 与 `Host` 一致，请求体上限 80MB。

## 错误约定

处理函数抛 `KeyError` → 404，普通 `ValueError` → 400，带 conflict 错误码 → 409、forbidden → 403，其它异常 → 500（打印堆栈）。处理函数也可以返回 `Stream`（SSE 生成器，GET / POST 都可以）；连接结束时外壳会关闭生成器，让它的 `finally` 立即执行。响应体 `{"error": "not_found|invalid|server|origin|too_large|bad_json", "msg": "给人看的中文说明"}`。前端 `core/api.js` 把 `msg` 作为 `error.message`。

## 端点

| 方法 路径 | 参数 | 返回 |
| --- | --- | --- |
| GET `/api/summary` | — | 概览统计（见 `algorithm.md`）+ `ai_ready`、`version` |
| GET `/api/taxonomy` | — | `{genres, qtypes:{genre:[题型]}, qtype_kinds:{genre:{题型:skill\|recall}}, uncategorized:{genre:题数}, usage:{genre:{题型:题数}}}`；默写两类型固定，三个阅读板块是用户实际配置 |
| POST `/api/taxonomy/add` | `{genre,name}` | 同 GET；名称去首尾空格，默认 `skill`，同板块不可重名 |
| POST `/api/taxonomy/rename` | `{genre,old_name,new_name}` | 同 GET；已有题逐题追加 `item.update`，记忆类型迁移，可在中断后同参数重试 |
| POST `/api/taxonomy/delete` | `{genre,name,replace_with?}` | 同 GET；仍有题使用时必须给 `replace_with`（同板块其它已有题型，或空字符串表示未分类），没有迁移目标则 400 |
| POST `/api/taxonomy/reorder` | `{genre,names:[完整有序题型表]}` | 同 GET；集合必须与现有表一致，只改配置 |
| POST `/api/taxonomy/kind` | `{genre,name,kind:skill\|recall}` | 同 GET；改后下次读取调度状态立即生效 |
| GET `/api/config` | — | 配置；密钥不回显，只给 `ai_api_key_set` / `assistant_api_key_set`。含 `ai_context_window`（上下文窗口 token 数，默认 128000，输入框圆环按它算占用） |
| POST `/api/config` | 配置补丁；`ai_api_key` 留空表示不改，`clear_api_key: true` 清除；独立助手密钥同样留空保留、`clear_assistant_api_key: true` 清除；忽略直接提交的 `qtypes` / `qtype_kinds` / 迁移标记，题型操作走专用接口 | 同 GET |
| GET `/api/activity` | `limit` | `{items:[{commit_id, created_at, type, message}]}` |
| GET `/api/ledger/verify` | — | `{ok, count, error}` |
| GET `/api/source/export` | — | 脱敏源码包 zip（`Content-Disposition` 带文件名，见下文） |
| GET `/api/drafts` | `view(all/active/ready/committed/trash), q, offset, limit` | `{drafts:[{id,status,kind,title,name,images(首张),pages,units,genres,error,committed,bucket,snippet,updated_at,…}], total, counts:{all,active,ready,committed,trash}, ai_ready}`；按最近更新排序 |
| POST `/api/drafts` | `{images:[{name, data}], hint}`、`{manual: genre}`、`{chat: true}` 或 `{images, review_session}` | `{drafts:[草稿视图]}`；带图的一律是一份 **staged（准备中）** 草稿，不直接执行 |
| POST `/api/draft/pages` | `{id, pages:[{image, rotate(0/90/180/270), note}], hint, add:[{name, data}]}` | 草稿视图；只在准备阶段可用；pages 只能包含这份草稿的图片 |
| POST `/api/draft/start` | `{id, split}` | `{ids, draft}`；开始识别（review 草稿是开始批改）；`split` 时每页一份、分别识别 |
| POST `/api/draft/rename` | `{id, name}` | 草稿视图（空名恢复自动标题，最多 40 字） |
| POST `/api/draft/undiscard` | `{id}` | 草稿视图（从回收站恢复到丢弃前的状态） |
| POST `/api/draft/delete` | `{id}` | `{id, deleted}`；只能彻底删除回收站里的草稿（原图保留） |
| GET `/api/draft/events` | `id, since`（或 `Last-Event-ID`） | SSE：`block` / `delta` / `status` / `stats` / `reload` 事件（见 `ai.md`「对话时间线与实时流」） |
| GET `/api/draft` | `id` | 草稿视图（见下） |
| POST `/api/draft/message` | `{id, text, with_image, images:[{name,data}]}` | 草稿视图；AI 在后台执行，状态变为 `thinking`。Agent 模式下 AI 正在执行时进插话队列（`queued` 计数），已入库的草稿也能继续聊 |
| POST `/api/draft/abort` | `{id}` | 草稿视图；停止正在执行的 Agent |
| POST `/api/draft/edit` | `{id, groups, revision}` | 草稿视图；`revision` 不是最新时 400 |
| POST `/api/draft/restore` | `{id, revision}` | 草稿视图（新增一版，内容等于目标版） |
| POST `/api/draft/retry` | `{id}` | 草稿视图（重跑 `last_job`） |
| POST `/api/draft/commit` | `{id}` | 草稿视图，`committed = {commit_id, created, reencountered, skipped, item_ids, material_ids}` |
| POST `/api/draft/discard` | `{id}` | `{id, status}`；放进回收站（已入库的也可以，题库不受影响；执行中不行） |
| GET `/api/image` | `id`（`<sha24>.<ext>`） | 图片字节，长缓存 |
| GET `/api/items` | `genre, qtype（__unclassified__ 筛选空题型）, status(新录入/巩固中/待攻克/已掌握/leech/suspended/deleted), kind(skill/recall), added(7/30/90/old), last(never/7/30/old), grade(none/low/mid/high), material, q, sort(priority/due/mastery/wrong/last/created/oldest), suspended=1, group(item/material), offset, limit` | 见下「题库查询」 |
| POST `/api/items/batch` | `{ids[], action: suspend/resume/delete}` | `{done, failed:[{id, msg}]}`；逐题追加提交（最多 500），单题失败不影响其它 |
| GET `/api/item` | `id` | 小题 + `sched`、`events`、`records`（含已作废）、`material`、`siblings`、`deleted` |
| POST `/api/item/update` | `{id, changes}` | 小题详情 |
| POST `/api/item/suspend` | `{id, suspended}` | 小题详情 |
| POST `/api/item/delete` | `{id}` | 提交 |
| POST `/api/item/restore` | `{id}` | 小题详情（撤销删除；删除后又录入了同一道题时 400） |
| GET `/api/records` | `item_id, session_id, voided(1/0), genre, grade(low/mid/high 或分值), since(YYYY-MM-DD), has_note=1, offset, limit` | `{records:[{commit_id, item_id, item_name, genre, qtype, material_title, session_id, grade, grade_label, note, at, voided, voided_by, restored_by, restored_from, replaces, item_deleted}], total, offset, limit}`；按日期倒序 |
| POST `/api/record/add` | `{item_id, grade, note, date, session_id}` | 记录（补记；`date` 不能晚于今天） |
| POST `/api/record/update` | `{commit_id, grade?, note?}` | 新记录（旧的作废） |
| POST `/api/record/delete` | `{commit_id}` | 记录（已作废） |
| POST `/api/record/restore` | `{commit_id}` | 新记录（恢复的） |
| GET `/api/material` | `id` | 材料 + 其下小题 |
| POST `/api/material/update` | `{id, changes}` | 材料详情 |
| POST `/api/sessions/plan` | `{minutes, genres[], fill, qtypes[], pinned[], exclude[]}` | `{items:[{id, tag, reason, minutes, item}], minutes, budget, due_total, due_left, busy_skipped, pinned, weak, horizon}`（不写 Ledger；规则见 `algorithm.md`「排复习」）。`item` 是精简行：`id, genre, qtype, no, stem, material_id, material_title, source, status, kind, mastery, decayed, due, last_review, last_grade, reviews, leech, created_at, minutes, material_minutes` |
| GET `/api/sessions` | — | `{sessions:[{id, planned_for, minutes, title, progress, genres}]}` |
| POST `/api/sessions` | `{item_ids, minutes, title}` | 复习视图 |
| GET `/api/session` | `id` | `{id, planned_for, progress, items:[小题 + grade], materials:{id: 材料}}` |
| POST `/api/session/grade` | `{session_id, item_id, grade, note}` | `{commit_id, session}`；已评过则先 void 再评 |
| POST `/api/session/ungrade` | `{session_id, item_id}` | 复习视图 |
| POST `/api/session/cancel` | `{id}` | `{id, cancelled}` |
| POST `/api/review/ai` | `{session_id, item_id, mode(ask/grade/feedback), text, images:[{name,data}], refs:[{text, where:{material_id?, para?, n?, part?}, label?}], history:[{role, text, images:[编号], refs?, tools?:[标签]}], revealed:[已对过答案的题号]}` | SSE 流（见下「复习助手」）；题不在这次复习里 400、复习不存在 404、没配置 AI 400，都在开始流式之前返回 |
| POST `/api/session/blank-lines` | `{session_id,changes:[{item_id,blank_lines}]}` | `{session,updated:[题目id]}`；批量 1–500 道题，全部须属于该 Session，行数是 0–1000 的严格整数；整体验证后同事务追加 `item.update`，同值不提交 |
| GET `/print/session` | `id, answers=1` | 真 A4 分页的打印文档；与页面内预览共用唯一模板、CSS 和浏览器排版引擎，模块从 `/assets/` 加载 |
| GET `/api/mcp/keys` | — | `{keys:[公开元数据],scopes:[{scope,label,default}]}`；不返回摘要或明文 |
| POST `/api/mcp/keys` | `{name?,scopes?,expires_at?}` | `{key:本次唯一明文,metadata:公开元数据}`；未知字段拒绝，`expires_at` 是未来 ISO-8601 时间 |
| POST `/api/mcp/keys/update` | `{key_id,scopes}` | `{key:公开元数据}`；不能复活已吊销或已到期密钥 |
| POST `/api/mcp/keys/revoke` | `{key_id}` | `{key:公开元数据}`；重复吊销不重复改变状态 |

静态文件：`/`、`/clms.html`、`/assets/**`（弱 ETag + `no-cache`）。

### 题库查询（`library.list_items`）

返回 `{items, groups?, total, total_groups?, offset, limit, facets, counts, deleted, library_total}`：

- 行（`items[]` / `groups[].items[]`）：小题字段 + `sched` + `encounters` + `wrong`（又录入次数 + 最近 8 次评分里 ≤ 1 分的次数）。
- `facets = {genre, status, qtype, kind, added, last, grade}`：每个维度各桶的题数，按「除这个维度以外的其它筛选」计算（经典分面计数）。桶可以叠加：近 7 天的题也计入近 30 天。停用的题在 status 里只计 `suspended`。
- `facets.qtype[""]` 是未分类题数；查询参数用 `qtype=__unclassified__`，因为不传 / 传空值表示不按题型过滤。
- `counts`：板块分段上的数字（= `facets.genre`）；`library_total`：未停用的题总数；`deleted`：已删除题数。
- `group=material`：按材料分组（默写按出处，其余单独成组），组顺序跟随组里排得最靠前的题，分页按组计：`groups:[{key, material_id, genre, title, author, source, created_at, size(这篇在库里共几题), items, stats:{total, mastered, new, leech, mastery}}]`。
- `limit` 为空时不分页（Agent 的 `library_search` 依赖这一点）。

### 复习助手（`clms/review_ai.py`、`clms/review_tools.py`）

请求（v0.6）：

- `refs`：学生在卷面上选中后「引用」的文字（最多 6 段、每段 400 字，空白压成一个空格）。`where` 是位置：原文给 `material_id` + `para`（段号），题目给 `n`（卷上题序）+ `part`（`stem` / `answer`）；服务端据此重新写位置标签，`label` 只在编号无效时兜底。只有引用、没写字的提问合法（默认问「解释一下我引用的这段。」）。
- `history`：最近 16 轮。用户那几轮可带 `images`（已存的照片编号）和 `refs`；助手那几轮可带 `tools`（这一轮查阅过什么的标签，如「读《老街的灯》第 2-3 段」），服务端只把它写成一句说明，**不回传查到的内容**。
- `revealed`：学生已经对过答案的题号列表（也兼容旧的布尔值，表示当前这道）；已评分的题一律视为已对过。

回 `text/event-stream`，每条 `data: {json}`，15 秒一次 `: ping`。一条回答由若干**块**组成（思考 / 正文 / 工具），按出现顺序：

| 事件 | 字段 |
| --- | --- |
| `start` | `images`（这次新上传的作答照片编号，按内容哈希存进 `images/`）、`mode`、`agent`（是否只读 Agent；设置里关掉 Agent 模式时为 false，不会有工具块） |
| `block` | 开一个块：`id`、`kind`（thinking / text / tool）；工具块另有 `name`、`status: preparing` |
| `delta` | `id`、`kind`、`text`：思考 / 正文逐字 |
| `end` | `id`：思考 / 正文块结束（思考块据此计时、收起） |
| `tool` | `id`、`status`（running / done / error）；running 时带 `name`、`label`（如「看第 3 题」）；结束时带 `summary`（如「2 段 · 157 字」）和 `result`（查到的内容，最多 2400 字，给学生展开看） |
| `done` | `reply`（最终回答，去掉【建议】行）、`suggestion`（`{grade, grade_label, note}` 的子集或 null）、`usage`（这次各轮之和 `{input, output, estimated}`）、`tools`（查阅次数）、`timing`（`{seconds}`） |
| `error` | `msg` |

客户端断开（停止、离开页面）时服务端关闭生成器，停止信号让模型连接立即断开。助手不写 Ledger；采用建议由前端调 `/api/session/grade`、`/api/record/update`。

### 草稿视图

`{id, status, kind, name, pages, live_seq, running, stats, session_id, agent, queued, created_at, updated_at, images, hint, messages, error, committed, revision, revisions:[{n, at, source}], groups, title, issues:[{gid, iid, message}], dedupe, activity, can_retry}`。`kind` 为 extract / manual / chat / review；`agent` 表示当前是否 Agent 模式。`activity = {started_at, finished_at, steps:[{id,label,kind,status,at,ended_at?}]}`，轮询草稿时可看到真实执行阶段。

`dedupe = {units, new_units, dup_units, groups:{gid: {material_match:{id,title,items}|null, items:{iid:{dup_item_id}}, dictation:{iid:[{blank, key, dup_item_id, dup_in_draft}]}}}}`。

## 打印（`clms/printing.py`）

人工创建 Session 成功后默认进入「打印预览」，再选择「打印」或「开始复习」。复习记录及评分页也能重新打开预览。页面内同源 iframe 与独立 `/print/session` 打印文档使用 `printing.render_session()` 的同一份 HTML / `printing.CSS`，并共同加载 `assets/app/domain/print-layout.js`；不维护第二套前端卷面模板。文档依赖当前服务的 `/assets/`，不作为离线自包含导出。

每张纸固定 210 × 297mm，内容区 178 × 263mm，页内边距上 16mm、左右 16mm、下 18mm；浏览器打印的 `@page` 设置 A4 / 0 边距。屏幕仅在纸外加背景并缩放到可用宽度，打印时移除缩放和工具条，页内几何与预览相同。浏览器等待字体加载并确认 iframe 真实可见后测量内容实际高度；字体等待期间离页则延后初始化，文档卸载取消，不能把隐藏 panel 的零高度当作排版失败。打印媒体保留不可见离屏测量容器的布局，`beforeprint` 也能实际测量。材料长段落按测量结果拆分，超长题干或答题区可在题内跨页并标「续」，不靠整题 `break-inside: avoid` 把长答案裁掉。

材料按篇排：标题（独占一行，可换行）、作者 / 出处（另起一行）、原文（古诗居中），接着是该篇小题的题号、题型、题干、分值与 9mm 答题横线。默写集中在最后，同一模板的多个空合成一行。`answers=1` 或预览勾选「附参考答案」时，参考答案另起页，保持原题号。

打开预览只读，绝不静默修改题库。点击「自动适配当前题」或「自动适配全部题」才测量参考答案：不可见答案与真正答题区具有相同宽度、字体、字号、9mm 行高、`white-space: pre-wrap` 与 `overflow-wrap: anywhere`；使用浏览器真实高度除以实际行高向上取整，不用按字符数估行。空答案建议 0 行；超过 1000 行明确报错；默写保留题面内书写区域。中文长答案、显式换行及空行都由真实排版处理。

预览内的 − / 数值 / + 即刻改变题目行数并重新分页，保存短防抖 450ms，连续点击只落最后的值，批量保存复用 `creation.prepare_item_changes()` 与 Ledger `item.update`。修改的是题库默认 `blank_lines`，刷新或随后创建的 Session 都使用新默认。失败明确显示未保存并可重试；打印 / 开始复习前等待保存；卸载时完成已经授权的保存，迟到回复不再重画页面。录入、草稿和题库编辑仍可设置相同的 0–1000 默认行数。

实际浏览器专项：`python3 tests/e2e_print.py --shots /tmp/clms-print-shots`；单测：`python3 -m unittest discover -s tests -p test_print.py -q`。专项包括长中文、多换行、135 行超长答案跨页、同宽字体与换行规则、即时分页、短防抖、刷新保持、不产生隐式提交、后续 Session、独立打印同 CSS / 页数、真实 PDF、390px 手机、键盘、旧评分及卸载后的异步回复。

## 外部 AI / MCP（`clms/mcp/`、`clms/mcp_http.py`）

官方 Python MCP SDK 是可选依赖，普通 Web、Key 管理和审核授权只用标准库。安装后与 Web 同进程启动独立监听，默认只绑定 `127.0.0.1`，共享现有领域服务、Ledger 写锁和审核权威，网络与模型等待不持有全局写锁：

```bash
python3 -m pip install -r requirements-mcp.txt
python3 clms_engine.py --vault /path/to/vault serve --port 8472 --mcp-port 18473
```

客户端地址为 `http://127.0.0.1:18473/mcp`，使用 `Authorization: Bearer <MCP Key>`，也接受独立的 `X-CLMS-MCP-Key`。Key 不得放在 URL；MCP 端口拒绝查询参数、重复或同时提供两种认证头。Web 端口在业务路由前拒绝 MCP 认证头，所以外部 Key 不能通过普通 HTTP 路由批准自己的操作或管理 Key。生产反向代理可指定 `--mcp-public-url https://example.com/mcp`，只登记该精确 Host / Origin；MCP 本身仍监听 localhost。缺少 SDK 时启用 MCP 明确报安装说明，普通 Web 照常运行。

设置页管理 Key；所有管理响应 `Cache-Control: no-store`。明文只在创建响应中显示一次，磁盘 `语文/.clms/mcp_keys.json` 只保存 SHA-256 摘要与必要元数据，权限 0600；临时文件原子替换，线程锁与操作系统文件锁避免多个进程互相覆盖。存储目录、文件和锁文件拒绝符号链接；损坏的 Key 文件拒绝静默覆盖。Web / 模型 Key 与 MCP Key 完全分离。每次协议请求、工具执行前后、正式写事务等锁后与提交前都重新验证有效期、吊销和当前权限。人工批准旧 MCP 提案也执行同样授权，不从提案恢复密钥明文。

权限及工具由唯一 `clms/tool_catalog.py` 注册表决定：同一 `Tool` 保存 schema、`permission`（read / auto / confirm）和 scopes；发现、直接点名调用和人工批准共用这份权威。共 27 个工具，18 读、9 写；没有任意本地文件读取、任意 HTTP 转发、删除正式数据或批准操作的 MCP 工具。

| Scope | 能力 | 创建默认 |
| --- | --- | --- |
| `clms:read` | 语文题库、材料、概览、推荐、Session、草稿及本人审核操作查询 | 是 |
| `draft:create` | 创建未入库草稿 | 是 |
| `draft:update` | 修订未入库草稿，还须 `clms:read` | 否 |
| `session:create` | 提交正式 Session 审核，还须 `clms:read` | 否 |
| `question:propose` | 提交正式题目修改审核，还须 `clms:read` | 否 |
| `material:propose` | 提交正式材料修改审核，还须 `clms:read` | 否 |
| `essay:read` | 作文题、练习、正式版本、历史评价和自由分类查询 | 是 |
| `essay:images` | 按指定 Version / 页下标读取原图，还须 `essay:read` | 否 |
| `essay:evaluate` | 为指定正式 Version 追加 0–60 分评价，还须 `essay:read` | 否 |
| `essay:note` | 追加讨论笔记 / 下一稿重点，还须 `essay:read` | 否 |
| `essay:classify` | 创建自由分类；给对象组合标签还须 `essay:read` | 否 |

| 工具 | 权限 / 结果 |
| --- | --- |
| `list_taxonomy`、`search_items`、`get_item`、`get_material`、`get_overview`、`get_recommendations`、`list_sessions`、`get_session` | `clms:read`，复用已有学习查询与推荐 |
| `list_drafts`、`get_draft` | `clms:read`，读取现有草稿 |
| `get_operation` | `clms:read`，只返回本 Key 发起的操作及正式领域结果 |
| `create_draft` | `draft:create`，自动执行，留痕，不正式入库 |
| `update_draft` | `clms:read` + `draft:update`，严格当前 revision，自动执行并留痕 |
| `create_review_session` | `clms:read` + `session:create`，返回统一 `pending_confirmation`，人工批准后才创建 |
| `propose_item_update` | `clms:read` + `question:propose`，字段白名单修改提案，等待人工审核 |
| `propose_material_update` | `clms:read` + `material:propose`，等待人工审核 |
| `list_essay_prompts`、`get_essay_prompt`、`get_essay_attempt`、`get_essay_version`、`list_essay_evaluations`、`list_essay_classifications` | `essay:read`，未确认的转写不作为正式全文返回；评价始终绑定原 Version |
| `get_essay_image` | `essay:read` + `essay:images`，一页原生 `ImageContent`，保持原字节，不输出服务器路径 |
| `append_essay_evaluation` | `essay:read` + `essay:evaluate`，自动追加评价，满分 60，保留其它评价 |
| `append_essay_note` | `essay:read` + `essay:note`，自动追加讨论笔记，不保存完整聊天 |
| `create_essay_classification` | `essay:classify`，自动创建自由分类，可选 group |
| `set_essay_classifications` | `essay:read` + `essay:classify`，为题 / Attempt / Version 组合分类，也可按名称创建 |

所有写工具必须提供稳定 `request_id`（1–128 字符，禁止控制字符及 `? # / \\`），由共享审核库以来源、Key、工具和编号作身份。同请求相同内容复用原操作与结果，不同内容返回 `request_conflict`；重复批准不再次执行，正式写的事实与幂等回执同 Ledger 事务，草稿使用自身原子保存回执。提案保留内容快照与 revision，发生内容或版本冲突不得盲写。自动写也通过统一审核权威登记意图与领域回执；辅助数据库不是学习事实源。领域拒绝自动写（例如稿件尚未确认）时 MCP 明确返回工具错误，并保留可查询的操作编号。

作文原图读取仅接受 `version_id` 与从 0 起的严格页下标，必须属于该 Version；图片名限定内容哈希与已支持后缀，用目录 / 文件描述符及 `O_NOFOLLOW` 拒绝路径替换与符号链接，读前后核对文件身份与内容 SHA。上限 8MiB，返回 PNG / JPEG / GIF / WebP 原生图片；可选 Pillow 存在时完整解码，并检查累计 4000 万像素 / 100 帧；不存在时保留签名、大小、哈希及路径安全检查。

每 Key 每分钟最多 120 个协议请求、最多 4 个并发请求。请求体最大 8MiB，声明长度与分块流都受限，总读取期限 30 秒。工具参数按公共 JSON schema 递归验证，拒未知字段、错误类型、布尔冒充数字、越界数字及非法写请求编号。运行库只保留脱敏身份、对象编号、状态、数量、用量和耗时，不保存密钥、作文正文、评价自由文字或原图；工具错误只返回稳定错误码及安全说明。

真实 SDK 专项：`python3 tests/e2e_mcp.py`；安全单测：`python3 -m unittest discover -s tests -p 'test_mcp*.py' -q`。测试使用官方 `mcp==1.28.1` ClientSession 真初始化、发现与调用，覆盖 3 页一稿正式全文 / 原图 / 47 分评价 / 笔记 / 分类，以及 Session 的 MCP 提案 → 网页人工批准 → 稳定 Session id。真实 SDK 通过表示本地协议可用；ChatGPT 账户、外部 HTTPS 代理及真实模型需另行联调，不能将本地 SDK 测试当作账户已连接。

## 脱敏源码包（`clms/source_export.py`）

设置页「导出脱敏源代码」与 `export-source` 命令共用。不依赖 Git：从程序目录收集根目录项目文件（`AGENTS.md`、`README.md`、`clms.html`、`clms_engine.py`、`run.*`、`.gitignore`、`requirements-mcp.txt`）和 `AI/`、`assets/`、`clms/`、`deploy/`、`tests/` 下的源码类型文件（含未提交的改动）；跳过 `语文/`、`.clms`、`__pycache__`、隐藏文件 / 目录、符号链接、日志、备份、`.db`、`mcp_keys.json`、`config.json` 和之前导出的包。文本文件里的当前 `ai_api_key` / `assistant_api_key` 与形如 `sk-…` / `clms_mcp_…` 的串替换成 `<已脱敏>`。zip 顶层目录 `CLMS/`，附 `SOURCE_EXPORT_MANIFEST.txt`（规则、时间、文件数、脱敏替换了哪些文件、文件清单）。文件名 `CLMS-source-sanitized-<UTC 时间>.zip`。

## 命令行（`clms/cli.py`）

`python3 clms_engine.py [--vault 目录] {serve [-p 端口] [--host 地址] [--open] [--mcp-port 独立端口] [--mcp-public-url HTTPS地址] | stats | verify | export-source [-o 目录]}`。`serve` 启动时恢复录入草稿、审核回执、助手运行、OCR 与系统运行中的中断状态；监听非本机地址时打印警告。MCP 端口必须为 1–65535 且不同于 Web 端口；启用失败明确退出，退出 Web 时停止同进程 MCP 服务。CLI 启动的 Web 支持设置页重启，重启时沿用绝对 vault 路径、实际 Web 端口、监听地址、MCP 端口及 public URL，不再次触发 `--open`。Key 生命周期通过设置页与上述人工 HTTP 接口管理。

`verify` 在控制台用 `[OK]` / `[FAIL]` 报告结果，避免 Windows GBK 控制台无法编码特殊符号而在输出时崩溃。

## 服务状态与重启（`clms/service.py`）

`ServiceServer` 为每个 Web 服务独立保存状态，`instance_id` 每次进程启动重新生成；不能用 PID 判断是否完成重启，因为 `os.execv()` 会保留 PID。只有 CLI 启动时设置 `restart_enabled=True`，嵌入式 `make_server()` 默认禁止重启，避免替换测试进程或宿主程序。

`POST /api/service/restart` 必须携带当前 `instance_id`，缺失或过期返回 `409 restart_conflict`；同实例的重复请求只触发一次关闭。它沿用人工 Web 的同源检查和 MCP 凭据拒绝，不属于 Agent/MCP 工具。服务先发送并 flush 成功 JSON，再从独立线程调用 `shutdown()`。CLI 主线程关闭 Web 监听、停止同进程 MCP，使用当前 Python 和原来的服务选项执行 `os.execv()`；工作目录、环境和 systemd 托管关系保留。该操作不调用 `systemctl`，直接运行及 systemd 服务均可使用；外部独立进程不会被重启。状态与重启结果只在内存中，不写 Ledger。

重启会中断正在进行的 AI 请求；已保存的 Ledger、配置和草稿保留，启动按现有恢复流程把中断草稿标为可重试、整理助手/OCR/审核运行状态。尚未保存的浏览器编辑和未落盘的流式片段不会由重启保存。前端只在新 `instance_id` 上线且 `restarting=false` 后刷新；请求断网时先查状态，不自动重发重启。

程序目录由启动入口决定，数据目录由 `--vault` 决定；`run.sh` / `run.bat` 默认把数据放在程序目录的 `语文/.clms`，生产与开发是否隔离取决于部署的入口和 vault 配置，程序不会自动创建第二份生产目录。


## HTTP 注册与升级接口

`http_registry.py` 是唯一 method/path 注册表，重复登记抛错；`http_legacy.py`保留所有旧业务接口，`http_upgrade.py`接审核/历史/运行/留白/status及重启，`http_assistant.py`接助手，`essay_http.py`接作文，`mcp_http.py`接人工Key管理。`server.py`只解析请求、同源/长度/凭据校验、静态文件、JSON/Raw/Stream/AfterResponse响应与异常映射；各vault使用独立Handler类。普通路由接收 vault；显式登记 `route(..., server=True)` 的服务状态/重启路由接收当前服务实例。`AfterResponse(data, callback)` 在 JSON 完整发送后执行回调，用于生命周期操作。Web拒绝Authorization或X-CLMS-MCP-Key，避免外部凭据被当成人工；negative/duplicate Content-Length拒绝，JSON响应no-store。所有写请求仍走同源检查。

| 方法 路径 | 参数 / 返回 |
| --- | --- |
| GET `/api/ai-review/items` | `view=pending|records,source,type,status,q,from,to,offset,limit`；`{items,total,offset,limit,has_more,next_offset}` |
| GET `/api/ai-review/detail` | `id`；`{item}`含原请求、revision、预览、开放字段、修订、决定、结果/commits |
| GET `/api/ai-review/counts` | `{counts:{pending,operations,drafts}}` |
| POST `/api/ai-review/update` | `{id,expected_revision,patch}`；flat字段补丁，只允许原请求开放范围 |
| POST `/api/ai-review/decide` | `{id,expected_revision,decision:approve|reject}`；reviewer固定为human/web，返回`{item}` |
| GET `/api/history` | `q,source,type,from,to,offset,limit`；Ledger学习记录，筛选先于分页 |
| GET `/api/history/detail` | `id=commit_id`；`{item}`含学习payload与稳定领域links |
| GET `/api/runtime/records` | `q,source,type/tool,status,from,to,offset,limit`；脱敏系统运行，不返回正文或凭据 |
| GET `/api/runtime/records/detail` | `id=call_id`；`{item}`含安全参数/结果摘要 |
| GET `/api/status` | `{version,host,port,pid,instance_id,restart_supported,restarting,mcp,mcp_sdk_installed}`；当前 Web 实例状态；`mcp.url` 为服务地址，检查SDK仅探测模块，不导入可选依赖 |
| POST `/api/service/restart` | `{instance_id}`；`{restarting:true,instance_id}` 表示当前实例已接受重启，完成须查询新实例；嵌入式服务返回400，过期实例返回409 |
| GET `/api/assistant/status` | `{enabled,ready,active_run,model}`不返回Key |
| GET `/api/assistant/conversations` | `{conversations}`最近200会话元数据 |
| POST `/api/assistant/conversation/create` | `{title?,context?}`；`{conversation}` |
| GET `/api/assistant/conversation` | `id`；`{conversation}`消息/事件/cursor/runs |
| POST `/api/assistant/message` | `{conversation_id,text,context?}`；`{conversation_id,run_id,queued}`，后台harness运行，同一会话可插话 |
| GET `/api/assistant/events` | `run_id,after,wait<=20`；`{events,cursor,run}`长轮询，不持领域锁 |
| POST `/api/assistant/abort` | `{run_id}`；`{run}`设停止，不撤销已完成学习事实 |

### 作文 HTTP（`clms/essay_http.py`）

| 方法 路径 | 参数 / 返回 |
| --- | --- |
| GET `/api/essays` | `q,classification_id,offset,limit`；题目列表与自由分类 |
| GET `/api/essay/prompt` / `/attempt` / `/version` | `id`；对应完整详情（含父子关系、原图URL、评价/笔记） |
| GET `/api/essay/classifications` | 全部自由分类实体 |
| GET `/api/essay/compare` | `before_id,after_id`；同练习两份确认稿的完整正文与增删diff |
| GET `/api/essay/image` | `version_id,image`；仅返回该版本已归属的原图，拒任意路径 |
| POST `/api/essay/prompt` | `{title,text,requirements?,metadata?}`；新完整作文题 |
| POST `/api/essay/attempt` | `{prompt_id,title?,metadata?}`；同题独立练习 |
| POST `/api/essay/version` | `{attempt_id,images,metadata?}`；1–30页只创建一个稿件 |
| POST `/api/essay/ocr` | `{version_id}`；后台转写，同一版本失败可重试 |
| POST `/api/essay/correct` | `{version_id,text,revision?}`；校对不增加版本 |
| POST `/api/essay/confirm` | `{version_id,text?,revision?}`；正式正文只确认一次 |
| POST `/api/essay/evaluation` | `{version_id,total_score,summary?,strengths?,issues?,suggestions?,dimensions?,evaluator?,model?,metadata?}`；追加0–60评价 |
| POST `/api/essay/evaluation/adopt` | `{version_id,evaluation_id}`；仅采用该版本评价 |
| POST `/api/essay/note` | `{attempt_id,version_id?,text,metadata?}`；追加讨论重点 |
| POST `/api/essay/classification` | `{name,group?,metadata?}`；自由分类，无固定必选组 |
| POST `/api/essay/classify` | `{target_type:prompt|attempt|version,target_id,classification_ids?,names?,metadata?}`；添加组合分类，同事务创建新名 |

网页人工作文操作来源固定web，不允许模型通过body伪造source；模型评价/笔记/分类仍用公共catalog/domain_ops和统一审核auto意图。确认后的稿件不能再OCR或correct，评价绑定具体version_id；详见data.md。OCR网络在Ledger事务外，结果按ocr_running状态/token复核，人工校对/确认按revision复核。图片复用原有内容库，不把正文/原图放进运行摘要或脱敏源码包。
