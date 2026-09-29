# HTTP 接口与命令行

> 速查：`clms/server.py` 用 `@route(method, path)` 登记，每个端点一行；`ThreadingHTTPServer`，默认 `127.0.0.1:8472`。请求 / 响应都是 JSON（打印页和图片除外）。POST 校验 `Origin` 与 `Host` 一致，请求体上限 80MB。

## 错误约定

处理函数抛 `KeyError` → 404，`ValueError` → 400，其它异常 → 500（打印堆栈）。处理函数也可以返回 `Stream`（SSE 生成器，GET / POST 都可以）；连接结束时外壳会关闭生成器，让它的 `finally` 立即执行。响应体 `{"error": "not_found|invalid|server|origin|too_large|bad_json", "msg": "给人看的中文说明"}`。前端 `core/api.js` 把 `msg` 作为 `error.message`。

## 端点

| 方法 路径 | 参数 | 返回 |
| --- | --- | --- |
| GET `/api/summary` | — | 概览统计（见 `algorithm.md`）+ `ai_ready`、`version` |
| GET `/api/taxonomy` | — | `{genres, qtypes:{genre:[题型]}}` |
| GET `/api/config` | — | 配置；密钥不回显，只给 `ai_api_key_set`。含 `ai_context_window`（上下文窗口 token 数，默认 128000，输入框圆环按它算占用） |
| POST `/api/config` | 配置补丁；`ai_api_key` 留空表示不改，`clear_api_key: true` 清除 | 同 GET |
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
| GET `/api/items` | `genre, qtype, status(新录入/巩固中/待攻克/已掌握/leech/suspended/deleted), kind(skill/recall), added(7/30/90/old), last(never/7/30/old), grade(none/low/mid/high), material, q, sort(priority/due/mastery/wrong/last/created/oldest), suspended=1, group(item/material), offset, limit` | 见下「题库查询」 |
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
| GET `/print/session` | `id, answers=1` | A4 打印页（自包含 HTML） |

静态文件：`/`、`/clms.html`、`/assets/**`（弱 ETag + `no-cache`）。

### 题库查询（`library.list_items`）

返回 `{items, groups?, total, total_groups?, offset, limit, facets, counts, deleted, library_total}`：

- 行（`items[]` / `groups[].items[]`）：小题字段 + `sched` + `encounters` + `wrong`（又录入次数 + 最近 8 次评分里 ≤ 1 分的次数）。
- `facets = {genre, status, qtype, kind, added, last, grade}`：每个维度各桶的题数，按「除这个维度以外的其它筛选」计算（经典分面计数）。桶可以叠加：近 7 天的题也计入近 30 天。停用的题在 status 里只计 `suspended`。
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

材料按篇排：标题（独占一行，可换行）、作者 / 出处（另起一行，小号灰字）、原文（古诗居中），接着是该篇的小题：题号、题型标签、题干、分值、按 `blank_lines` 画的 9mm 答题横线。默写集中在最后，同一模板的几个空合成一行。`answers=1` 时另起一页列答案（`<li value=题号>`）。页面右上角有「打印」按钮，打印时隐藏。

## 脱敏源码包（`clms/source_export.py`）

设置页「导出脱敏源代码」与 `export-source` 命令共用。不依赖 Git：从程序目录收集根目录项目文件（`AGENTS.md`、`README.md`、`clms.html`、`clms_engine.py`、`run.*`、`.gitignore`）和 `AI/`、`assets/`、`clms/`、`deploy/`、`tests/` 下的源码类型文件（含未提交的改动）；跳过 `语文/`、`.clms`、`__pycache__`、隐藏文件 / 目录、符号链接、日志、备份、`.db`、`config.json` 和之前导出的包。文本文件里的当前 `ai_api_key` 与形如 `sk-…` 的串替换成 `<已脱敏>`。zip 顶层目录 `CLMS/`，附 `SOURCE_EXPORT_MANIFEST.txt`（规则、时间、文件数、脱敏替换了哪些文件、文件清单）。文件名 `CLMS-source-sanitized-<UTC 时间>.zip`。

## 命令行（`clms/cli.py`）

`python3 clms_engine.py [--vault 目录] {serve [-p 端口] [--host 地址] [--open] | stats | verify | export-source [-o 目录]}`。`serve` 启动时先 `drafts.recover()`；监听非本机地址时打印警告。

`verify` 在控制台用 `[OK]` / `[FAIL]` 报告结果，避免 Windows GBK 控制台无法编码特殊符号而在输出时崩溃。
